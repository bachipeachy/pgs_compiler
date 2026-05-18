"""Convert process segments (multi-workflow) to Graphviz DOT format."""

from typing import Dict, Any


def segment_to_dot(
    segment_id: str,
    display_name: str,
    dags: Dict[str, Dict[str, Any]],
    color: str = "#4A90E2",
    layout: str = "horizontal",
) -> str:
    """
    Generate DOT for a multi-workflow segment.

    Args:
        segment_id: Segment identifier
        display_name: Human-readable segment name
        dags: Dict of {wf_code: {dag, workflow_spec, ...}}
        color: Hex color for workflow clustering
        layout: "horizontal" or "vertical"

    Returns:
        DOT format string
    """
    lines = [
        f'digraph "{segment_id}" {{',
        f'  label="{display_name}";',
        '  labelloc="t";',
        '  fontsize=16;',
        '  fontname="Helvetica Bold";',
        f'  rankdir={"TB" if layout == "vertical" else "LR"};',
        '  compound=true;',
        '  node [fontname="Helvetica"];',
        '  edge [fontname="Helvetica", fontsize=10];',
        '',
    ]

    emitted_events = {}
    consumed_events = {}

    for wf_code, wf_data in dags.items():
        dag = wf_data["dag"]
        workflow_spec = wf_data["workflow_spec"]

        lines.extend([
            f'  subgraph cluster_{wf_code} {{',
            f'    label="{wf_code}";',
            f'    style=filled;',
            f'    fillcolor="{color}20";',
            f'    color="{color}";',
            f'    penwidth=2;',
            '',
        ])

        for node in dag.nodes.values():
            # Use new DAGNode properties
            label = f"{node.node_id}\\n[{node.node_type.upper()}]"
            if node.capability_code:
                label += f"\\n{node.capability_code}"

            # Map node_type to shape
            shape = "box"
            if node.node_type == "exit":
                shape = "doublecircle"
            elif node.node_type == "intent":
                shape = "hexagon"
            elif node.node_id == dag.entry_nodes[0] if dag.entry_nodes else False:
                shape = "circle"

            node_id = f"{wf_code}_{node.node_id}"
            lines.append(f'    "{node_id}" [label="{label}", shape={shape}];')

        lines.extend(['  }', ''])

        # Use new DAGEdge properties
        for edge in dag.edges:
            from_id = f"{wf_code}_{edge.from_node}"
            to_id = f"{wf_code}_{edge.to_node}"
            condition = edge.condition or ""
            lines.append(f'  "{from_id}" -> "{to_id}" [label="{condition}"];')

        for event_code in workflow_spec.get("emit_events", []):
            emitted_events.setdefault(event_code, []).append(wf_code)

        for event_code in workflow_spec.get("consume_events", []):
            consumed_events.setdefault(event_code, []).append(wf_code)

    lines.append('')

    for event_code in set(emitted_events.keys()) | set(consumed_events.keys()):
        lines.append(
            f'  "{event_code}" [label="{event_code}", shape=diamond, '
            f'style=filled, fillcolor="#FFD700", color="#FF8C00", penwidth=2];'
        )

    lines.append('')

    for event_code, emitters in emitted_events.items():
        for wf_code in emitters:
            lines.append(
                f'  "{wf_code}_EXIT" -> "{event_code}" '
                f'[style=dashed, color="#FF8C00", label="emits"];'
            )

    for event_code, consumers in consumed_events.items():
        for wf_code in consumers:
            # Find entry node for this workflow
            dag = dags[wf_code]["dag"]
            entry_node = dag.entry_nodes[0] if dag.entry_nodes else "START"
            lines.append(
                f'  "{event_code}" -> "{wf_code}_{entry_node}" '
                f'[style=dashed, color="#32CD32", label="triggers"];'
            )

    lines.append('}')
    return '\n'.join(lines)
