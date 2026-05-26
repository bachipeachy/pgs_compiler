"""
Compiler evidence taxonomy — constitutional observability vocabulary.

Defines the formal evidence model for compiler trace events:
- EventFamily: semantic concern groups (DISCOVERY, TOPOLOGY, etc.)
- EventKind: typed event kinds matching compiler operations
- Typed payload dataclasses for each EventKind
- EvidenceGraph: stable contract container for structured trace access

This is EG-3 of the EvidenceGraph rollout. Events are semantic state
transitions — never procedural (ENTER_LOOP, CALL_FUNCTION). Every
event records a semantic derivation step in admissibility construction.

EG-1: Formal taxonomy (EventFamily, EventKind, typed payloads, EvidenceGraph)
EG-2: Explicit family tagging at all call sites; typed evidence edges
EG-3: Stable materialization — evidence_graph.json written per structure
EG-4: Replay and integrity verification (hash, causality validation)
"""

from dataclasses import dataclass, fields
from enum import Enum
from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.graph.trace import TraceEvent


# ---------------------------------------------------------------------------
# Event Family — semantic concern groups
# ---------------------------------------------------------------------------

class EventFamily(str, Enum):
    """
    Semantic concern groups for compiler evidence events.

    Each family corresponds to a compilation concern, NOT a stage.
    A stage may emit events from multiple families, and a family
    may span multiple stages. The grouping is by semantic meaning.
    """
    DISCOVERY       = "DISCOVERY"
    TOPOLOGY        = "TOPOLOGY"
    ADDRESSING      = "ADDRESSING"
    GOVERNANCE      = "GOVERNANCE"
    CONSTRUCTION    = "CONSTRUCTION"
    PROJECTION      = "PROJECTION"
    MATERIALIZATION = "MATERIALIZATION"
    VERIFICATION    = "VERIFICATION"
    ATTESTATION     = "ATTESTATION"


# ---------------------------------------------------------------------------
# Event Kind — typed event identifiers
# ---------------------------------------------------------------------------

class EventKind(str, Enum):
    """
    Typed compiler evidence event kinds.

    Each value matches an existing TraceEvent operation string exactly.
    This ensures backward compatibility — existing events are already
    valid EventKind values.
    """
    # DISCOVERY
    DISCOVERY_COMPLETE    = "discovery_complete"
    NODE_CREATED          = "node_created"
    # TOPOLOGY
    EDGE_TYPED            = "edge_typed"
    # ADDRESSING
    ADDRESSES_ALLOCATED   = "addresses_allocated"
    # GOVERNANCE
    GOVERNANCE_COMPLETE   = "governance_complete"
    # CONSTRUCTION
    CT_IR_BUILT           = "ct_ir_built"
    CS_IR_BUILT           = "cs_ir_built"
    CC_PROJECTION_BUILT   = "cc_projection_built"
    CONSTRUCTION_COMPLETE = "construction_complete"
    # PROJECTION
    ARTIFACT_PROJECTED    = "artifact_projected"
    VOCABULARY_PROJECTED  = "vocabulary_projected"
    TOKENIZED_PROJECTED   = "tokenized_projected"
    EVIDENCE_PROJECTED    = "evidence_projected"
    # MATERIALIZATION
    ARTIFACT_WRITTEN              = "artifact_written"
    VOCABULARY_MATERIALIZED       = "vocabulary_materialized"
    TOKENIZED_MATERIALIZED        = "tokenized_materialized"
    EVIDENCE_MATERIALIZED         = "evidence_materialized"
    EVIDENCE_GRAPH_MATERIALIZED   = "evidence_graph_materialized"
    CONFORMANCE_WRITTEN           = "conformance_written"
    # VERIFICATION
    VERIFICATION_COMPLETE = "verification_complete"
    # ATTESTATION
    ATTESTATION_COMPLETE  = "attestation_complete"


# ---------------------------------------------------------------------------
# EventKind → EventFamily mapping
# ---------------------------------------------------------------------------

EVENT_KIND_TO_FAMILY: dict[EventKind, EventFamily] = {
    # DISCOVERY
    EventKind.DISCOVERY_COMPLETE:    EventFamily.DISCOVERY,
    EventKind.NODE_CREATED:          EventFamily.DISCOVERY,
    # TOPOLOGY
    EventKind.EDGE_TYPED:            EventFamily.TOPOLOGY,
    # ADDRESSING
    EventKind.ADDRESSES_ALLOCATED:   EventFamily.ADDRESSING,
    # GOVERNANCE
    EventKind.GOVERNANCE_COMPLETE:   EventFamily.GOVERNANCE,
    # CONSTRUCTION
    EventKind.CT_IR_BUILT:           EventFamily.CONSTRUCTION,
    EventKind.CS_IR_BUILT:           EventFamily.CONSTRUCTION,
    EventKind.CC_PROJECTION_BUILT:   EventFamily.CONSTRUCTION,
    EventKind.CONSTRUCTION_COMPLETE: EventFamily.CONSTRUCTION,
    # PROJECTION
    EventKind.ARTIFACT_PROJECTED:    EventFamily.PROJECTION,
    EventKind.VOCABULARY_PROJECTED:  EventFamily.PROJECTION,
    EventKind.TOKENIZED_PROJECTED:   EventFamily.PROJECTION,
    EventKind.EVIDENCE_PROJECTED:    EventFamily.PROJECTION,
    # MATERIALIZATION
    EventKind.ARTIFACT_WRITTEN:              EventFamily.MATERIALIZATION,
    EventKind.VOCABULARY_MATERIALIZED:       EventFamily.MATERIALIZATION,
    EventKind.TOKENIZED_MATERIALIZED:        EventFamily.MATERIALIZATION,
    EventKind.EVIDENCE_MATERIALIZED:         EventFamily.MATERIALIZATION,
    EventKind.EVIDENCE_GRAPH_MATERIALIZED:   EventFamily.MATERIALIZATION,
    EventKind.CONFORMANCE_WRITTEN:           EventFamily.MATERIALIZATION,
    # VERIFICATION
    EventKind.VERIFICATION_COMPLETE: EventFamily.VERIFICATION,
    # ATTESTATION
    EventKind.ATTESTATION_COMPLETE:  EventFamily.ATTESTATION,
}


# ---------------------------------------------------------------------------
# Typed payload dataclasses — one per EventKind
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscoveryCompletePayload:
    artifacts_discovered: int

    def to_dict(self) -> dict[str, Any]:
        return {"artifacts_discovered": self.artifacts_discovered}


@dataclass(frozen=True)
class NodeCreatedPayload:
    kind: str
    layer_code: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "layer_code": self.layer_code}


@dataclass(frozen=True)
class EdgeTypedPayload:
    target: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "kind": self.kind}


@dataclass(frozen=True)
class AddressesAllocatedPayload:
    address_table_size: int
    address_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "address_table_size": self.address_table_size,
            "address_hash": self.address_hash,
        }


@dataclass(frozen=True)
class GovernanceCompletePayload:
    errors: int
    warnings: int

    def to_dict(self) -> dict[str, Any]:
        return {"errors": self.errors, "warnings": self.warnings}


@dataclass(frozen=True)
class CtIrBuiltPayload:
    atom_stream_length: int

    def to_dict(self) -> dict[str, Any]:
        return {"atom_stream_length": self.atom_stream_length}


@dataclass(frozen=True)
class CsIrBuiltPayload:
    """CS IR built — no detail fields (emitted without detail dict)."""

    def to_dict(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True)
class CcProjectionBuiltPayload:
    pipeline_steps: int

    def to_dict(self) -> dict[str, Any]:
        return {"pipeline_steps": self.pipeline_steps}


@dataclass(frozen=True)
class ConstructionCompletePayload:
    ir_count: int

    def to_dict(self) -> dict[str, Any]:
        return {"ir_count": self.ir_count}


@dataclass(frozen=True)
class ArtifactProjectedPayload:
    artifact_type: str

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_type": self.artifact_type}


@dataclass(frozen=True)
class VocabularyProjectedPayload:
    address_count: int
    projection_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "address_count": self.address_count,
            "projection_hash": self.projection_hash,
        }


@dataclass(frozen=True)
class TokenizedProjectedPayload:
    node_count: int
    edge_count: int
    adjacency_count: int
    projection_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "adjacency_count": self.adjacency_count,
            "projection_hash": self.projection_hash,
        }


@dataclass(frozen=True)
class EvidenceProjectedPayload:
    node_count: int
    edge_count: int
    event_count: int
    projection_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "event_count": self.event_count,
            "projection_hash": self.projection_hash,
        }


@dataclass(frozen=True)
class ArtifactWrittenPayload:
    output_path: str
    artifact_type: str

    def to_dict(self) -> dict[str, Any]:
        return {"output_path": self.output_path, "artifact_type": self.artifact_type}


@dataclass(frozen=True)
class VocabularyMaterializedPayload:
    structure_id: str
    output_dir: str
    files_written: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure_id": self.structure_id,
            "output_dir": self.output_dir,
            "files_written": self.files_written,
        }


@dataclass(frozen=True)
class TokenizedMaterializedPayload:
    structure_id: str
    output_dir: str
    files_written: int
    node_count: int
    edge_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure_id": self.structure_id,
            "output_dir": self.output_dir,
            "files_written": self.files_written,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
        }


@dataclass(frozen=True)
class EvidenceMaterializedPayload:
    structure_id: str
    output_dir: str
    files_written: int
    node_count: int
    edge_count: int
    event_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure_id": self.structure_id,
            "output_dir": self.output_dir,
            "files_written": self.files_written,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "event_count": self.event_count,
        }


@dataclass(frozen=True)
class EvidenceGraphMaterializedPayload:
    structure_id: str
    output_dir: str
    event_count: int
    edge_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure_id": self.structure_id,
            "output_dir": self.output_dir,
            "event_count": self.event_count,
            "edge_count": self.edge_count,
        }


@dataclass(frozen=True)
class ConformanceWrittenPayload:
    output_path: str
    test_data_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": self.output_path,
            "test_data_source": self.test_data_source,
        }


@dataclass(frozen=True)
class VerificationCompletePayload:
    files_checked: int
    errors: int
    verified: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_checked": self.files_checked,
            "errors": self.errors,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class AttestationCompletePayload:
    structure_id: str
    tokenized_projection_hash: str
    attestation_hash: str
    signing_algorithm: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure_id": self.structure_id,
            "tokenized_projection_hash": self.tokenized_projection_hash,
            "attestation_hash": self.attestation_hash,
            "signing_algorithm": self.signing_algorithm,
        }


# ---------------------------------------------------------------------------
# EventKind → Payload type mapping
# ---------------------------------------------------------------------------

EVENT_KIND_TO_PAYLOAD: dict[EventKind, type] = {
    EventKind.DISCOVERY_COMPLETE:    DiscoveryCompletePayload,
    EventKind.NODE_CREATED:          NodeCreatedPayload,
    EventKind.EDGE_TYPED:            EdgeTypedPayload,
    EventKind.ADDRESSES_ALLOCATED:   AddressesAllocatedPayload,
    EventKind.GOVERNANCE_COMPLETE:   GovernanceCompletePayload,
    EventKind.CT_IR_BUILT:           CtIrBuiltPayload,
    EventKind.CS_IR_BUILT:           CsIrBuiltPayload,
    EventKind.CC_PROJECTION_BUILT:   CcProjectionBuiltPayload,
    EventKind.CONSTRUCTION_COMPLETE: ConstructionCompletePayload,
    EventKind.ARTIFACT_PROJECTED:    ArtifactProjectedPayload,
    EventKind.VOCABULARY_PROJECTED:  VocabularyProjectedPayload,
    EventKind.TOKENIZED_PROJECTED:   TokenizedProjectedPayload,
    EventKind.EVIDENCE_PROJECTED:    EvidenceProjectedPayload,
    EventKind.ARTIFACT_WRITTEN:              ArtifactWrittenPayload,
    EventKind.VOCABULARY_MATERIALIZED:       VocabularyMaterializedPayload,
    EventKind.TOKENIZED_MATERIALIZED:        TokenizedMaterializedPayload,
    EventKind.EVIDENCE_MATERIALIZED:         EvidenceMaterializedPayload,
    EventKind.EVIDENCE_GRAPH_MATERIALIZED:   EvidenceGraphMaterializedPayload,
    EventKind.CONFORMANCE_WRITTEN:           ConformanceWrittenPayload,
    EventKind.VERIFICATION_COMPLETE: VerificationCompletePayload,
    EventKind.ATTESTATION_COMPLETE:  AttestationCompletePayload,
}


def resolve_family(operation: str) -> str:
    """
    Resolve EventFamily for an operation string.

    Returns the EventFamily value if the operation matches a known
    EventKind, or empty string if unknown.
    """
    try:
        kind = EventKind(operation)
        return EVENT_KIND_TO_FAMILY[kind].value
    except (ValueError, KeyError):
        return ""


# ---------------------------------------------------------------------------
# Evidence edge types — typed relationships between events
# ---------------------------------------------------------------------------

class EvidenceEdgeKind(str, Enum):
    """
    Typed relationships between compiler evidence events.

    CAUSALITY: parent event caused/gated child event.
    STAGE_SEQUENCE: last event of stage N → first event of stage N+1.
    """
    CAUSALITY      = "CAUSALITY"
    STAGE_SEQUENCE = "STAGE_SEQUENCE"


@dataclass(frozen=True)
class EvidenceEdge:
    """Typed directed edge between two evidence events."""
    source_event_id: int
    target_event_id: int
    kind: EvidenceEdgeKind

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_event_id": self.source_event_id,
            "target_event_id": self.target_event_id,
            "kind": self.kind.value,
        }


def _infer_causality_edges(
    events: tuple[TraceEvent, ...],
    edges: list[EvidenceEdge],
) -> None:
    """
    Infer causality edges from event ordering patterns.

    S1: discovery_complete → node_created (discovery gates node creation)
    S5: ct/cs/cc_ir_built → construction_complete (IR builds aggregate)
    """
    # S1 pattern: discovery_complete → node_created
    discovery_id = -1
    for event in events:
        if event.operation == EventKind.DISCOVERY_COMPLETE.value:
            discovery_id = event.event_id
        elif event.operation == EventKind.NODE_CREATED.value and discovery_id >= 0:
            edges.append(EvidenceEdge(
                source_event_id=discovery_id,
                target_event_id=event.event_id,
                kind=EvidenceEdgeKind.CAUSALITY,
            ))

    # S5 pattern: ir builds → construction_complete
    ir_ids: list[int] = []
    for event in events:
        if event.operation in (
            EventKind.CT_IR_BUILT.value,
            EventKind.CS_IR_BUILT.value,
            EventKind.CC_PROJECTION_BUILT.value,
        ):
            ir_ids.append(event.event_id)
        elif event.operation == EventKind.CONSTRUCTION_COMPLETE.value:
            for ir_id in ir_ids:
                edges.append(EvidenceEdge(
                    source_event_id=ir_id,
                    target_event_id=event.event_id,
                    kind=EvidenceEdgeKind.CAUSALITY,
                ))
            ir_ids.clear()


def _infer_stage_sequence_edges(
    events: tuple[TraceEvent, ...],
    edges: list[EvidenceEdge],
) -> None:
    """
    Infer stage sequence edges from stage transitions.

    Last event of stage N → first event of stage N+1.
    """
    prev_stage = ""
    prev_event_id = -1
    for event in events:
        if event.event_id < 0:
            continue
        if event.stage != prev_stage and prev_stage and prev_event_id >= 0:
            edges.append(EvidenceEdge(
                source_event_id=prev_event_id,
                target_event_id=event.event_id,
                kind=EvidenceEdgeKind.STAGE_SEQUENCE,
            ))
        prev_stage = event.stage
        prev_event_id = event.event_id


# ---------------------------------------------------------------------------
# EvidenceGraph — stable contract container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceGraph:
    """
    Structured evidence graph built from compiler trace events.

    Events are typed graph nodes. Relationships between events are
    typed edges (CAUSALITY, STAGE_SEQUENCE). This is the stable
    contract object for observability consumers.

    Immutable once constructed.
    """
    events: tuple[TraceEvent, ...]
    edges: tuple[EvidenceEdge, ...]
    families: MappingProxyType   # EventFamily.value -> tuple of event_ids
    causality: MappingProxyType  # event_id -> tuple of child event_ids
    event_index: MappingProxyType  # event_id -> TraceEvent

    @staticmethod
    def from_trace_events(events: tuple[TraceEvent, ...]) -> "EvidenceGraph":
        """
        Build EvidenceGraph from accumulated trace events.

        Groups events by family, builds the causality index,
        and infers typed edges from event ordering patterns.
        """
        # Build family index
        family_buckets: dict[str, list[int]] = {}
        for family in EventFamily:
            family_buckets[family.value] = []

        # Build event index and family grouping
        event_index: dict[int, TraceEvent] = {}
        for event in events:
            if event.event_id >= 0:
                event_index[event.event_id] = event

            family = event.family
            if not family:
                family = resolve_family(event.operation)
            if family in family_buckets:
                family_buckets[family].append(event.event_id)

        # Build causality index (parent_id -> list of child_ids)
        causality: dict[int, list[int]] = {}
        for event in events:
            if event.parent_event_id >= 0 and event.event_id >= 0:
                if event.parent_event_id not in causality:
                    causality[event.parent_event_id] = []
                causality[event.parent_event_id].append(event.event_id)

        # Infer typed edges
        inferred_edges: list[EvidenceEdge] = []
        _infer_stage_sequence_edges(events, inferred_edges)
        _infer_causality_edges(events, inferred_edges)

        # Merge inferred causality into causality index
        for edge in inferred_edges:
            if edge.kind == EvidenceEdgeKind.CAUSALITY:
                if edge.source_event_id not in causality:
                    causality[edge.source_event_id] = []
                causality[edge.source_event_id].append(edge.target_event_id)

        return EvidenceGraph(
            events=events,
            edges=tuple(inferred_edges),
            families=MappingProxyType({
                k: tuple(v) for k, v in family_buckets.items()
            }),
            causality=MappingProxyType({
                k: tuple(v) for k, v in causality.items()
            }),
            event_index=MappingProxyType(event_index),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for evidence_graph.json output."""
        return {
            "event_count": self.event_count,
            "edge_count": self.edge_count,
            "events": [e.to_dict() for e in self.events],
            "edges": [e.to_dict() for e in self.edges],
            "families": {k: list(v) for k, v in self.families.items()},
        }

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def edges_by_kind(self, kind: EvidenceEdgeKind) -> tuple[EvidenceEdge, ...]:
        """Get all edges of a specific kind."""
        return tuple(e for e in self.edges if e.kind == kind)

    def events_in_family(self, family: EventFamily) -> tuple[TraceEvent, ...]:
        """Get all events belonging to a semantic family."""
        ids = self.families.get(family.value, ())
        return tuple(
            self.event_index[eid] for eid in ids if eid in self.event_index
        )

    def children_of(self, event_id: int) -> tuple[TraceEvent, ...]:
        """Get child events in the causality chain."""
        child_ids = self.causality.get(event_id, ())
        return tuple(
            self.event_index[eid] for eid in child_ids if eid in self.event_index
        )
