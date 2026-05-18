from pgs_compiler.tooling.artifact_validation.wf_graph_structure import GraphStructure, EXIT
from pgs_compiler.tooling.artifact_validation.errors import (
    MissingEntryNode,
    UnreachableNode,
    MissingExitPath,
)


def rule_single_entry(graph: GraphStructure) -> None:
    if not graph.entry_node:
        raise MissingEntryNode("Workflow has no entry node")


def rule_reachability(graph: GraphStructure) -> None:
    visited = set()

    def dfs(node_code: str):
        if node_code in visited:
            return
        visited.add(node_code)
        node = graph.get_node(node_code)
        if not node:
            return
        for edge in node.outgoing.values():
            if edge.to_node != EXIT:
                dfs(edge.to_node)

    dfs(graph.entry_node)

    for code in graph.nodes:
        if code not in visited:
            raise UnreachableNode(f"Unreachable node: {code}")


def rule_exit_reachability(graph: GraphStructure) -> None:
    if not graph.exit_edges():
        raise MissingExitPath("Workflow has no EXIT path")
