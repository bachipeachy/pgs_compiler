"""
Evidence projection — higher-level derived views over EvidenceQuery.

ISOLATION INVARIANT: This module MUST NOT import from compiler internals.
The evidence_graph.json schema is the only contract.

DTO types:
    StageView  — summary of a single compilation stage

Projection class:
    EvidenceProjection — derived semantic views for visualization and analysis

Methods:
    stage_summary()          — per-stage breakdown: event counts by family, artifacts written
    artifact_provenance(fqdn)— all events in the causality chain for an FQDN
    node_creation_events()   — all node_created events in event order
    construction_summary()   — S5 IR build events grouped by IR type + construction_complete
"""

from dataclasses import dataclass, field
from typing import Any

from .evidence_query import EvidenceQuery, TraceEventDTO


@dataclass
class StageView:
    """
    Derived summary of a single compilation stage.

    Fields:
        stage            — stage name (e.g. 'S1_EXTRACT')
        event_count      — total events emitted in this stage
        families         — {family_name: count} for events in this stage
        written_artifacts— output_paths from artifact_written events in this stage
    """
    stage: str
    event_count: int
    families: dict[str, int] = field(default_factory=dict)
    written_artifacts: list[str] = field(default_factory=list)


class EvidenceProjection:
    """
    Higher-level derived views over an EvidenceQuery.

    All views are computed lazily from the underlying EvidenceQuery.
    Results are typed DTOs or plain dicts/lists — never raw JSON.

    This is the stable projection layer between EvidenceQuery and rendering
    surfaces (visualization, AI tooling, debugging, replay).
    """

    def __init__(self, query: EvidenceQuery) -> None:
        self._q = query

    # --- Stage summary ---

    def stage_summary(self) -> dict[str, StageView]:
        """
        Per-stage breakdown: event counts, family distribution, written artifacts.

        Returns a dict keyed by stage name in first-seen stage order.
        """
        views: dict[str, StageView] = {}

        for stage in self._q.stages():
            events = self._q.by_stage(stage)
            families: dict[str, int] = {}
            for ev in events:
                families[ev.family] = families.get(ev.family, 0) + 1

            artifacts = sorted(
                ev.detail["output_path"]
                for ev in events
                if ev.operation == "artifact_written" and "output_path" in ev.detail
            )

            views[stage] = StageView(
                stage=stage,
                event_count=len(events),
                families=families,
                written_artifacts=artifacts,
            )

        return views

    # --- Provenance ---

    def artifact_provenance(self, fqdn: str) -> list[TraceEventDTO]:
        """
        All events in the causality chain for a given subject FQDN.

        Finds all events whose subject_fqdn matches fqdn, then walks the
        causality chain backward from each one (BFS, root-first).

        Returns the union of all ancestor chains, deduplicated, root-first
        (sorted by event_id).
        """
        seed_events = [
            ev for ev in self._q.by_family("DISCOVERY")
            + self._q.by_family("TOPOLOGY")
            + self._q.by_family("CONSTRUCTION")
            + self._q.by_family("PROJECTION")
            + self._q.by_family("MATERIALIZATION")
            + self._q.by_family("VERIFICATION")
            + self._q.by_family("ADDRESSING")
            + self._q.by_family("GOVERNANCE")
            if ev.subject_fqdn == fqdn
        ]

        seen: set[int] = set()
        result: list[TraceEventDTO] = []

        for ev in seed_events:
            chain = self._q.causality_chain(ev.event_id)
            for ancestor in chain:
                if ancestor.event_id not in seen:
                    seen.add(ancestor.event_id)
                    result.append(ancestor)

        return sorted(result, key=lambda e: e.event_id)

    # --- Node creation ---

    def node_creation_events(self) -> list[TraceEventDTO]:
        """
        All node_created events in event_id order.

        These represent the canonical set of topology nodes discovered during
        S1 extraction.
        """
        return sorted(
            self._q.by_operation("node_created"),
            key=lambda e: e.event_id,
        )

    # --- Construction summary ---

    def construction_summary(self) -> dict[str, Any]:
        """
        S5 construction phase summary.

        Returns a dict with:
            ct_ir_built          — list of events for CT IR builds
            cs_ir_built          — list of events for CS IR builds
            cc_projection_built  — list of events for CC projection builds
            construction_complete— the construction_complete event (or None)
            total_ir_builds      — total count of IR build events across all kinds
        """
        ct_events = self._q.by_operation("ct_ir_built")
        cs_events = self._q.by_operation("cs_ir_built")
        cc_events = self._q.by_operation("cc_projection_built")
        complete_events = self._q.by_operation("construction_complete")

        return {
            "ct_ir_built": sorted(ct_events, key=lambda e: e.event_id),
            "cs_ir_built": sorted(cs_events, key=lambda e: e.event_id),
            "cc_projection_built": sorted(cc_events, key=lambda e: e.event_id),
            "construction_complete": complete_events[0] if complete_events else None,
            "total_ir_builds": len(ct_events) + len(cs_events) + len(cc_events),
        }
