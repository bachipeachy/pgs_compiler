"""
errors.py — Consolidated Validation Errors

All validation errors for authoring-time protocol validation.
Fail-fast, no recovery, no ambiguity.
"""


# ---------------------------------------------------------------------
# WF-CC Link Validation Errors
# ---------------------------------------------------------------------

class WFCCLinkValidationError(Exception):
    """Base class for WF-CC link validation errors."""


class MissingCapabilityContract(WFCCLinkValidationError):
    pass


class UnknownResultStatus(WFCCLinkValidationError):
    pass


class UnhandledCapabilityOutcome(WFCCLinkValidationError):
    pass


# ---------------------------------------------------------------------
# Workflow Graph Validation Errors
# ---------------------------------------------------------------------

class WorkflowGraphError(RuntimeError):
    pass


class MissingEntryNode(WorkflowGraphError):
    pass


class MultipleEntryNodes(WorkflowGraphError):
    pass


class UnreachableNode(WorkflowGraphError):
    pass


class MissingExitPath(WorkflowGraphError):
    pass


class IllegalExitUsage(WorkflowGraphError):
    pass
