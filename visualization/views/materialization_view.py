"""
Materialization View — stage-by-stage artifact output as deterministic DOT (→ PNG).

ISOLATION INVARIANT: Only imports from visualization.consumers. No compiler internals.

What it shows:
    - One node per compilation stage
    - Artifact output listed per stage
    - Stage sequence edges showing compilation order
    - Projection provenance: which stages wrote how many artifacts

DTO:
    MaterializationViewDTO — per-stage artifact write summary

Renderer:
    render_materialization_view(view) → DOT string (internal only)
    write_materialization_view_png(view, output_path) → writes PNG

The DOT output is deterministic: same MaterializationViewDTO → same DOT string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..consumers.evidence_query import EvidenceQuery
from ..consumers.evidence_projection import EvidenceProjection, StageView
from ._png_writer import write_png_from_dot


@dataclass
class MaterializationViewDTO:
    """
    Per-stage artifact materialization summary.

    Fields:
        structure_id     — identifier for the compiled structure
        stage_views      — {stage: StageView} in stage order
        stage_order      — stage names in first-seen order
        total_artifacts  — total count of artifact_written events across all stages
    """
    structure_id: str
    stage_views: dict[str, StageView]
    stage_order: list[str]
    total_artifacts: int


def build_materialization_view(query: EvidenceQuery) -> MaterializationViewDTO:
    """
    Build a MaterializationViewDTO from an EvidenceQuery.

    Only calls EvidenceQuery and EvidenceProjection methods.
    No compiler imports, no inference beyond what the consumer layer provides.
    """
    projection = EvidenceProjection(query)
    stage_views = projection.stage_summary()
    stage_order = query.stages()

    total_artifacts = sum(
        len(sv.written_artifacts) for sv in stage_views.values()
    )

    return MaterializationViewDTO(
        structure_id=query.structure_id,
        stage_views=stage_views,
        stage_order=stage_order,
        total_artifacts=total_artifacts,
    )


def render_materialization_view(view: MaterializationViewDTO) -> str:
    """
    Render a MaterializationViewDTO as a DOT string (internal representation only).

    Stages are nodes in compilation order with artifact counts labeled.
    Stage sequence edges (dashed) connect stages left-to-right.
    Stage nodes are shaded darker when they write more artifacts.
    Deterministic: same MaterializationViewDTO → same DOT string.
    """
    lines: list[str] = []
    lines.append(f'digraph "materialization_view_{view.structure_id}" {{')
    lines.append('  graph [rankdir=LR fontname="monospace" label="Materialization View" pad="0.5" nodesep=0.8];')
    lines.append('  node  [fontname="monospace" fontsize=9 style=filled shape=box];')
    lines.append('  edge  [fontname="monospace" fontsize=8 style=dashed color="#333333" penwidth=1.5];')
    lines.append("")

    # Compute max artifacts for relative shading
    max_artifacts = max(
        (len(sv.written_artifacts) for sv in view.stage_views.values()),
        default=1,
    ) or 1

    lines.append("  // Stage nodes")
    for stage in view.stage_order:
        sv = view.stage_views.get(stage)
        if sv is None:
            continue

        artifact_count = len(sv.written_artifacts)
        event_count = sv.event_count

        # Greyscale fill: more artifacts → darker (from #f0f0f0 to #808080)
        shade = int(0xf0 - (artifact_count / max_artifacts) * 0x70)
        fill_hex = f"#{shade:02x}{shade:02x}{shade:02x}"

        # Build label: stage name + counts + top artifacts (up to 5)
        artifact_lines = sv.written_artifacts[:5]
        if len(sv.written_artifacts) > 5:
            artifact_lines = artifact_lines + [f"... +{len(sv.written_artifacts) - 5} more"]

        artifact_label = "\\n".join(
            _shorten_path(p) for p in artifact_lines
        ) if artifact_lines else "(no artifacts)"

        label = (
            f"{stage}\\n"
            f"{event_count} events | {artifact_count} artifacts\\n"
            f"{artifact_label}"
        )
        lines.append(f'  s_{stage} [label="{label}" fillcolor="{fill_hex}"];')

    lines.append("")

    # Stage sequence edges (in stage_order order)
    lines.append("  // Stage sequence edges")
    for i in range(len(view.stage_order) - 1):
        src = view.stage_order[i]
        tgt = view.stage_order[i + 1]
        lines.append(f"  s_{src} -> s_{tgt};")

    lines.append("}")
    return "\n".join(lines)


def write_materialization_view_png(view: MaterializationViewDTO, output_path: Path) -> bool:
    """
    Render MaterializationViewDTO → PNG using graphviz (dot command).

    DOT is internal only — not written to disk.
    Returns True if PNG was written, False if graphviz is unavailable.
    """
    return write_png_from_dot(render_materialization_view(view), output_path)


def _shorten_path(path: str, max_len: int = 50) -> str:
    """Shorten a path for display, keeping the filename visible."""
    if len(path) <= max_len:
        return path
    return "..." + path[-(max_len - 3):]
