"""
Atoms: Pure functions with no side effects.

Design:
- Single responsibility
- Explicit inputs/outputs
- No I/O, no state
- Independently testable
- Reusable across phases

Patches Applied:
- Patch A: FQDN immutability hardened
- Patch B: PhaseResult immutability (frozen=True)
- Patch C: Error codes centralized in error_codes.py
- Patch D: Invariant helpers (require, require_not_none, require_exists)
- Patch E: Deterministic ordering (sort_artifacts_by_fqdn, ensure_deterministic_output)
- Patch F: Transient pipeline field stripping (strip_transient_pipeline_fields)
"""

from pgs_compiler.compiler.atoms.error_codes import ErrorCode, ERROR_SUGGESTIONS
from pgs_compiler.compiler.atoms.errors import CompilerError, Severity
from pgs_compiler.compiler.atoms.fqdn import FQDN, parse_fqdn, build_fqdn, to_fqdn
from pgs_compiler.compiler.atoms.invariants import require, require_not_none, require_exists
from pgs_compiler.compiler.atoms.phase import PhaseResult, PhaseStatus, PhaseMetrics
from pgs_compiler.compiler.atoms.pipeline import strip_transient_pipeline_fields
from pgs_compiler.compiler.atoms.sorting import (
    ensure_deterministic_output,
    sort_artifacts_by_fqdn,
    sort_by_fqdn,
    sort_dict_keys,
)

__all__ = [
    # Error model
    "CompilerError",
    "ErrorCode",
    "ERROR_SUGGESTIONS",
    "Severity",
    # FQDN identity
    "FQDN",
    "parse_fqdn",
    "build_fqdn",
    "to_fqdn",
    # Phase results
    "PhaseResult",
    "PhaseStatus",
    "PhaseMetrics",
    # Invariant enforcement
    "require",
    "require_not_none",
    "require_exists",
    # Pipeline metadata
    "strip_transient_pipeline_fields",
    # Deterministic ordering
    "ensure_deterministic_output",
    "sort_artifacts_by_fqdn",
    "sort_by_fqdn",
    "sort_dict_keys",
]
