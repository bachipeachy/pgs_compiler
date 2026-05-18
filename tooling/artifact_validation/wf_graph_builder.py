from pgs_compiler.tooling.artifact_validation.wf_graph_structure import GraphStructure, Node, NodeKind, Edge, EXIT


def build_graph_structure(workflow: dict) -> GraphStructure:
    """
    Build GraphStructure from a protocol_validator-authored workflow artifact.

    Constitutional behavior:
    - Reads graph exclusively from workflow["core"]
    - Treats EXIT as a semantic sink
    - Ignores EXIT as a node
    - Performs NO validation
    """

    core = workflow.get("core", {})
    core_nodes = core.get("nodes", {})
    entry_node = core.get("start_node")

    nodes: Dict[str, Node] = {}
    edges: list[Edge] = []

    # --------------------------------------------------
    # Node creation (exclude EXIT)
    # --------------------------------------------------
    for code, spec in core_nodes.items():
        node_type = spec.get("type")

        # EXIT is a semantic sink, not a node
        if node_type == "EXIT" or code == "EXIT":
            continue

        if node_type == "IN":
            kind = NodeKind.IN
        else:
            # CC / OP / anything executable is treated as OP here
            kind = NodeKind.OP

        nodes[code] = Node(
            node_code=code,
            kind=kind,
        )

    # --------------------------------------------------
    # Edge creation
    # --------------------------------------------------
    for from_code, spec in core_nodes.items():
        if spec.get("type") == "EXIT":
            continue

        from_node = nodes.get(from_code)
        if not from_node:
            continue

        transitions = spec.get("next", {})
        for result_status, target in transitions.items():
            to_node = EXIT if target == "EXIT" else target

            edge = Edge(
                from_node=from_code,
                result_status=result_status,
                to_node=to_node,
            )

            edges.append(edge)
            from_node.outgoing[result_status] = edge

    return GraphStructure(
        nodes=nodes,
        entry_node=entry_node,
        edges=edges,
    )
