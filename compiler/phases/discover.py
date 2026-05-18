"""
Discovery phase: Scan filesystem for protocol artifacts.

Input: Config (search_roots, artifact_types, exclusions)
Output: PhaseResult with discovered artifacts (list[dict])

Artifacts format:
{
    "fqdn_id": "namespace::artifact_code",
    "artifact_code": "CT_FOO_V0",
    "artifact_type": "CT",
    "namespace": "pkg_transforms",
    "source_path": "/path/to/CT_FOO_V0.md",
    "version": "0"
}

Design:
- Deterministic ordering (sorted by FQDN)
- FQDN collision detection
- Filename pattern validation
- Cross-repo reference detection
"""

import re
from pathlib import Path
from typing import Any

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    FQDN,
    PhaseResult,
    PhaseStatus,
    build_fqdn,
    parse_fqdn,
    sort_artifacts_by_fqdn,
)


# Artifact filename pattern: {TYPE}_{NAME}_V{N}.md
ARTIFACT_PATTERN = re.compile(
    r"^(?P<type>[A-Z]+)_(?P<name>[A-Z0-9_]+)_V(?P<version>\d+)\.md$"
)


def discover_phase(
    search_roots: list[Path],
    artifact_types: list[str],
    exclusions: list[str] | None = None,
) -> PhaseResult:
    """
    Discover protocol artifacts in filesystem.

    Args:
        search_roots: Directories to scan (absolute paths)
        artifact_types: Artifact type codes to include (e.g., ["CT", "CS", "WF"])
        exclusions: Directory names to skip (e.g., [".git", "__pycache__"])

    Returns:
        PhaseResult with discovered artifacts (sorted by FQDN)

    Errors:
        E001_NO_ARTIFACTS: No artifacts found
        E002_DUPLICATE_FQDN: Multiple artifacts with same FQDN
        E003_INVALID_FILENAME: Filename doesn't match pattern
        E004_CROSS_REPO_REF: Artifact outside search roots
    """
    exclusions = exclusions or [".git", "__pycache__", "node_modules", ".venv"]
    errors: list[CompilerError] = []
    artifacts: list[dict[str, Any]] = []
    seen_fqdns: dict[str, Path] = {}  # fqdn_id -> first source_path

    # Scan each search root
    for search_root in search_roots:
        if not search_root.exists():
            errors.append(
                CompilerError(
                    code=ErrorCode.E001_NO_ARTIFACTS,
                    message=f"Search root does not exist: {search_root}",
                    phase="DISCOVER",
                    source_path=search_root,
                )
            )
            continue

        # Walk directory tree
        for markdown_file in search_root.rglob("*.md"):
            # Skip excluded directories
            if any(excl in markdown_file.parts for excl in exclusions):
                continue

            # Validate filename pattern (skip files that don't match - not all .md files are artifacts)
            match = ARTIFACT_PATTERN.match(markdown_file.name)
            if not match:
                # Skip silently - filename pattern is the protocol's declaration of "this is a compilable artifact"
                # Files like process_segments_v0.md, README.md, etc. are documentation, not artifacts
                continue

            # Extract components
            artifact_type = match.group("type")
            artifact_name = match.group("name")
            version = match.group("version")

            # Filter by artifact type
            if artifact_type not in artifact_types:
                continue

            # Build artifact code and FQDN
            artifact_code = f"{artifact_type}_{artifact_name}_V{version}"

            # Infer namespace from directory structure
            # Convention: parent directory name becomes namespace
            # Example: /path/to/pkg_transforms/CT_FOO_V0.md → namespace=pkg_transforms
            namespace = markdown_file.parent.name

            # Build FQDN
            fqdn_obj = FQDN(namespace=namespace, artifact_code=artifact_code)
            fqdn_id = str(fqdn_obj)

            # Check for FQDN collision
            if fqdn_id in seen_fqdns:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E002_DUPLICATE_FQDN,
                        message=f"Duplicate FQDN: {fqdn_id}",
                        phase="DISCOVER",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        source_path=markdown_file,
                        context={
                            "first_occurrence": str(seen_fqdns[fqdn_id]),
                            "duplicate_occurrence": str(markdown_file),
                        },
                    )
                )
                continue

            # Verify artifact is within search roots (no cross-repo references)
            is_within_search_roots = any(
                search_root in markdown_file.parents for search_root in search_roots
            )
            if not is_within_search_roots:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E004_CROSS_REPO_REF,
                        message=f"Artifact outside search roots: {markdown_file}",
                        phase="DISCOVER",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        source_path=markdown_file,
                        context={"search_roots": [str(r) for r in search_roots]},
                    )
                )
                continue

            # Record artifact
            seen_fqdns[fqdn_id] = markdown_file
            artifacts.append(
                {
                    "fqdn_id": fqdn_id,
                    "artifact_code": artifact_code,
                    "artifact_type": artifact_type,
                    "namespace": namespace,
                    "source_path": str(markdown_file),
                    "version": version,
                }
            )

    # Check if any artifacts found
    if not artifacts and not errors:
        errors.append(
            CompilerError(
                code=ErrorCode.E001_NO_ARTIFACTS,
                message=f"No artifacts found in search roots: {search_roots}",
                phase="DISCOVER",
                context={
                    "search_roots": [str(r) for r in search_roots],
                    "artifact_types": artifact_types,
                },
            )
        )

    # Sort artifacts by FQDN (deterministic ordering - Patch E)
    artifacts_sorted = sort_artifacts_by_fqdn(artifacts)

    # Build result
    if errors:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={"discovered_artifacts": artifacts_sorted},
            errors=tuple(errors),
        )
    else:
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={"discovered_artifacts": artifacts_sorted},
            errors=tuple(),
        )
