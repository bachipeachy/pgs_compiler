"""
generate_all_graphs.py — Post-Build Graph Generation

Generates workflow graph artifacts for all compiled workflows.

This script runs AFTER successful compilation and validation.
Graph generation failures do NOT fail the build - they are logged as warnings.

Usage:
    python -m pgs_compiler.compiler.visualization.generate_all_graphs \
        --artifacts-root /path/to/compiled/artifacts \
        --output-root /path/to/workflow_graphs

Governed by: Phase 8 - Workflow Graph Generation
"""

import argparse
import json
import sys
from pathlib import Path

from pgs_compiler.compiler.visualization.wf_graph_generator import generate_workflow_graph


def load_artifacts(artifacts_root: Path, artifact_type: str) -> dict:
    """
    Load all compiled artifacts of a given type.

    Args:
        artifacts_root: Root directory containing compiled artifacts
        artifact_type: Artifact type directory name (e.g., "workflows", "capability_contracts")

    Returns:
        Map of artifact code → artifact dict
    """
    artifacts = {}
    artifacts_dir = artifacts_root / artifact_type

    if not artifacts_dir.exists():
        print(f"  ⚠ No {artifact_type} directory found: {artifacts_dir}")
        return artifacts

    for json_file in artifacts_dir.glob("*.json"):
        try:
            with open(json_file) as f:
                artifact = json.load(f)

                # Try to extract code from frontmatter
                frontmatter = artifact.get("frontmatter", {})
                code = (frontmatter.get("wf_code") or
                       frontmatter.get("cc_code") or
                       artifact.get("artifact_code"))

                if code:
                    artifacts[code] = artifact
                else:
                    print(f"  ⚠ No artifact code found in {json_file.name}")
        except Exception as e:
            print(f"  ⚠ Failed to load {json_file.name}: {e}")

    return artifacts


def generate_all_workflow_graphs(artifacts_root: Path, output_root: Path) -> dict:
    """
    Generate graph artifacts for all compiled workflows.

    Args:
        artifacts_root: Root directory containing compiled artifacts
                       (e.g., .../compiled/artifacts/platform/)
        output_root: Root directory for graph output
                    (e.g., .../compiled/artifacts/workflow_graphs/)

    Returns:
        {
            "total": int,
            "successful": int,
            "partial": int,
            "failed": int,
            "results": list[dict]
        }
    """
    print("Loading compiled artifacts...")

    # Load WF artifacts
    wf_artifacts = load_artifacts(artifacts_root, "workflows")
    print(f"  Found {len(wf_artifacts)} workflow artifacts")

    # Load CC artifacts (for capability binding lookup)
    cc_artifacts = load_artifacts(artifacts_root, "capability_contracts")
    print(f"  Found {len(cc_artifacts)} capability contract artifacts")

    if not wf_artifacts:
        print("  No workflows to process")
        return {
            "total": 0,
            "successful": 0,
            "partial": 0,
            "failed": 0,
            "results": []
        }

    print(f"\nGenerating workflow graphs...")
    print(f"  Output: {output_root}")

    results = []
    stats = {"total": 0, "successful": 0, "partial": 0, "failed": 0}

    for wf_code, wf_artifact in wf_artifacts.items():
        stats["total"] += 1

        print(f"\n  [{stats['total']}/{len(wf_artifacts)}] {wf_code}")

        try:
            result = generate_workflow_graph(wf_artifact, cc_artifacts, output_root)
            results.append(result)

            status = result["status"]
            stats[status.lower()] += 1

            # Report result
            if status == "SUCCESS":
                print(f"    ✓ Generated: JSON, projection PNG")
            elif status == "PARTIAL":
                print(f"    ⚠ Partial: {', '.join(result.get('errors', []))}")
            else:  # FAILED
                print(f"    ✗ Failed: {', '.join(result.get('errors', []))}")

        except Exception as e:
            print(f"    ✗ Unexpected error: {e}")
            stats["failed"] += 1
            results.append({
                "wf_code": wf_code,
                "status": "FAILED",
                "errors": [str(e)]
            })

    return {
        **stats,
        "results": results
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate workflow graph artifacts"
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        required=True,
        help="Root directory containing compiled artifacts"
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Output directory for graph artifacts (default: artifacts-root/../workflow_graphs)"
    )

    args = parser.parse_args()

    # Default output to sibling of artifacts root
    if not args.output_root:
        args.output_root = args.artifacts_root.parent / "workflow_graphs"

    # Verify artifacts root exists
    if not args.artifacts_root.exists():
        print(f"✗ Artifacts root not found: {args.artifacts_root}")
        sys.exit(1)

    print("=" * 60)
    print("Workflow Graph Generation (Phase 8)")
    print("=" * 60)

    # Generate graphs
    summary = generate_all_workflow_graphs(args.artifacts_root, args.output_root)

    # Print summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Total workflows: {summary['total']}")
    print(f"  ✓ Successful: {summary['successful']}")
    if summary['partial'] > 0:
        print(f"  ⚠ Partial: {summary['partial']}")
    if summary['failed'] > 0:
        print(f"  ✗ Failed: {summary['failed']}")

    # Exit code
    # Graph generation failures do NOT fail the build - they are logged as warnings
    # We exit 0 even if some graphs failed (best-effort)
    print("\nGraph generation complete (best-effort)")
    sys.exit(0)


if __name__ == "__main__":
    main()
