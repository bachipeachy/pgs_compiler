"""
Behavior Logic — projections of <WF>.graph.json.

All rendering reads the graph JSON (the behavior logic source of truth), never the
PNGs. Output forms: execution-tree model (terminal render), Mermaid, DOT.
Text generation only — pi writes nothing; the materialized PNG is opened
via `pi behavior_logic open`.
"""

from typing import Any


def execution_tree(graph: dict[str, Any]) -> dict[str, Any]:
    """
    Build the execution tree from a behavior logic graph (entry + routed edges).

    Tree nodes: {fqdn (node id), kind (node type), edge_kind (condition),
    children}, compatible with render.render_tree. EXIT targets appear as
    leaves; cycles are marked, not followed.
    """
    node_types = {n["id"]: n["type"] for n in graph["nodes"]}
    routing: dict[str, list[dict[str, str]]] = {}
    for edge in sorted(
        graph["edges"], key=lambda e: (e["from"], e["condition"], e["to"])
    ):
        routing.setdefault(edge["from"], []).append(edge)

    def build(node_id: str, on_path: frozenset) -> dict[str, Any]:
        node = {
            "fqdn": node_id,
            "kind": node_types.get(node_id, "EXIT"),
            "children": [],
        }
        for edge in routing.get(node_id, []):
            target = edge["to"]
            if target in on_path:
                node["children"].append({
                    "fqdn": target, "kind": node_types.get(target, "EXIT"),
                    "edge_kind": edge["condition"], "cycle": True, "children": [],
                })
                continue
            child = build(target, on_path | {target})
            child["edge_kind"] = edge["condition"]
            node["children"].append(child)
        return node

    entry = graph["entry"]
    return build(entry, frozenset({entry}))


def to_mermaid(graph: dict[str, Any]) -> str:
    """Mermaid flowchart text for a behavior logic graph. Deterministic ordering."""
    lines = ["flowchart TD"]
    for node in sorted(graph["nodes"], key=lambda n: n["id"]):
        lines.append(f'    {node["id"]}["{node["id"]}<br/>({node["type"]})"]')
    terminals = sorted({
        e["to"] for e in graph["edges"]
    } - {n["id"] for n in graph["nodes"]})
    for terminal in terminals:
        lines.append(f'    {terminal}(["{terminal}"])')
    for edge in sorted(
        graph["edges"], key=lambda e: (e["from"], e["condition"], e["to"])
    ):
        lines.append(f'    {edge["from"]} -->|{edge["condition"]}| {edge["to"]}')
    return "\n".join(lines)


def to_dot(graph: dict[str, Any]) -> str:
    """Graphviz DOT text for a behavior logic graph. Deterministic ordering."""
    lines = [f'digraph "{graph["wf_id"]}" {{', "    rankdir=TB;"]
    for node in sorted(graph["nodes"], key=lambda n: n["id"]):
        lines.append(
            f'    "{node["id"]}" [shape=box, label="{node["id"]}\\n({node["type"]})"];'
        )
    terminals = sorted({
        e["to"] for e in graph["edges"]
    } - {n["id"] for n in graph["nodes"]})
    for terminal in terminals:
        lines.append(f'    "{terminal}" [shape=oval];')
    for edge in sorted(
        graph["edges"], key=lambda e: (e["from"], e["condition"], e["to"])
    ):
        lines.append(
            f'    "{edge["from"]}" -> "{edge["to"]}" [label="{edge["condition"]}"];'
        )
    lines.append("}")
    return "\n".join(lines)
