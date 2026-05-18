from pgs_compiler.tooling.artifact_validation.wf_graph_rules import (
    rule_single_entry,
    rule_reachability,
    rule_exit_reachability,
)


def validate_graph(graph) -> None:
    rule_single_entry(graph)
    rule_reachability(graph)
    rule_exit_reachability(graph)
