"""
Graph Validator - Validates workflow DAG structure.

Usage:
    python -m pgs_tooling.protocol_validation.cli.graph_validator <workflow.json>
"""

import argparse
import sys
from pathlib import Path

from pgs_governance.structure.structure.resolution import bootstrap

bootstrap()

# If invoked from a different directory (e.g., pgs_sandbox), preserve it as workspace_root

from pgs_compiler.tooling.artifact_validation import build_graph_structure, validate_graph as wgv_validate
from pgs_compiler.tooling.protocol_validation.core.base import ValidationError, load_json_file


def validate_graph(workflow_path: Path) -> tuple[bool, str]:
    """
    Validate workflow graph structure.

    Returns:
        Tuple of (success, message).
    """
    workflow = load_json_file(workflow_path)
    graph = build_graph_structure(workflow)
    wgv_validate(graph)
    return True, "Graph validation successful."


def main() -> None:
    parser = argparse.ArgumentParser(description="Protocol Graph Validator")
    parser.add_argument("workflow_file", type=Path, help="Path to workflow.json")
    args = parser.parse_args()

    print(f"Validating graph: {args.workflow_file.name}")

    try:
        success, message = validate_graph(args.workflow_file)
        print(f"\n{message}")
        sys.exit(0)

    except ValidationError as e:
        print(f"Validation error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Graph validation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    bootstrap()
    main()
