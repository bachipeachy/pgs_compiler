"""
pgs_compiler.inspection — Protocol Inspection library (the pi core).

One verified model, three surfaces: this library is the core; the pi
CLI/shell and the --json output are its projections. All surfaces are
read-only, fail-hard, zero-inference, query-only (V0 Principle):

    pi answers questions. The compiler performs changes.
    The runtime performs execution.

Library usage (in-ecosystem tooling):

    from pgs_compiler.inspection import open_workspace, Resolver, SemanticGraph

    ws = open_workspace("/abs/path/to/pgs_workspace")
    fqdn, entry = Resolver(ws).resolve("blockchain::CC_GENERATE_TX_ID_V0")
    consumers = SemanticGraph(ws).refs(fqdn, transitive=True)
"""

from pgs_compiler.inspection.errors import (
    AmbiguousCode,
    InspectionError,
    ProjectionMissing,
    SnapshotInvalid,
    UnresolvedFqdn,
    WorkspaceNotDeclared,
)
from pgs_compiler.inspection.loader import Workspace
from pgs_compiler.inspection.resolver import Resolver
from pgs_compiler.inspection.traversal import Edge, SemanticGraph


def open_workspace(workspace: str | None = None) -> Workspace:
    """Open a workspace (explicit path or PGS_WORKSPACE); gates on validity."""
    return Workspace.open(workspace)


__all__ = [
    "AmbiguousCode",
    "Edge",
    "InspectionError",
    "ProjectionMissing",
    "Resolver",
    "SemanticGraph",
    "SnapshotInvalid",
    "UnresolvedFqdn",
    "Workspace",
    "WorkspaceNotDeclared",
    "open_workspace",
]
