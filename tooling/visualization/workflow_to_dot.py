"""
Convert workflow DAG to Graphviz DOT format.

Governed by: CONSTITUTION_EXECUTION_V0
"""

from typing import List, Dict, Any, Set, Tuple
from omnibachi.implementation.execution.machine.dag_model import DAG


def workflow_to_dot(dag: DAG, trace_events: List[Dict[str, Any]] = None) -> str:
    """
    Generate DOT representation of workflow DAG.

    Args:
        dag: The workflow DAG
        trace_events: Optional trace events to highlight execution path (red)

    Returns:
        DOT format string
    """
    visited_nodes: Set[str] = set()
    traversed_edges: Set[Tuple[str, str, str]] = set()

    if trace_events:
        # Track execution path from trace events
        last_node_id = None
        last_status = None

        for event in trace_events:
            # Handle both old format (event) and new format (event_type)
            evt_type = event.get("event_type") or event.get("event")

            # Handle nested payload format
            payload = event.get("payload", event)
            node_id = payload.get("node_id", "")

            if evt_type == "node_start":
                visited_nodes.add(node_id)
                # Track edge from previous node
                if last_node_id and last_status:
                    traversed_edges.add((last_node_id, node_id, last_status))
                last_node_id = None
                last_status = None

            elif evt_type == "node_end":
                last_node_id = node_id
                last_status = payload.get("status", "")

    lines = [
        f'digraph "{dag.dag_id}" {{',
        '  rankdir=LR;',
        '  node [fontname="Helvetica"];',
        '  edge [fontname="Helvetica", fontsize=10];',
    ]

    for node in dag.nodes.values():
        label = f"{node.node_id}\\n[{node.node_type}]"
        if node.capability_code and node.capability_code != node.node_id:
            label += f"\\n{node.capability_code}"

        shape = "box"
        if node.node_id in dag.terminal_nodes:
            shape = "doublecircle"
        elif node.node_type == "intent":
            shape = "hexagon"

        style, color, fillcolor = "", "black", "white"
        if node.node_id in visited_nodes:
            style, color, fillcolor = "filled", "red", "#ffcccc"

        lines.append(
            f'  "{node.node_id}" [label="{label}", shape={shape}, '
            f'style="{style}", color="{color}", fillcolor="{fillcolor}"];'
        )

    for edge in dag.edges:
        condition = edge.condition or ""
        is_traversed = (edge.from_node, edge.to_node, condition) in traversed_edges
        color = "red" if is_traversed else "black"
        penwidth = 3 if is_traversed else 1

        lines.append(
            f'  "{edge.from_node}" -> "{edge.to_node}" '
            f'[label="{condition}", color="{color}", penwidth={penwidth}];'
        )

    lines.append("}")
    return "\n".join(lines)
