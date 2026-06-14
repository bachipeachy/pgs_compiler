"""
Graph — immutable semantic graph container.

Graph is the SOLE SEMANTIC AUTHORITY of the governed system.
All projections (canonical JSON, tokenized, vocabulary, trace) are
derived deterministic materializations of this graph.

No mutation methods exist. Each stage returns a NEW Graph
via the builder class.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.graph.types import NodeKind, EdgeKind
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.edge import Edge


# Sentinel empty containers
_EMPTY_NODE_MAP: MappingProxyType = MappingProxyType({})
_EMPTY_EDGE_TUPLE: tuple[Edge, ...] = ()
_EMPTY_ADJACENCY: MappingProxyType = MappingProxyType({})
_EMPTY_ADDRESS_TABLE: MappingProxyType = MappingProxyType({})


@dataclass(frozen=True)
class Graph:
    """
    Immutable semantic graph — the sole semantic authority.

    Contains all nodes (governed artifacts), all edges (typed relationships),
    semantic address tables, and pre-computed adjacency for O(1) traversal.

    IMMUTABILITY GUARANTEE:
    - frozen=True on dataclass
    - All collections are MappingProxyType or tuple (immutable)
    - No mutation methods — use GraphBuilder to construct new graphs
    - Each compilation stage produces a NEW Graph
    """

    # --- Nodes ---
    nodes: MappingProxyType  # str (FQDN) → Node

    # --- Edges ---
    edges: tuple[Edge, ...]  # All edges (frozen tuple, deterministic order)

    # --- Semantic address tables ---
    address_table: MappingProxyType   # str (identity) → int (address) — forward lookup
    reverse_table: MappingProxyType   # int (address) → str (identity) — reverse lookup

    # --- Pre-computed adjacency ---
    outgoing: MappingProxyType  # str (FQDN) → tuple[Edge, ...] — outgoing edges
    incoming: MappingProxyType  # str (FQDN) → tuple[Edge, ...] — incoming edges

    # --- Topology hashes ---
    topology_hash: str          # Hash of graph structure (nodes + edges)
    address_hash: str           # Hash of semantic address allocation

    @staticmethod
    def empty() -> "Graph":
        """Create an empty Graph (initial state before S1 EXTRACT)."""
        return Graph(
            nodes=_EMPTY_NODE_MAP,
            edges=_EMPTY_EDGE_TUPLE,
            address_table=_EMPTY_ADDRESS_TABLE,
            reverse_table=_EMPTY_ADDRESS_TABLE,
            outgoing=_EMPTY_ADJACENCY,
            incoming=_EMPTY_ADJACENCY,
            topology_hash="",
            address_hash="",
        )

    @property
    def node_count(self) -> int:
        """Number of nodes in the graph."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Number of edges in the graph."""
        return len(self.edges)

    def has_node(self, fqdn: str) -> bool:
        """Check if a node exists by FQDN."""
        return fqdn in self.nodes

    def get_node(self, fqdn: str) -> Node | None:
        """Get a node by FQDN, or None if not found."""
        return self.nodes.get(fqdn)

    def get_outgoing(self, fqdn: str, kind: EdgeKind | None = None) -> tuple[Edge, ...]:
        """
        Get outgoing edges from a node, optionally filtered by kind.

        Args:
            fqdn: Source node FQDN
            kind: Optional edge kind filter

        Returns:
            Tuple of matching outgoing edges (empty tuple if none)
        """
        edges = self.outgoing.get(fqdn, ())
        if kind is None:
            return edges
        return tuple(e for e in edges if e.kind == kind)

    def get_incoming(self, fqdn: str, kind: EdgeKind | None = None) -> tuple[Edge, ...]:
        """
        Get incoming edges to a node, optionally filtered by kind.

        Args:
            fqdn: Target node FQDN
            kind: Optional edge kind filter

        Returns:
            Tuple of matching incoming edges (empty tuple if none)
        """
        edges = self.incoming.get(fqdn, ())
        if kind is None:
            return edges
        return tuple(e for e in edges if e.kind == kind)

    def nodes_by_kind(self, kind: NodeKind) -> tuple[Node, ...]:
        """Get all nodes of a specific kind, in deterministic FQDN order."""
        return tuple(
            node for fqdn, node in sorted(self.nodes.items())
            if node.kind == kind
        )

    def edges_by_kind(self, kind: EdgeKind) -> tuple[Edge, ...]:
        """Get all edges of a specific kind, preserving order."""
        return tuple(e for e in self.edges if e.kind == kind)


class GraphBuilder:
    """
    Builder for constructing new Graph instances.

    Since Graph is immutable, this builder accumulates changes
    and produces a new frozen graph on build(). Used by compilation
    stages to transform one Graph into the next.

    Usage:
        builder = GraphBuilder.from_graph(existing_graph)
        builder.add_node(node)
        builder.add_edge(edge)
        new_graph = builder.build()
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._address_table: dict[str, int] = {}
        self._reverse_table: dict[int, str] = {}
        self._topology_hash: str = ""
        self._address_hash: str = ""

    @classmethod
    def from_graph(cls, graph: Graph) -> "GraphBuilder":
        """Create a builder pre-populated from an existing graph."""
        builder = cls()
        builder._nodes = dict(graph.nodes)
        builder._edges = list(graph.edges)
        builder._address_table = dict(graph.address_table)
        builder._reverse_table = dict(graph.reverse_table)
        builder._topology_hash = graph.topology_hash
        builder._address_hash = graph.address_hash
        return builder

    def add_node(self, node: Node) -> None:
        """Add a node to the graph (replaces if FQDN exists)."""
        self._nodes[node.fqdn] = node

    def replace_node(self, fqdn: str, **kwargs: Any) -> None:
        """Replace fields on an existing node."""
        if fqdn not in self._nodes:
            raise KeyError(f"Node not found: {fqdn}")
        self._nodes[fqdn] = self._nodes[fqdn].replace(**kwargs)

    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the graph."""
        self._edges.append(edge)

    def drop_bare_duplicate_edges(self) -> int:
        """
        Drop metadata-empty edges shadowed by a metadata-rich duplicate.

        The same relationship can be declared twice in an artifact — once in
        its references/Dependencies header (typed to a bare edge) and once in
        frontmatter (e.g. a CC pipeline step, which carries step metadata).
        Both declarations are true; only one edge should survive: the one
        carrying metadata. Edges that differ in metadata content (e.g.
        NODE_NEXT outcome conditions) are distinct relationships and are
        never dropped.

        Returns the number of edges dropped.
        """
        rich_keys = {
            (e.source_fqdn, e.target_fqdn, e.kind)
            for e in self._edges
            if e.metadata
        }
        kept: list[Edge] = []
        dropped = 0
        for edge in self._edges:
            if not edge.metadata and (edge.source_fqdn, edge.target_fqdn, edge.kind) in rich_keys:
                dropped += 1
                continue
            kept.append(edge)
        self._edges = kept
        return dropped

    def set_address_table(self, table: dict[str, int]) -> None:
        """Set the complete address table (forward lookup)."""
        self._address_table = dict(table)
        self._reverse_table = {v: k for k, v in table.items()}

    def set_topology_hash(self, h: str) -> None:
        """Set the topology hash."""
        self._topology_hash = h

    def set_address_hash(self, h: str) -> None:
        """Set the address hash."""
        self._address_hash = h

    def build(self) -> Graph:
        """
        Build an immutable Graph from accumulated state.

        Computes adjacency indexes and freezes all collections.
        Edges are sorted deterministically (source_fqdn, target_fqdn, kind).

        Returns:
            New frozen Graph
        """
        # Sort edges deterministically
        sorted_edges = tuple(sorted(
            self._edges,
            key=lambda e: (e.source_fqdn, e.target_fqdn, e.kind.value)
        ))

        # Build adjacency indexes
        outgoing: dict[str, list[Edge]] = {}
        incoming: dict[str, list[Edge]] = {}

        for edge in sorted_edges:
            outgoing.setdefault(edge.source_fqdn, []).append(edge)
            incoming.setdefault(edge.target_fqdn, []).append(edge)

        # Freeze adjacency
        frozen_outgoing = MappingProxyType({
            k: tuple(v) for k, v in outgoing.items()
        })
        frozen_incoming = MappingProxyType({
            k: tuple(v) for k, v in incoming.items()
        })

        return Graph(
            nodes=MappingProxyType(self._nodes),
            edges=sorted_edges,
            address_table=MappingProxyType(self._address_table),
            reverse_table=MappingProxyType(self._reverse_table),
            outgoing=frozen_outgoing,
            incoming=frozen_incoming,
            topology_hash=self._topology_hash,
            address_hash=self._address_hash,
        )
