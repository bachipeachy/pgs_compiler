"""
Base utilities for protocol validators.

Shared infrastructure:
- ValidationError: Base exception with path tracking
- load_json_file: Safe JSON file loading with error handling
- run_cli: Standard CLI runner pattern
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, List


class ValidationError(Exception):
    """Base exception for all protocol validation errors."""

    def __init__(self, message: str, path: List[str] | None = None):
        self.path = path or []
        self.path_str = " -> ".join(self.path) if self.path else ""
        if self.path_str:
            super().__init__(f"[{self.path_str}] {message}")
        else:
            super().__init__(message)


def load_json_file(file_path: Path) -> dict[str, Any]:
    """
    Load and parse a JSON file.

    Raises:
        ValidationError: If file not found or invalid JSON.
    """
    if not file_path.is_file():
        raise ValidationError(f"File not found: {file_path}")

    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValidationError(f"Expected JSON object, got {type(data).__name__}")

    return data


def run_cli(
    description: str,
    validate_fn: Callable[[Path], tuple[bool, str]],
    file_path: Path,
) -> None:
    """
    Standard CLI runner for validators.

    Args:
        description: What is being validated (e.g., "schema", "payload", "graph")
        validate_fn: Function that takes file path and returns (success, message)
        file_path: Path to the file to validate
    """
    print(f"Validating {description}: {file_path.name}")

    try:
        success, message = validate_fn(file_path)
        print(message)
        sys.exit(0 if success else 1)

    except ValidationError as e:
        print(f"Validation error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)
