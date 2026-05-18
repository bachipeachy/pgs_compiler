"""
Schema Validator - Validates protocol artifacts against schema definitions.

Usage:
    python -m pgs_tooling.protocol_validation.cli.schema_validator <artifact.json>
"""

import argparse
from pathlib import Path
from typing import Any

from pgs_compiler.tooling.protocol_validation.core.base import (
    ValidationError,
    load_json_file,
    run_cli,
)

# Schema definition for workflow artifacts
WORKFLOW_SCHEMA = {
    "required_keys": {"code", "description", "core"},
    "core": {
        "required_keys": {"nodes", "start_node"},
        "nodes": {
            "__dict__": {
                "required_keys": {"type", "next"},
                "next": {"__dict__": {}},
            }
        },
    },
}


def _validate_dict(data: dict, schema: dict, path: list[str]) -> None:
    """Recursively validate a dictionary against a schema."""
    if not isinstance(data, dict):
        raise ValidationError("Expected a dictionary", path)

    required_keys = schema.get("required_keys", set())
    missing_keys = required_keys - set(data.keys())
    if missing_keys:
        raise ValidationError(f"Missing required keys: {sorted(missing_keys)}", path)

    for key, value in data.items():
        if key in schema:
            _validate_dict(value, schema[key], path + [key])

    if "__dict__" in schema:
        value_schema = schema["__dict__"]
        for key, value in data.items():
            _validate_dict(value, value_schema, path + [key])


def validate_schema(artifact: dict[str, Any], schema: dict | None = None) -> None:
    """
    Validate an artifact against a schema.

    Args:
        artifact: The loaded JSON artifact data.
        schema: Schema definition (defaults to WORKFLOW_SCHEMA).

    Raises:
        ValidationError: If validation fails.
    """
    schema = schema or WORKFLOW_SCHEMA
    _validate_dict(artifact, schema, ["root"])


def validate_file(file_path: Path) -> tuple[bool, str]:
    """Validate a file and return (success, message)."""
    artifact = load_json_file(file_path)
    validate_schema(artifact)
    return True, "Schema validation successful."


def main() -> None:
    parser = argparse.ArgumentParser(description="Protocol Schema Validator")
    parser.add_argument("artifact_file", type=Path, help="Path to artifact file")
    args = parser.parse_args()

    run_cli("schema", validate_file, args.artifact_file)


if __name__ == "__main__":
    main()
