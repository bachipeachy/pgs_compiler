"""
Traversal — pure graph operations over the federated semantic graph.

The graph is the union of every scope's evidence.json (artifact-level
nodes + typed edges), deduplicated. Operations are structural only —
upstream/downstream walks, transitive closure, path search. No domain
knowledge lives here (the compiler analog of Runtime Dumbness).

Edge direction convention (as materialized by the compiler):
    source --kind--> target  means "source depends on / contains / routes
    to target". Consumers of X are therefore sources of edges into X.
"""

import json
from dataclasses import dataclass
from typing import Any

from pgs_compiler.inspection.loader import Workspace


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    metadata_json: str  # canonical JSON — keeps Edge hashable for dedup

    @property
    def metadata(self) -> dict[str, Any]:
        return json.loads(self.metadata_json)


class SemanticGraph:
    """Federated, immutable artifact graph over all structure scopes."""

    def __init__(self, workspace: Workspace):
        nodes: dict[str, str] = {}
        edges: set[Edge] = set()

        for scope in workspace.scopes:
            evidence = workspace.evidence(scope)
            for node in evidence["nodes"]:
                nodes.setdefault(node["fqdn"], node["kind"])
            for edge in evidence["edges"]:
                edges.add(Edge(
                    source=edge["source_fqdn"],
                    target=edge["target_fqdn"],
                    kind=edge["kind"],
                    metadata_json=json.dumps(edge.get("metadata", {}), sort_keys=True),
                ))

        self.nodes = nodes
        self.edges = sorted(edges, key=lambda e: (e.source, e.target, e.kind, e.metadata_json))

        self._out: dict[str, list[Edge]] = {}
        self._in: dict[str, list[Edge]] = {}
        for edge in self.edges:
            self._out.setdefault(edge.source, []).append(edge)
            self._in.setdefault(edge.target, []).append(edge)

    # ── direct neighborhood ──────────────────────────────────────

    def out_edges(self, fqdn: str) -> list[Edge]:
        return self._out.get(fqdn, [])

    def in_edges(self, fqdn: str) -> list[Edge]:
        return self._in.get(fqdn, [])

    def node_kind(self, fqdn: str) -> str:
        return self.nodes.get(fqdn, "UNKNOWN")

    # ── walks ────────────────────────────────────────────────────

    def refs(self, fqdn: str, transitive: bool = False) -> list[dict[str, Any]]:
        """Who references this artifact (incoming edges; consumers)."""
        return self._walk(fqdn, self._in, "source", transitive)

    def deps(self, fqdn: str, transitive: bool = False) -> list[dict[str, Any]]:
        """What this artifact depends on (outgoing edges)."""
        return self._walk(fqdn, self._out, "target", transitive)

    def _walk(
        self,
        start: str,
        adjacency: dict[str, list[Edge]],
        neighbor_attr: str,
        transitive: bool,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        visited: set[str] = {start}
        frontier = [start]
        depth = 0
        while frontier:
            depth += 1
            next_frontier: list[str] = []
            for fqdn in frontier:
                for edge in adjacency.get(fqdn, []):
                    neighbor = getattr(edge, neighbor_attr)
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)
                    results.append({
                        "fqdn": neighbor,
                        "kind": self.node_kind(neighbor),
                        "edge_kind": edge.kind,
                        "depth": depth,
                    })
                    next_frontier.append(neighbor)
            if not transitive:
                break
            frontier = next_frontier
        results.sort(key=lambda r: (r["depth"], r["fqdn"]))
        return results

    def impact(self, fqdn: str) -> dict[str, dict[str, list[str]]]:
        """Transitive consumer closure, grouped by kind then domain."""
        closure = self.refs(fqdn, transitive=True)
        grouped: dict[str, dict[str, list[str]]] = {}
        for record in closure:
            domain = record["fqdn"].split("::", 1)[0]
            grouped.setdefault(record["kind"], {}).setdefault(domain, []).append(record["fqdn"])
        for kind in grouped:
            for domain in grouped[kind]:
                grouped[kind][domain] = sorted(set(grouped[kind][domain]))
        return {k: dict(sorted(v.items())) for k, v in sorted(grouped.items())}

    def lineage(self, fqdn: str, max_depth: int = 24) -> dict[str, Any]:
        """Ancestors (dependencies) and descendants (consumers) as trees."""
        return {
            "ancestors": self._tree(fqdn, self._out, "target", set(), max_depth),
            "descendants": self._tree(fqdn, self._in, "source", set(), max_depth),
        }

    def _tree(
        self,
        fqdn: str,
        adjacency: dict[str, list[Edge]],
        neighbor_attr: str,
        on_path: set[str],
        remaining: int,
    ) -> dict[str, Any]:
        node: dict[str, Any] = {"fqdn": fqdn, "kind": self.node_kind(fqdn), "children": []}
        if remaining == 0:
            return node
        on_path = on_path | {fqdn}
        seen: set[tuple[str, str]] = set()
        for edge in adjacency.get(fqdn, []):
            neighbor = getattr(edge, neighbor_attr)
            if (neighbor, edge.kind) in seen:  # same logical edge, richer metadata
                continue
            seen.add((neighbor, edge.kind))
            if neighbor in on_path:  # cycle guard
                node["children"].append({
                    "fqdn": neighbor, "kind": self.node_kind(neighbor),
                    "edge_kind": edge.kind, "cycle": True, "children": [],
                })
                continue
            child = self._tree(neighbor, adjacency, neighbor_attr, on_path, remaining - 1)
            child["edge_kind"] = edge.kind
            node["children"].append(child)
        return node

    def paths(self, source: str, target: str, limit: int = 10) -> list[list[str]]:
        """All shortest paths source → target along edge direction (≤ limit)."""
        if source == target:
            return [[source]]
        # BFS recording predecessor sets at the shortest depth
        depth = {source: 0}
        predecessors: dict[str, list[str]] = {}
        frontier = [source]
        found_depth: int | None = None
        while frontier and found_depth is None:
            next_frontier: list[str] = []
            for fqdn in frontier:
                for edge in self._out.get(fqdn, []):
                    neighbor = edge.target
                    if neighbor not in depth:
                        depth[neighbor] = depth[fqdn] + 1
                        predecessors[neighbor] = [fqdn]
                        next_frontier.append(neighbor)
                    elif depth[neighbor] == depth[fqdn] + 1:
                        predecessors[neighbor].append(fqdn)
                    if neighbor == target:
                        found_depth = depth[neighbor]
            frontier = next_frontier
        if target not in depth:
            return []

        paths: list[list[str]] = []

        def unwind(fqdn: str, suffix: list[str]) -> None:
            if len(paths) >= limit:
                return
            if fqdn == source:
                paths.append([source] + suffix)
                return
            for pred in sorted(set(predecessors.get(fqdn, []))):
                unwind(pred, [fqdn] + suffix)

        unwind(target, [])
        return paths

    # ── workflow-shaped queries ──────────────────────────────────

    def wf_subgraph(self, wf_fqdn: str) -> dict[str, Any]:
        """Reachability graph of one workflow: members, start, routing."""
        members = sorted({
            e.target for e in self.out_edges(wf_fqdn) if e.kind == "WF_CONTAINS_NODE"
        })
        start = {e.target for e in self.out_edges(wf_fqdn) if e.kind == "WF_START"}
        bindings = {e.target for e in self.out_edges(wf_fqdn) if e.kind == "WF_BINDS_RB"}
        routing = [
            {"from": f, "condition": c, "to": t}
            for f, c, t in sorted({
                (e.source, e.metadata.get("condition", ""), e.target)
                for e in self.edges
                if e.kind == "NODE_NEXT" and e.metadata.get("wf_fqdn") == wf_fqdn
            })
        ]
        return {
            "workflow": wf_fqdn,
            "start": sorted(start),
            "members": members,
            "runtime_bindings": sorted(bindings),
            "routing": routing,
        }

    def cc_positions(self, cc_fqdn: str) -> dict[str, Any]:
        """Every WF position this artifact occupies, with routing context."""
        workflows = sorted(
            e.source for e in self.in_edges(cc_fqdn) if e.kind == "WF_CONTAINS_NODE"
        )
        positions: dict[str, Any] = {}
        for wf in workflows:
            incoming = sorted(
                {
                    (e.source, e.metadata.get("condition", ""))
                    for e in self.in_edges(cc_fqdn)
                    if e.kind == "NODE_NEXT" and e.metadata.get("wf_fqdn") == wf
                }
            )
            outgoing = sorted(
                {
                    (e.metadata.get("condition", ""), e.target)
                    for e in self.out_edges(cc_fqdn)
                    if e.kind == "NODE_NEXT" and e.metadata.get("wf_fqdn") == wf
                }
            )
            positions[wf] = {
                "incoming": [{"from": s, "condition": c} for s, c in incoming],
                "outgoing": [{"condition": c, "to": t} for c, t in outgoing],
            }
        return positions

    # ── graph-wide metrics ───────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for kind in self.nodes.values():
            by_kind[kind] = by_kind.get(kind, 0) + 1
        edge_kinds: dict[str, int] = {}
        for edge in self.edges:
            edge_kinds[edge.kind] = edge_kinds.get(edge.kind, 0) + 1
        orphans = sorted(
            fqdn for fqdn in self.nodes
            if fqdn not in self._out and fqdn not in self._in
        )
        orphans_by_kind: dict[str, list[str]] = {}
        for fqdn in orphans:
            orphans_by_kind.setdefault(self.node_kind(fqdn), []).append(fqdn)
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes_by_kind": dict(sorted(by_kind.items())),
            "edges_by_kind": dict(sorted(edge_kinds.items())),
            "orphans": orphans,
            "orphans_by_kind": dict(sorted(orphans_by_kind.items())),
        }
