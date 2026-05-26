"""
Graph query interface.

Provides structured queries over the Graph for governance
predicates, ASSERT handlers, and stage logic. All queries are
read-only — they never modify the graph.
"""

from pgs_compiler.compiler.graph.types import NodeKind, EdgeKind
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.edge import Edge
from pgs_compiler.compiler.graph.graph import Graph


class Query:
    """
    Read-only query interface over a Graph.

    Used by:
    - S4 GOVERN: graph legality predicates
    - ASSERT handlers: governance checks via compilation_context
    - S5 CONSTRUCT: topology traversal for IR construction

    All methods are pure — they return results without modifying state.
    """

    def __init__(self, graph: Graph) -> None:
        self._graph = graph

    @property
    def graph(self) -> Graph:
        """Access the underlying graph (read-only)."""
        return self._graph

    def outgoing(
        self,
        fqdn: str,
        kind: EdgeKind | list[EdgeKind] | None = None,
    ) -> list[Edge]:
        """
        Get outgoing edges from a node, optionally filtered by kind(s).

        Args:
            fqdn: Source node FQDN
            kind: Single kind, list of kinds, or None for all

        Returns:
            List of matching outgoing edges
        """
        edges = self._graph.outgoing.get(fqdn, ())
        if kind is None:
            return list(edges)
        if isinstance(kind, list):
            kind_set = set(kind)
            return [e for e in edges if e.kind in kind_set]
        return [e for e in edges if e.kind == kind]

    def incoming(
        self,
        fqdn: str,
        kind: EdgeKind | list[EdgeKind] | None = None,
    ) -> list[Edge]:
        """
        Get incoming edges to a node, optionally filtered by kind(s).

        Args:
            fqdn: Target node FQDN
            kind: Single kind, list of kinds, or None for all

        Returns:
            List of matching incoming edges
        """
        edges = self._graph.incoming.get(fqdn, ())
        if kind is None:
            return list(edges)
        if isinstance(kind, list):
            kind_set = set(kind)
            return [e for e in edges if e.kind in kind_set]
        return [e for e in edges if e.kind == kind]

    def targets(
        self,
        fqdn: str,
        kind: EdgeKind | list[EdgeKind] | None = None,
    ) -> list[str]:
        """Get FQDNs of all nodes reachable via outgoing edges of given kind(s)."""
        return [e.target_fqdn for e in self.outgoing(fqdn, kind)]

    def sources(
        self,
        fqdn: str,
        kind: EdgeKind | list[EdgeKind] | None = None,
    ) -> list[str]:
        """Get FQDNs of all nodes that point to this node via given kind(s)."""
        return [e.source_fqdn for e in self.incoming(fqdn, kind)]

    def reachable(
        self,
        from_fqdn: str,
        edge_kinds: list[EdgeKind],
    ) -> set[str]:
        """
        Compute all FQDNs reachable from a node via edges of given kinds.

        Performs breadth-first traversal. Includes the starting node.

        Args:
            from_fqdn: Starting node FQDN
            edge_kinds: Edge kinds to follow

        Returns:
            Set of reachable node FQDNs (includes from_fqdn)
        """
        visited: set[str] = set()
        queue: list[str] = [from_fqdn]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for target in self.targets(current, edge_kinds):
                if target not in visited:
                    queue.append(target)

        return visited

    def has_cycle(self, edge_kinds: list[EdgeKind]) -> bool:
        """
        Detect cycles in the subgraph defined by given edge kinds.

        Uses DFS with coloring (WHITE/GRAY/BLACK).

        Args:
            edge_kinds: Edge kinds to consider

        Returns:
            True if a cycle exists
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {fqdn: WHITE for fqdn in self._graph.nodes}

        def dfs(fqdn: str) -> bool:
            color[fqdn] = GRAY
            for target in self.targets(fqdn, edge_kinds):
                if target not in color:
                    continue
                if color[target] == GRAY:
                    return True  # Back edge = cycle
                if color[target] == WHITE and dfs(target):
                    return True
            color[fqdn] = BLACK
            return False

        for fqdn in self._graph.nodes:
            if color[fqdn] == WHITE:
                if dfs(fqdn):
                    return True
        return False

    def topological_order(self, edge_kinds: list[EdgeKind]) -> list[str]:
        """
        Compute topological ordering of nodes connected by given edge kinds.

        Only includes nodes that participate in edges of the given kinds.
        Raises ValueError if a cycle is detected.

        Args:
            edge_kinds: Edge kinds to consider

        Returns:
            List of FQDNs in topological order

        Raises:
            ValueError: If the subgraph contains a cycle
        """
        # Collect participating nodes
        participating: set[str] = set()
        in_degree: dict[str, int] = {}

        for edge in self._graph.edges:
            if edge.kind in edge_kinds:
                participating.add(edge.source_fqdn)
                participating.add(edge.target_fqdn)
                in_degree.setdefault(edge.source_fqdn, 0)
                in_degree[edge.target_fqdn] = in_degree.get(edge.target_fqdn, 0) + 1

        # Kahn's algorithm
        queue = sorted(fqdn for fqdn in participating if in_degree.get(fqdn, 0) == 0)
        result: list[str] = []

        while queue:
            current = queue.pop(0)
            result.append(current)
            for target in sorted(self.targets(current, edge_kinds)):
                if target in in_degree:
                    in_degree[target] -= 1
                    if in_degree[target] == 0:
                        queue.append(target)

        if len(result) != len(participating):
            raise ValueError(
                f"Cycle detected in subgraph with edge kinds "
                f"{[k.value for k in edge_kinds]}"
            )

        return result

    def nodes_by_kind(self, kind: NodeKind) -> list[Node]:
        """Get all nodes of a specific kind, in deterministic FQDN order."""
        return list(self._graph.nodes_by_kind(kind))

    def by_address(self, address: int) -> str | None:
        """Look up identity by address (reverse lookup)."""
        return self._graph.reverse_table.get(address)
