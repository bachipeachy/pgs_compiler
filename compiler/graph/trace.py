"""
TraceEvent — immutable compiler evidence event.

Each compilation stage emits trace events recording semantic derivation:
topology construction, addressing, legality verification, edge synthesis,
admissibility construction, projection, and materialization.

This is NOT logging. It is governed compiler evidence analogous to
runtime traces in PGS. "Proven by trace" symmetry:
  - Runtime proves execution realization
  - Compiler proves admissibility construction

Visualization tooling consumes these events — no UI assumptions
exist inside compiler stages.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


_EMPTY_DETAIL: MappingProxyType = MappingProxyType({})


@dataclass(frozen=True)
class TraceEvent:
    """
    Immutable compiler evidence event.

    Emitted by compilation stages to record the semantic derivation
    path through EXTRACT → CANONICALIZE → SEMANTIC_ADDRESSING →
    GOVERN → CONSTRUCT → PROJECT → MATERIALIZE → VERIFY.

    Fields:
        stage: Compilation stage that emitted this event (e.g., "S1_EXTRACT")
        operation: What happened (e.g., "node_created", "edge_typed", "address_allocated")
        subject_fqdn: The FQDN of the artifact this event concerns (empty if global)
        subject_token: The semantic address token (-1 if not yet addressed)
        detail: Immutable dict of event-specific properties
    """

    stage: str
    operation: str
    subject_fqdn: str
    subject_token: int
    detail: MappingProxyType
    event_id: int = -1
    parent_event_id: int = -1
    family: str = ""

    @staticmethod
    def create(
        stage: str,
        operation: str,
        subject_fqdn: str = "",
        subject_token: int = -1,
        detail: dict[str, Any] | None = None,
        parent_event_id: int = -1,
        family: str = "",
    ) -> "TraceEvent":
        """Factory with proper immutable wrapping."""
        return TraceEvent(
            stage=stage,
            operation=operation,
            subject_fqdn=subject_fqdn,
            subject_token=subject_token,
            detail=MappingProxyType(detail) if detail else _EMPTY_DETAIL,
            event_id=-1,
            parent_event_id=parent_event_id,
            family=family,
        )

    def with_event_id(self, event_id: int) -> "TraceEvent":
        """Return a copy with event_id assigned."""
        return TraceEvent(
            stage=self.stage,
            operation=self.operation,
            subject_fqdn=self.subject_fqdn,
            subject_token=self.subject_token,
            detail=self.detail,
            event_id=event_id,
            parent_event_id=self.parent_event_id,
            family=self.family,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for evidence artifact output."""
        return {
            "event_id": self.event_id,
            "stage": self.stage,
            "operation": self.operation,
            "family": self.family,
            "subject_fqdn": self.subject_fqdn,
            "subject_token": self.subject_token,
            "parent_event_id": self.parent_event_id,
            "detail": dict(self.detail),
        }
