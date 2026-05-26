"""
Structural DAG view — compilation topology as a deterministic DOT graph (→ PNG).

ISOLATION INVARIANT: Only imports from visualization.consumers. No compiler internals.

What it shows:
    - Stages as graph clusters (S1 through S7)
    - Events as labeled nodes within their stage cluster
    - CAUSALITY edges (solid) between events
    - STAGE_SEQUENCE edges (dashed) between stage boundaries

DTO:
    StructuralDAGView — all data needed to render the DAG

Renderer:
    render_structural_dag(view) → DOT string (internal only)
    write_structural_dag_png(view, output_path) → writes PNG

DOT is internal only — not written to disk.
The PNG output is deterministic: same evidence_graph.json → same PNG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..consumers.evidence_query import EvidenceQuery, TraceEventDTO, EvidenceEdgeDTO
from ._png_writer import write_png_from_dot


@dataclass
class StructuralDAGView:
    """
    All data needed to render the structural compilation DAG.

    Fields:
        structure_id     — identifier for the compiled structure
        stages           — stage names in first-seen order
        events_by_stage  — {stage: [TraceEventDTO]} in emission order
        causality_edges  — all CAUSALITY EvidenceEdgeDTOs
        sequence_edges   — all STAGE_SEQUENCE EvidenceEdgeDTOs
    """
    structure_id: str
    stages: list[str]
    events_by_stage: dict[str, list[TraceEventDTO]] = field(default_factory=dict)
    causality_edges: list[EvidenceEdgeDTO] = field(default_factory=list)
    sequence_edges: list[EvidenceEdgeDTO] = field(default_factory=list)


def build_structural_dag_view(query: EvidenceQuery) -> StructuralDAGView:
    """
    Build a StructuralDAGView from an EvidenceQuery.

    Only calls EvidenceQuery methods — no compiler imports, no inference.
    """
    stages = query.stages()

    events_by_stage: dict[str, list[TraceEventDTO]] = {
        stage: sorted(query.by_stage(stage), key=lambda e: e.event_id)
        for stage in stages
    }

    causality_edges = query.edges_by_kind("CAUSALITY")
    sequence_edges = query.edges_by_kind("STAGE_SEQUENCE")

    return StructuralDAGView(
        structure_id=query.structure_id,
        stages=stages,
        events_by_stage=events_by_stage,
        causality_edges=causality_edges,
        sequence_edges=sequence_edges,
    )


# Family → fill color (monochrome-safe greyscale shades)
_FAMILY_COLORS: dict[str, str] = {
    "DISCOVERY":     "#f0f0f0",
    "TOPOLOGY":      "#e0e0e0",
    "ADDRESSING":    "#d0d0d0",
    "GOVERNANCE":    "#c0c0c0",
    "CONSTRUCTION":  "#b0b0b0",
    "PROJECTION":    "#a0a0a0",
    "MATERIALIZATION": "#909090",
    "VERIFICATION":  "#808080",
}
_DEFAULT_COLOR = "#f8f8f8"


def render_structural_dag(view: StructuralDAGView) -> str:
    """
    Render a StructuralDAGView as a DOT string.

    Output is deterministic: same StructuralDAGView → same DOT string.
    Stages appear as subgraph clusters. Events are labeled by operation.
    CAUSALITY edges are solid. STAGE_SEQUENCE edges are dashed.
    """
    lines: list[str] = []
    lines.append(f'digraph "structural_dag_{view.structure_id}" {{')
    lines.append('  graph [rankdir=TB fontname="monospace" label="" pad="0.5"];')
    lines.append('  node  [fontname="monospace" fontsize=9 shape=box style=filled];')
    lines.append('  edge  [fontname="monospace" fontsize=8];')
    lines.append("")

    # One subgraph cluster per stage
    for idx, stage in enumerate(view.stages):
        events = view.events_by_stage.get(stage, [])
        lines.append(f"  subgraph cluster_{idx} {{")
        lines.append(f'    label="{stage}";')
        lines.append('    style=rounded;')
        lines.append('    color="#444444";')
        lines.append("")

        for ev in events:
            color = _FAMILY_COLORS.get(ev.family, _DEFAULT_COLOR)
            label = f"{ev.operation}\\n(#{ev.event_id})"
            if ev.subject_fqdn:
                # Truncate long FQDNs to keep nodes readable
                fqdn = ev.subject_fqdn
                if len(fqdn) > 40:
                    fqdn = fqdn[:37] + "..."
                label += f"\\n{fqdn}"
            lines.append(
                f'    n{ev.event_id} [label="{label}" fillcolor="{color}"];'
            )

        lines.append("  }")
        lines.append("")

    # CAUSALITY edges — solid
    lines.append("  // CAUSALITY edges")
    for edge in sorted(view.causality_edges, key=lambda e: (e.source_event_id, e.target_event_id)):
        lines.append(
            f"  n{edge.source_event_id} -> n{edge.target_event_id}"
            ' [style=solid color="#333333" penwidth=1.2];'
        )
    lines.append("")

    # STAGE_SEQUENCE edges — dashed, bold
    lines.append("  // STAGE_SEQUENCE edges")
    for edge in sorted(view.sequence_edges, key=lambda e: e.source_event_id):
        lines.append(
            f"  n{edge.source_event_id} -> n{edge.target_event_id}"
            ' [style=dashed color="#000000" penwidth=2.0 label="STAGE_SEQ"];'
        )

    lines.append("}")
    return "\n".join(lines)


def write_structural_dag_png(view: StructuralDAGView, output_path: Path) -> bool:
    """
    Render StructuralDAGView → PNG using graphviz (dot command).

    DOT is internal only — not written to disk.
    Returns True if PNG was written, False if graphviz is unavailable.
    """
    return write_png_from_dot(render_structural_dag(view), output_path)
