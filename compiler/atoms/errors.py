"""
Structured error model for the PGS compiler.

Design:
- Machine-readable + human-friendly
- Phase-tagged (S1–S8)
- Context-rich (FQDN, artifact_code, source_path)
- Actionable messages via ERROR_SUGGESTIONS
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pgs_compiler.compiler.atoms.error_codes import ErrorCode, ERROR_SUGGESTIONS


class Severity(Enum):
    """Error severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class CompilerError(Exception):
    """
    Structured error for compiler failures.

    Fields:
        code: Error code (e.g., E201_MISSING_REFERENCE)
        message: Human-readable description
        phase: Stage where error occurred (e.g., S1_EXTRACT)
        fqdn_id: Fully qualified domain name (primary identity)
        artifact_code: Short code for display/logging (not unique)
        source_path: Path to source file if applicable
        context: Additional debug information
        severity: Error severity level
    """

    code: ErrorCode
    message: str
    phase: str
    fqdn_id: str | None = None
    artifact_code: str | None = None
    source_path: Path | None = None
    context: dict[str, Any] = field(default_factory=dict)
    severity: Severity = Severity.ERROR

    def __str__(self) -> str:
        """String representation delegates to format()."""
        return self.format(verbose=False)

    def format(self, verbose: bool = False) -> str:
        """
        Format error for terminal output.

        Args:
            verbose: Include full context and suggestions

        Returns:
            Formatted error string
        """
        # Color codes (basic ANSI)
        color = {
            Severity.ERROR: "\033[91m",  # Red
            Severity.WARNING: "\033[93m",  # Yellow
            Severity.INFO: "\033[94m",  # Blue
        }
        reset = "\033[0m"

        severity_color = color.get(self.severity, "")
        severity_str = self.severity.value.upper()

        # Basic format: [ERROR] E201: Message
        basic = f"{severity_color}[{severity_str}]{reset} {self.code.value}: {self.message}"

        if not verbose:
            return basic

        # Verbose format includes location, context
        parts = [basic]

        if self.source_path:
            parts.append(f"  File: {self.source_path}")

        if self.fqdn_id:
            parts.append(f"  FQDN: {self.fqdn_id}")

        if self.artifact_code:
            parts.append(f"  Code: {self.artifact_code}")

        if self.phase:
            parts.append(f"  Phase: {self.phase}")

        if self.context:
            parts.append("  Context:")
            for key, value in self.context.items():
                parts.append(f"    {key}: {value}")

        # Add suggestion if available
        suggestion = self._get_suggestion()
        if suggestion:
            parts.append(f"  💡 Suggestion: {suggestion}")

        return "\n".join(parts)

    def _get_suggestion(self) -> str | None:
        """Get actionable suggestion for fixing this error."""
        return ERROR_SUGGESTIONS.get(self.code)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "code": self.code.value,
            "message": self.message,
            "phase": self.phase,
            "fqdn_id": self.fqdn_id,
            "artifact_code": self.artifact_code,
            "source_path": str(self.source_path) if self.source_path else None,
            "context": self.context,
            "severity": self.severity.value,
        }
