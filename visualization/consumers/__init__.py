"""
Evidence consumer contract — stable query API over evidence_graph.json.

These modules are the ONLY sanctioned interface between evidence_graph.json
and all downstream consumers: visualization, AI, debugging, replay, IDE tooling.

Consumers MUST NOT import from compiler/graph/* or any other compiler internal.
The evidence_graph.json schema IS the contract.

Modules:
    evidence_reader    — load evidence_graph.json → EvidenceQuery
    evidence_query     — TraceEventDTO, EvidenceEdgeDTO, EvidenceQuery
    evidence_projection — higher-level derived views (StageView, provenance)
"""

from .evidence_reader import load_evidence_graph
from .evidence_query import EvidenceQuery, TraceEventDTO, EvidenceEdgeDTO, EVIDENCE_QUERY_CONTRACT_VERSION
from .evidence_projection import EvidenceProjection, StageView

__all__ = [
    "load_evidence_graph",
    "EvidenceQuery",
    "TraceEventDTO",
    "EvidenceEdgeDTO",
    "EvidenceProjection",
    "StageView",
    "EVIDENCE_QUERY_CONTRACT_VERSION",
]
