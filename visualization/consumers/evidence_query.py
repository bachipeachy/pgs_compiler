"""
Evidence query contract — consumer API over deserialized evidence_graph.json.

CONTRACT VERSION: v0  (EVIDENCE_QUERY_CONTRACT_VERSION)

EvidenceQuery wraps the deserialized graph and provides typed, indexed
semantic access. All operations return DTOs — never raw JSON dicts.

ISOLATION INVARIANT: This module MUST NOT import from compiler internals.
The evidence_graph.json schema is the only contract.

DTO types:
    TraceEventDTO  — a single compiler trace event
    EvidenceEdgeDTO — a typed directed edge between two events

Query methods:
    by_family(family)           — all events for a semantic concern group
    by_stage(stage)             — all events from a compilation stage
    by_operation(operation)     — all events of a specific operation kind
    event_by_id(event_id)       — single event lookup
    downstream(event_id)        — direct CAUSALITY children
    upstream(event_id)          — direct CAUSALITY parents
    causality_chain(event_id)   — all ancestors, root-first (BFS)
    stage_sequence()            — STAGE_SEQUENCE edge pairs in order
    materialized_outputs()      — output_paths from artifact_written events
    edges_by_kind(kind)         — all edges of CAUSALITY or STAGE_SEQUENCE
    families()                  — all event families present
    stages()                    — all stages in event order

CONTRACT STABILITY POLICY
--------------------------
This module is a protocol surface. The following rules apply:

FROZEN (breaking changes require a contract version bump):
  - All public method signatures on EvidenceQuery
  - All dataclass fields on TraceEventDTO and EvidenceEdgeDTO
  - Return types of all query methods (list[TraceEventDTO], etc.)
  - Semantics of CAUSALITY and STAGE_SEQUENCE edge traversal
  - Behavior of causality_chain() BFS ordering (root-first)
  - Behavior of stage_sequence() sort order (by source event_id)

ADDITIVE (permitted without version bump):
  - New query methods on EvidenceQuery
  - New properties (read-only, non-breaking)
  - New fields on EvidenceQuery with default values only

PROHIBITED regardless of version:
  - Importing from compiler/graph/* or any compiler internal
  - Exposing raw dict results (all returns must be DTOs or stdlib types)
  - Adding mutable state to DTOs
  - Returning None from methods that currently return lists

DEPRECATION RULE:
  A method may be deprecated (docstring + DeprecationWarning) in one
  contract version and removed in the next. No silent removal.
"""

from dataclasses import dataclass, field
from typing import Any

# Contract version — bump when a FROZEN surface changes.
# Consumers may assert: from visualization.consumers import EVIDENCE_QUERY_CONTRACT_VERSION
EVIDENCE_QUERY_CONTRACT_VERSION: str = "v0"


@dataclass
class TraceEventDTO:
    """
    DTO for a single compiler trace event.

    Sourced from the 'events' array in evidence_graph.json.
    Schema-stable: fields match evidence_graph.json event object.
    """
    event_id: int
    stage: str
    operation: str
    family: str
    subject_fqdn: str
    subject_token: int
    parent_event_id: int
    detail: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "TraceEventDTO":
        return TraceEventDTO(
            event_id=d.get("event_id", -1),
            stage=d.get("stage", ""),
            operation=d.get("operation", ""),
            family=d.get("family", ""),
            subject_fqdn=d.get("subject_fqdn", ""),
            subject_token=d.get("subject_token", -1),
            parent_event_id=d.get("parent_event_id", -1),
            detail=d.get("detail", {}),
        )


@dataclass
class EvidenceEdgeDTO:
    """
    DTO for a typed directed edge between two trace events.

    Sourced from the 'edges' array in evidence_graph.json.
    kind is one of: "CAUSALITY", "STAGE_SEQUENCE"
    """
    source_event_id: int
    target_event_id: int
    kind: str

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "EvidenceEdgeDTO":
        return EvidenceEdgeDTO(
            source_event_id=d["source_event_id"],
            target_event_id=d["target_event_id"],
            kind=d["kind"],
        )


class EvidenceQuery:
    """
    Consumer API for evidence_graph.json.

    Provides semantic query operations over the compiler evidence graph.
    All results are typed DTOs. Internal indexes are built once at construction.

    This is the stable boundary between evidence_graph.json and all consumers.
    Visualization, AI tooling, replay systems, and debuggers all go through here.
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self._structure_id: str = raw.get("structure_id", "")
        self._compiler_version: str = raw.get("compiler_version", "")
        self._evidence_graph_hash: str = raw.get("evidence_graph_hash", "")

        # Deserialize
        self._events: list[TraceEventDTO] = [
            TraceEventDTO.from_dict(e) for e in raw.get("events", [])
        ]
        self._edges: list[EvidenceEdgeDTO] = [
            EvidenceEdgeDTO.from_dict(e) for e in raw.get("edges", [])
        ]

        # Build indexes — O(N) construction, O(1) amortized queries
        self._by_id: dict[int, TraceEventDTO] = {
            e.event_id: e for e in self._events
        }
        self._by_family: dict[str, list[TraceEventDTO]] = {}
        self._by_stage: dict[str, list[TraceEventDTO]] = {}
        self._by_operation: dict[str, list[TraceEventDTO]] = {}
        self._edges_from: dict[int, list[EvidenceEdgeDTO]] = {}  # src → edges out
        self._edges_to: dict[int, list[EvidenceEdgeDTO]] = {}    # tgt → edges in
        self._stage_order: list[str] = []  # stages in first-seen order

        _seen_stages: set[str] = set()
        for event in self._events:
            self._by_family.setdefault(event.family, []).append(event)
            self._by_stage.setdefault(event.stage, []).append(event)
            self._by_operation.setdefault(event.operation, []).append(event)
            if event.stage not in _seen_stages:
                self._stage_order.append(event.stage)
                _seen_stages.add(event.stage)

        for edge in self._edges:
            self._edges_from.setdefault(edge.source_event_id, []).append(edge)
            self._edges_to.setdefault(edge.target_event_id, []).append(edge)

    # --- Identity ---

    @property
    def structure_id(self) -> str:
        return self._structure_id

    @property
    def compiler_version(self) -> str:
        return self._compiler_version

    @property
    def evidence_graph_hash(self) -> str:
        return self._evidence_graph_hash

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    # --- Flat queries ---

    def by_family(self, family: str) -> list[TraceEventDTO]:
        """All events for a semantic concern group (e.g. 'DISCOVERY')."""
        return list(self._by_family.get(family, []))

    def by_stage(self, stage: str) -> list[TraceEventDTO]:
        """All events emitted by a compilation stage (e.g. 'S1_EXTRACT')."""
        return list(self._by_stage.get(stage, []))

    def by_operation(self, operation: str) -> list[TraceEventDTO]:
        """All events of a specific operation kind (e.g. 'artifact_written')."""
        return list(self._by_operation.get(operation, []))

    def event_by_id(self, event_id: int) -> TraceEventDTO | None:
        """Single event lookup by event_id. None if not found."""
        return self._by_id.get(event_id)

    # --- Graph traversal ---

    def downstream(self, event_id: int) -> list[TraceEventDTO]:
        """
        Direct CAUSALITY children of this event.

        Returns events that this event caused/gated.
        """
        return [
            self._by_id[e.target_event_id]
            for e in self._edges_from.get(event_id, [])
            if e.kind == "CAUSALITY" and e.target_event_id in self._by_id
        ]

    def upstream(self, event_id: int) -> list[TraceEventDTO]:
        """
        Direct CAUSALITY parents of this event.

        Returns events that caused/gated this event.
        """
        return [
            self._by_id[e.source_event_id]
            for e in self._edges_to.get(event_id, [])
            if e.kind == "CAUSALITY" and e.source_event_id in self._by_id
        ]

    def causality_chain(self, event_id: int) -> list[TraceEventDTO]:
        """
        All ancestors in the causality chain, root-first (BFS).

        Traverses CAUSALITY edges backward from event_id to all roots.
        Returns [] if event_id not found.
        """
        result: list[TraceEventDTO] = []
        visited: set[int] = set()
        queue: list[int] = [event_id]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            event = self._by_id.get(current)
            if event:
                result.append(event)
            for parent in self.upstream(current):
                if parent.event_id not in visited:
                    queue.append(parent.event_id)

        return result

    def stage_sequence(self) -> list[tuple[TraceEventDTO, TraceEventDTO]]:
        """
        STAGE_SEQUENCE edge pairs in order (source, target).

        Each pair is (last event of stage N, first event of stage N+1).
        """
        pairs = [
            (self._by_id[e.source_event_id], self._by_id[e.target_event_id])
            for e in self._edges
            if e.kind == "STAGE_SEQUENCE"
            and e.source_event_id in self._by_id
            and e.target_event_id in self._by_id
        ]
        return sorted(pairs, key=lambda p: p[0].event_id)

    # --- Derived queries ---

    def materialized_outputs(self) -> list[str]:
        """
        Sorted list of output_paths from all artifact_written events.

        These are the canonical JSON artifacts written to the snapshot.
        """
        return sorted(
            event.detail["output_path"]
            for event in self.by_operation("artifact_written")
            if "output_path" in event.detail
        )

    def edges_by_kind(self, kind: str) -> list[EvidenceEdgeDTO]:
        """All edges of a specific kind: 'CAUSALITY' or 'STAGE_SEQUENCE'."""
        return [e for e in self._edges if e.kind == kind]

    def families(self) -> list[str]:
        """All event families present in the graph, sorted."""
        return sorted(self._by_family.keys())

    def stages(self) -> list[str]:
        """All stages present in the graph, in first-seen event order."""
        return list(self._stage_order)
