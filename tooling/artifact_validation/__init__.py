"""
validator — Protocol Validation (Authoring Phase)

Public API:
- CapabilityContractValidator: Validates CC bindings
- validate_ct_composition: Validates CT-IR bytecode
- build_graph_structure: Builds workflow graph structure
- validate_graph: Validates workflow graph (WGV)
- run_wf_cc_link_validation: Validates WF-CC linkage

This module rejects invalid protocol. It does not help authors succeed.
"""

from pgs_compiler.tooling.artifact_validation.cc_validator import CapabilityContractValidator
from pgs_compiler.tooling.artifact_validation.ct_bytecode_validator import validate_ct_composition
from pgs_compiler.tooling.artifact_validation.wf_graph_builder import build_graph_structure
from pgs_compiler.tooling.artifact_validation.wf_graph_validator import validate_graph
from pgs_compiler.tooling.artifact_validation.wf_cc_link_validator import run_wf_cc_link_validation

from pgs_compiler.tooling.artifact_validation.wf_graph_structure import (
    GraphStructure,
    Node,
    NodeKind,
    Edge,
    EXIT,
)

from pgs_compiler.tooling.artifact_validation.errors import (
    WFCCLinkValidationError,
    MissingCapabilityContract,
    UnknownResultStatus,
    UnhandledCapabilityOutcome,
    WorkflowGraphError,
    MissingEntryNode,
    MultipleEntryNodes,
    UnreachableNode,
    MissingExitPath,
    IllegalExitUsage,
)


def run_wgv(workflows: dict) -> None:
    """Validate all workflow graphs."""
    for wf_code, workflow in workflows.items():
        graph = build_graph_structure(workflow)
        validate_graph(graph)


__all__ = [
    "CapabilityContractValidator",
    "validate_ct_composition",
    "build_graph_structure",
    "validate_graph",
    "run_wf_cc_link_validation",
    "run_wgv",
    "GraphStructure",
    "Node",
    "NodeKind",
    "Edge",
    "EXIT",
    "WFCCLinkValidationError",
    "MissingCapabilityContract",
    "UnknownResultStatus",
    "UnhandledCapabilityOutcome",
    "WorkflowGraphError",
    "MissingEntryNode",
    "MultipleEntryNodes",
    "UnreachableNode",
    "MissingExitPath",
    "IllegalExitUsage",
]
