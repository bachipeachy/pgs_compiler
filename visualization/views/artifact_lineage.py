"""
Artifact Lineage view — causality chain per materialized artifact (DOT format).

ISOLATION INVARIANT: Only imports from visualization.consumers. No compiler internals.

Core question answered: "Why does this artifact exist?"

What it shows:
    For each materialized output path, walk the causality chain backward
    from the artifact_written event to its root cause — showing every event
    that directly or indirectly caused the artifact to be produced.

DTO:
    ArtifactLineageView — one lineage chain per materialized artifact

Renderer:
    render_artifact_lineage(view) → DOT string

Each artifact appears as a cluster. Events are nodes shaped by their family.
Causality edges flow from root → leaf (cause → effect), so graph reads top-to-bottom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..consumers.evidence_query import EvidenceQuery, TraceEventDTO
from ..consumers.evidence_projection import EvidenceProjection
from ._png_writer import write_png_from_dot


@dataclass
class ArtifactLineage:
    """
    Causality chain for a single materialized artifact.

    Fields:
        output_path  — the artifact output path (from artifact_written event detail)
        chain        — events in causality chain, root-first (ascending event_id)
    """
    output_path: str
    chain: list[TraceEventDTO] = field(default_factory=list)


@dataclass
class ArtifactLineageView:
    """
    All lineage chains for a compiled structure.

    Fields:
        structure_id — identifier for the compiled structure
        lineages     — one ArtifactLineage per materialized output, sorted by path
    """
    structure_id: str
    lineages: list[ArtifactLineage] = field(default_factory=list)


def build_artifact_lineage_view(query: EvidenceQuery) -> ArtifactLineageView:
    """
    Build an ArtifactLineageView from an EvidenceQuery.

    Only calls EvidenceQuery and EvidenceProjection methods.
    No compiler imports, no inference beyond what the consumer layer provides.
    """
    projection = EvidenceProjection(query)
    lineages: list[ArtifactLineage] = []

    for output_path in sorted(query.materialized_outputs()):
        # Find the artifact_written event for this path
        written_events = [
            ev for ev in query.by_operation("artifact_written")
            if ev.detail.get("output_path") == output_path
        ]
        if not written_events:
            continue

        # Use subject_fqdn of the written event as the provenance key
        written_ev = written_events[0]
        fqdn = written_ev.subject_fqdn

        # Walk causality chain via EvidenceProjection
        chain = projection.artifact_provenance(fqdn) if fqdn else query.causality_chain(written_ev.event_id)

        lineages.append(ArtifactLineage(
            output_path=output_path,
            chain=chain,
        ))

    return ArtifactLineageView(
        structure_id=query.structure_id,
        lineages=lineages,
    )


# Family → shape (DOT node shape)
_FAMILY_SHAPE: dict[str, str] = {
    "DISCOVERY":       "ellipse",
    "TOPOLOGY":        "diamond",
    "ADDRESSING":      "parallelogram",
    "GOVERNANCE":      "hexagon",
    "CONSTRUCTION":    "box",
    "PROJECTION":      "trapezium",
    "MATERIALIZATION": "invhouse",
    "VERIFICATION":    "octagon",
}
_DEFAULT_SHAPE = "box"


def render_artifact_lineage(view: ArtifactLineageView) -> str:
    """
    Render an ArtifactLineageView as a DOT string.

    Each artifact gets a subgraph cluster containing its causality chain.
    Events are shaped by family. Edges flow cause → effect (top-to-bottom).
    Output is deterministic: same ArtifactLineageView → same DOT string.
    """
    lines: list[str] = []
    lines.append(f'digraph "artifact_lineage_{view.structure_id}" {{')
    lines.append('  graph [rankdir=TB fontname="monospace" label="Artifact Lineage" pad="0.5"];')
    lines.append('  node  [fontname="monospace" fontsize=9 style=filled fillcolor="#f4f4f4"];')
    lines.append('  edge  [fontname="monospace" fontsize=8 style=solid color="#555555"];')
    lines.append("")

    # Track all event_id nodes already emitted to avoid duplicates across chains
    emitted_nodes: set[int] = set()

    for lidx, lineage in enumerate(view.lineages):
        # Truncate long paths for cluster label
        label = lineage.output_path
        if len(label) > 60:
            label = "..." + label[-57:]

        lines.append(f"  subgraph cluster_lineage_{lidx} {{")
        lines.append(f'    label="{label}";')
        lines.append('    style=rounded; color="#666666";')
        lines.append("")

        for ev in lineage.chain:
            if ev.event_id in emitted_nodes:
                continue
            emitted_nodes.add(ev.event_id)
            shape = _FAMILY_SHAPE.get(ev.family, _DEFAULT_SHAPE)
            op_label = ev.operation
            node_label = f"{op_label}\\n(#{ev.event_id} {ev.stage})"
            lines.append(
                f'    n{ev.event_id} [label="{node_label}" shape={shape}];'
            )

        lines.append("  }")
        lines.append("")

    # Causality edges within each chain (cause → effect ascending event_id pairs)
    lines.append("  // Causality edges within lineage chains")
    emitted_edges: set[tuple[int, int]] = set()

    for lineage in view.lineages:
        # Edges: consecutive pairs in causality chain (root → ... → artifact)
        # The chain is root-first; adjacent events are causally connected.
        # We use the fact that chain[i].event_id < chain[i+1].event_id (monotonic).
        for i in range(len(lineage.chain) - 1):
            src_id = lineage.chain[i].event_id
            tgt_id = lineage.chain[i + 1].event_id
            key = (src_id, tgt_id)
            if key not in emitted_edges:
                emitted_edges.add(key)
                lines.append(f"  n{src_id} -> n{tgt_id};")

    lines.append("}")
    return "\n".join(lines)


def write_artifact_lineage_png(view: ArtifactLineageView, output_path: Path) -> bool:
    """
    Render ArtifactLineageView → PNG using graphviz (dot command).

    DOT is internal only — not written to disk.
    Returns True if PNG was written, False if graphviz is unavailable.
    """
    return write_png_from_dot(render_artifact_lineage(view), output_path)
