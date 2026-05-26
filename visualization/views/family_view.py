"""
Family View — event family distribution as deterministic DOT (→ PNG).

ISOLATION INVARIANT: Only imports from visualization.consumers. No compiler internals.

What it shows:
    - One node per EventFamily present in the evidence graph
    - Family node labeled with: family name, event count, operations used
    - Stage → Family edges (dashed): which stages contribute to which families
    - Gives semantic observability: correct family tagging = correct edge topology

DTO:
    FamilyViewDTO — family names, counts, per-stage contributions

Renderer:
    render_family_view(view) → DOT string (internal only)
    write_family_view_png(view, output_path) → writes PNG

The DOT output is deterministic: same FamilyViewDTO → same DOT string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..consumers.evidence_query import EvidenceQuery
from ._png_writer import write_png_from_dot


@dataclass
class FamilyStageStat:
    """How many events of a given family came from a specific stage."""
    stage: str
    count: int


@dataclass
class FamilyViewDTO:
    """
    Event family distribution summary.

    Fields:
        structure_id      — identifier for the compiled structure
        families          — sorted list of family names present
        event_count_by_family — {family: total event count}
        operations_by_family  — {family: sorted list of distinct operations}
        stage_contributions   — {family: [FamilyStageStat]} stages that emit this family
    """
    structure_id: str
    families: list[str]
    event_count_by_family: dict[str, int] = field(default_factory=dict)
    operations_by_family: dict[str, list[str]] = field(default_factory=dict)
    stage_contributions: dict[str, list[FamilyStageStat]] = field(default_factory=dict)


def build_family_view(query: EvidenceQuery) -> FamilyViewDTO:
    """
    Build a FamilyViewDTO from an EvidenceQuery.

    Only calls EvidenceQuery methods — no compiler imports, no inference.
    """
    families = query.families()

    event_count_by_family: dict[str, int] = {}
    operations_by_family: dict[str, list[str]] = {}
    stage_contributions: dict[str, list[FamilyStageStat]] = {}

    for family in families:
        events = query.by_family(family)
        event_count_by_family[family] = len(events)
        operations_by_family[family] = sorted({ev.operation for ev in events})

        # Count per-stage contributions to this family
        stage_counts: dict[str, int] = {}
        for ev in events:
            stage_counts[ev.stage] = stage_counts.get(ev.stage, 0) + 1
        stage_contributions[family] = [
            FamilyStageStat(stage=s, count=c)
            for s, c in sorted(stage_counts.items())
        ]

    return FamilyViewDTO(
        structure_id=query.structure_id,
        families=families,
        event_count_by_family=event_count_by_family,
        operations_by_family=operations_by_family,
        stage_contributions=stage_contributions,
    )


# Family → greyscale fill
_FAMILY_FILL: dict[str, str] = {
    "DISCOVERY":       "#f0f0f0",
    "TOPOLOGY":        "#e0e0e0",
    "ADDRESSING":      "#d4d4d4",
    "GOVERNANCE":      "#c8c8c8",
    "CONSTRUCTION":    "#bcbcbc",
    "PROJECTION":      "#b0b0b0",
    "MATERIALIZATION": "#a4a4a4",
    "VERIFICATION":    "#989898",
}
_DEFAULT_FILL = "#f8f8f8"


def render_family_view(view: FamilyViewDTO) -> str:
    """
    Render a FamilyViewDTO as a DOT string (internal representation only).

    Family nodes are rectangles labeled with name + event count + operations.
    Stage → Family edges show which stage contributes to which family.
    Deterministic: same FamilyViewDTO → same DOT string.
    """
    lines: list[str] = []
    lines.append(f'digraph "family_view_{view.structure_id}" {{')
    lines.append('  graph [rankdir=LR fontname="monospace" label="Event Family View" pad="0.5" nodesep=0.6];')
    lines.append('  node  [fontname="monospace" fontsize=9 style=filled shape=box];')
    lines.append('  edge  [fontname="monospace" fontsize=8];')
    lines.append("")

    # Stage nodes (left column)
    all_stages: set[str] = set()
    for stats in view.stage_contributions.values():
        for stat in stats:
            all_stages.add(stat.stage)

    lines.append("  // Stage nodes")
    for stage in sorted(all_stages):
        lines.append(f'  s_{stage} [label="{stage}" fillcolor="#ffffff" shape=ellipse];')
    lines.append("")

    # Family nodes (right column)
    lines.append("  // Family nodes")
    for family in view.families:
        count = view.event_count_by_family.get(family, 0)
        ops = view.operations_by_family.get(family, [])
        ops_label = "\\n".join(ops) if ops else "(none)"
        fill = _FAMILY_FILL.get(family, _DEFAULT_FILL)
        label = f"{family}\\n{count} events\\n{ops_label}"
        lines.append(f'  f_{family} [label="{label}" fillcolor="{fill}"];')
    lines.append("")

    # Stage → Family edges (dashed, labeled with count)
    lines.append("  // Stage → Family contribution edges")
    for family in view.families:
        stats = view.stage_contributions.get(family, [])
        for stat in stats:
            lines.append(
                f'  s_{stat.stage} -> f_{family}'
                f' [style=dashed label="{stat.count}" color="#555555"];'
            )

    lines.append("}")
    return "\n".join(lines)


def write_family_view_png(view: FamilyViewDTO, output_path: Path) -> bool:
    """
    Render FamilyViewDTO → PNG using graphviz (dot command).

    DOT is internal only — not written to disk.
    Returns True if PNG was written, False if graphviz is unavailable.
    """
    return write_png_from_dot(render_family_view(view), output_path)
