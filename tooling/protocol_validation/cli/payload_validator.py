"""
Payload Validator - Validates payload completeness against workflow IN node requirements.

Usage:
    python -m pgs_tooling.protocol_validation.cli.payload_validator <workflow.json> <payload.json>
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from pgs_compiler.tooling.protocol_validation.core.base import ValidationError, load_json_file


def get_required_payload_keys(workflow: dict[str, Any]) -> set[str]:
    """
    Extract required payload keys from workflow's IN node.

    Contract:
    - Entry node must be of type 'IN' to require a payload.
    - The 'payload_schema' field must be a list of required key names.
    """
    core = workflow.get("core", {})
    start_node_code = core.get("start_node")
    if not start_node_code:
        raise ValidationError("Workflow missing 'start_node'")

    start_node_spec = core.get("nodes", {}).get(start_node_code)
    if not start_node_spec:
        raise ValidationError(f"Start node '{start_node_code}' not defined in 'nodes'")

    if start_node_spec.get("type") != "IN":
        return set()

    required_keys = start_node_spec.get("payload_schema", [])
    if not isinstance(required_keys, list):
        raise ValidationError(f"'payload_schema' for '{start_node_code}' must be a list")

    return set(required_keys)


def validate_payload(
    workflow: dict[str, Any], payload: dict[str, Any]
) -> tuple[set[str], set[str]]:
    """
    Validate payload against workflow requirements.

    Returns:
        Tuple of (missing_keys, extra_keys).
    """
    required_keys = get_required_payload_keys(workflow)
    actual_keys = set(payload.keys())
    return required_keys - actual_keys, actual_keys - required_keys


def main() -> None:
    parser = argparse.ArgumentParser(description="Protocol Payload Validator")
    parser.add_argument("workflow_file", type=Path, help="Path to workflow.json")
    parser.add_argument("payload_file", type=Path, help="Path to payload.json")
    args = parser.parse_args()

    print(f"Validating payload: {args.payload_file.name} against {args.workflow_file.name}")

    try:
        workflow = load_json_file(args.workflow_file)
        payload = load_json_file(args.payload_file)
        missing, extra = validate_payload(workflow, payload)

        if missing:
            print(f"\nMissing required keys: {sorted(missing)}")
        if extra:
            print(f"\nExtra keys (warning): {sorted(extra)}")

        if missing:
            print("\nPayload validation failed.")
            sys.exit(1)
        else:
            print("\nPayload validation successful.")
            sys.exit(0)

    except ValidationError as e:
        print(f"Validation error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
