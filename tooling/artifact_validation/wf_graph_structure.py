"""
wf_graph_structure.py — Workflow Graph Canonical Structure (V0)

CONSTITUTIONAL ROLE
-------------------
This module defines the authoritative in-memory representation of a workflow
graph for Workflow Graph Validation (WGV).

It answers exactly one question:
    "What graph was authored?"

It does NOT answer:
- Whether the graph is valid
- Whether the graph is executable
- Whether the graph terminates
- Whether the graph obeys protocol_validator rules

Those concerns belong to wf_graph_rules.py.

DESIGN PRINCIPLES
-----------------
1. Structure is validation-agnostic
2. Invalid graphs must be representable
3. EXIT is semantic, not a node
4. No inference, no normalization
5. Deterministic and explicit
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set, List, Optional


# ---------------------------------------------------------------------
# Node kind
# ---------------------------------------------------------------------

class NodeKind(str, Enum):
    """
    Executable node kinds recognized by WGV.

    NOTE:
    - This enum does not validate correctness.
    - Unknown or illegal kinds may still appear upstream;
      those are handled by graph rules, not here.
    """
    IN = "IN"
    OP = "OP"


# ---------------------------------------------------------------------
# EXIT semantic sink
# ---------------------------------------------------------------------

# EXIT is NOT a node.
# It represents graph termination and has no outgoing edges.
EXIT = "__EXIT__"


# ---------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class Edge:
    """
    A directed, result-keyed edge.

    Semantics:
        (from_node, result_status) -> to_node | EXIT
    """
    from_node: str
    result_status: str
    to_node: str  # node_code or EXIT


# ---------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------

@dataclass
class Node:
    """
    A workflow graph node.

    This structure is intentionally permissive:
    - declared_results may be empty
    - outgoing edges may be missing or partial
    - nodes may be unreachable

    All such conditions are validated elsewhere.
    """

    node_code: str
    kind: NodeKind

    # Result statuses this node claims it may emit
    declared_results: Set[str] = field(default_factory=set)

    # Outgoing edges keyed by result_status
    outgoing: Dict[str, Edge] = field(default_factory=dict)


# ---------------------------------------------------------------------
# GraphStructure
# ---------------------------------------------------------------------

@dataclass
class GraphStructure:
    """
    Canonical, validation-agnostic workflow graph representation.

    This is the sole structure over which WGV rules operate.
    """

    nodes: Dict[str, Node]
    entry_node: Optional[str]
    edges: List[Edge]

    # --------------------------------------------------------------
    # Access helpers (no validation)
    # --------------------------------------------------------------

    def get_node(self, node_code: str) -> Optional[Node]:
        return self.nodes.get(node_code)

    def all_node_codes(self) -> Set[str]:
        return set(self.nodes.keys())

    def incoming_edge_count(self, node_code: str) -> int:
        return sum(1 for e in self.edges if e.to_node == node_code)

    def exit_edges(self) -> List[Edge]:
        return [e for e in self.edges if e.to_node == EXIT]
