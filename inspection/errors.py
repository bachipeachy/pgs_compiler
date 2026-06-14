"""
Inspection error hierarchy — fail-hard, explicit cause, non-zero exit.

Every error names what is missing or ambiguous. No fallback, no guess.
"""


class InspectionError(Exception):
    """Base class for all inspection failures. Maps to non-zero exit."""

    exit_code = 1


class WorkspaceNotDeclared(InspectionError):
    """No workspace root declared via --workspace or PGS_WORKSPACE."""


class SnapshotInvalid(InspectionError):
    """snapshot_status.json missing or not VALID — refuse to answer."""


class ProjectionMissing(InspectionError):
    """A required materialized projection is absent or malformed."""


class UnresolvedFqdn(InspectionError):
    """FQDN not present in the artifact index."""


class AmbiguousCode(InspectionError):
    """Bare artifact code given where a full FQDN is required."""

    def __init__(self, code: str, candidates: list[str]):
        self.code = code
        self.candidates = candidates
        lines = "\n".join(f"  {c}" for c in candidates)
        super().__init__(
            f"bare code '{code}' is not a full FQDN — declare the domain. "
            f"Candidates:\n{lines}"
        )
