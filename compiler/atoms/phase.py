"""
Phase result model for pipeline execution.

Design:
- Explicit status (SUCCESS/PARTIAL/FAILED)
- Typed outputs (phase-specific data)
- Error collection (all errors, not just first)
- Metrics (timing, counts for reporting)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pgs_compiler.compiler.atoms.errors import CompilerError


class PhaseStatus(Enum):
    """Phase execution status."""

    SUCCESS = "SUCCESS"  # No errors, all items processed
    PARTIAL = "PARTIAL"  # Some errors, some items processed
    FAILED = "FAILED"  # Critical error, phase could not complete


@dataclass
class PhaseMetrics:
    """
    Metrics for phase execution.

    Used for reporting and performance analysis.
    """

    duration_ms: int = 0
    items_processed: int = 0
    items_failed: int = 0
    items_skipped: int = 0

    def __post_init__(self) -> None:
        """Calculate total."""
        self.total = self.items_processed + self.items_failed + self.items_skipped


@dataclass(frozen=True)
class PhaseResult:
    """
    Result from phase execution.

    All phases return this type for consistency.

    IMMUTABILITY GUARANTEE:
    - frozen=True prevents mutation after creation
    - No phase side-effects
    - No hidden mutation across pipeline
    - Build once with all errors, don't mutate

    Fields:
        status: Execution status
        outputs: Phase-specific output data (artifacts, metadata, etc.)
        errors: Tuple of errors encountered (immutable)
        metrics: Performance metrics

    Examples:
        >>> result = PhaseResult(
        ...     status=PhaseStatus.SUCCESS,
        ...     outputs={"artifacts": [...]},
        ...     errors=(),
        ...     metrics=PhaseMetrics(duration_ms=50, items_processed=10)
        ... )
    """

    status: PhaseStatus
    outputs: dict[str, Any]
    errors: tuple[CompilerError, ...] = field(default_factory=tuple)
    metrics: PhaseMetrics = field(default_factory=PhaseMetrics)

    @property
    def success(self) -> bool:
        """Check if phase succeeded (no errors)."""
        return self.status == PhaseStatus.SUCCESS and len(self.errors) == 0

    @property
    def failed(self) -> bool:
        """Check if phase failed (critical error or all items failed)."""
        return self.status == PhaseStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "status": self.status.value,
            "outputs": self.outputs,
            "errors": [e.to_dict() for e in self.errors],
            "metrics": {
                "duration_ms": self.metrics.duration_ms,
                "items_processed": self.metrics.items_processed,
                "items_failed": self.metrics.items_failed,
                "items_skipped": self.metrics.items_skipped,
            },
        }
