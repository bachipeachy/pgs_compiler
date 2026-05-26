"""
Compiler graph — core data model.

The canonical, immutable, topology-native semantic graph
representing the entire governed system. Graph is the sole
semantic authority from which all projections are derived.
"""

from pgs_compiler.compiler.graph.types import NodeKind, EdgeKind
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.edge import Edge
from pgs_compiler.compiler.graph.graph import Graph
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.evidence import (
    EventFamily,
    EventKind,
    EVENT_KIND_TO_FAMILY,
    EvidenceEdge,
    EvidenceEdgeKind,
    EvidenceGraph,
)

__all__ = [
    "NodeKind",
    "EdgeKind",
    "Node",
    "Edge",
    "Graph",
    "TraceEvent",
    "State",
    "EventFamily",
    "EventKind",
    "EVENT_KIND_TO_FAMILY",
    "EvidenceEdge",
    "EvidenceEdgeKind",
    "EvidenceGraph",
]
