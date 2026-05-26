"""
Verify phase: Check outputs match expectations.

Input: Materialized paths (list[Path])
Output: PhaseResult with verification status

Verifies:
1. Expected files exist
2. No undeclared files present
3. Roundtrip integrity (parse(materialized) == original)
4. Output schema valid (optional)

Design:
- Bounded verification (check declared outputs only)
- No filesystem guessing
- Fail on unexpected files (prevent output drift)
- Roundtrip check catches serialization drift and corruption
"""

import json
from pathlib import Path
from typing import Any

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    PhaseResult,
    PhaseStatus,
    ensure_deterministic_output,
    strip_transient_pipeline_fields,
)


def verify_phase(
    materialized_paths: list[str],
    structure: dict,
    original_artifacts: list[dict[str, Any]] | None = None,
    strict: bool = True,
    check_roundtrip: bool = True,
) -> PhaseResult:
    """
    Verify materialized outputs match expectations.

    Args:
        materialized_paths: Output from materialize_phase (expected files)
        structure: STRUCTURE artifact declaring output paths
        original_artifacts: Original artifacts for roundtrip verification
        strict: Fail on undeclared files
        check_roundtrip: Enable roundtrip verification

    Returns:
        PhaseResult with verification status

    Errors:
        E401_MISSING_OUTPUT: Expected file not found
        E402_UNDECLARED_OUTPUT: Unexpected file found (strict mode only)
        E403_OUTPUT_MISMATCH: Roundtrip verification failed
    """
    errors: list[CompilerError] = []

    # Convert paths to Path objects
    expected_paths = {Path(p) for p in materialized_paths}

    # Check expected files exist
    for expected_path in expected_paths:
        if not expected_path.exists():
            errors.append(
                CompilerError(
                    code=ErrorCode.E401_MISSING_OUTPUT,
                    message=f"Expected output not found: {expected_path}",
                    phase="VERIFY",
                    context={"expected_path": str(expected_path)},
                )
            )

    # Roundtrip verification (critical for catching serialization drift)
    if check_roundtrip and original_artifacts is not None:
        roundtrip_errors = _verify_roundtrip(
            original_artifacts, materialized_paths
        )
        errors.extend(roundtrip_errors)

    # Check for undeclared files (strict mode)
    if strict:
        # STRUCTURE-driven output resolution
        from pgs_governance.implementation.structure.resolution.layer_resolver import LayerResolver

        resolver = LayerResolver()
        actual_paths = set()

        # Get all layer output paths from STRUCTURE
        layer_outputs = structure.get("output_configuration", {}).get("layer_outputs", {})

        for layer_code in layer_outputs:
            try:
                layer_output_dir = resolver.resolve_output_path(
                    "layer_outputs", layer_code, structure
                )
                if layer_output_dir.exists():
                    actual_paths.update(layer_output_dir.rglob("*.json"))
            except Exception:
                # Skip layers that fail to resolve
                continue

        # Filter out temp files
        actual_paths = {p for p in actual_paths if not p.name.endswith(".tmp")}

        # Find undeclared files
        undeclared = actual_paths - expected_paths

        for undeclared_path in undeclared:
            errors.append(
                CompilerError(
                    code=ErrorCode.E402_UNDECLARED_OUTPUT,
                    message=f"Undeclared output found: {undeclared_path}",
                    phase="VERIFY",
                    context={
                        "undeclared_path": str(undeclared_path),
                        "suggestion": "Remove file or add to expected outputs",
                    },
                )
            )

        # Patch 4: Enforce zero extra directories
        # Check for unexpected directories in output
        undeclared_dirs = _check_undeclared_directories(
            structure, materialized_paths, resolver
        )
        errors.extend(undeclared_dirs)

    # Build result
    if errors:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={"verified": False},
            errors=tuple(errors),
        )
    else:
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={"verified": True},
            errors=tuple(),
        )


def _verify_roundtrip(
    original_artifacts: list[dict[str, Any]],
    materialized_paths: list[str],
) -> list[CompilerError]:
    """
    Verify roundtrip integrity: parse(materialized_json) == original.

    Catches:
    - Serialization drift
    - Schema mismatches
    - Silent corruption

    Args:
        original_artifacts: Original artifacts from validate phase
        materialized_paths: Paths to materialized JSON files

    Returns:
        List of E403_OUTPUT_MISMATCH errors
    """
    errors: list[CompilerError] = []

    # Build index of original artifacts by FQDN
    original_by_fqdn: dict[str, dict[str, Any]] = {
        artifact["fqdn_id"]: artifact for artifact in original_artifacts
    }

    # Check each materialized file
    for path_str in materialized_paths:
        path = Path(path_str)

        if not path.exists():
            continue  # Already reported by missing output check

        try:
            # Load materialized JSON
            with open(path, "r", encoding="utf-8") as f:
                materialized = json.load(f)

            fqdn_id = materialized.get("fqdn_id")
            if not fqdn_id:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E403_OUTPUT_MISMATCH,
                        message=f"Materialized artifact missing fqdn_id: {path}",
                        phase="VERIFY",
                        context={"path": str(path)},
                    )
                )
                continue

            # Find original artifact
            original = original_by_fqdn.get(fqdn_id)
            if not original:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E403_OUTPUT_MISMATCH,
                        message=f"No original artifact for FQDN: {fqdn_id}",
                        phase="VERIFY",
                        fqdn_id=fqdn_id,
                        context={"path": str(path)},
                    )
                )
                continue

            # Normalize both for comparison: strip compiler-transient fields from the
            # pipeline artifact (source_path etc.) so the comparison reflects only
            # semantic state — exactly what materialization emits.
            normalized_original = ensure_deterministic_output(strip_transient_pipeline_fields(original))
            normalized_materialized = ensure_deterministic_output(materialized)

            # Compare
            if normalized_original != normalized_materialized:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E403_OUTPUT_MISMATCH,
                        message=f"Roundtrip mismatch: {fqdn_id}",
                        phase="VERIFY",
                        fqdn_id=fqdn_id,
                        artifact_code=original.get("artifact_code"),
                        context={
                            "path": str(path),
                            "suggestion": "Check serialization logic in materialize phase",
                        },
                    )
                )

        except json.JSONDecodeError as e:
            errors.append(
                CompilerError(
                    code=ErrorCode.E403_OUTPUT_MISMATCH,
                    message=f"Invalid JSON in materialized file: {e}",
                    phase="VERIFY",
                    context={"path": str(path), "json_error": str(e)},
                )
            )
        except Exception as e:
            errors.append(
                CompilerError(
                    code=ErrorCode.E901_INTERNAL_ERROR,
                    message=f"Roundtrip verification error: {e}",
                    phase="VERIFY",
                    context={"path": str(path), "error": str(e)},
                )
            )

    return errors


def _check_undeclared_directories(
    structure: dict,
    materialized_paths: list[str],
    resolver,
) -> list[CompilerError]:
    """
    Check for unexpected directories in output (Patch 4).

    CRITICAL: Strict mode enforces zero extra directories.
    Only allowed: {namespace}/{artifact_type}/ paths.

    Args:
        structure: STRUCTURE artifact declaring output paths
        materialized_paths: Expected materialized file paths
        resolver: LayerResolver instance

    Returns:
        List of E402_UNDECLARED_OUTPUT errors for unexpected directories
    """
    errors: list[CompilerError] = []

    # Get list of output directories from STRUCTURE
    layer_outputs = structure.get("output_configuration", {}).get("layer_outputs", {})
    output_dirs = []

    for layer_code in layer_outputs:
        try:
            layer_output_dir = resolver.resolve_output_path(
                "layer_outputs", layer_code, structure
            )
            output_dirs.append(layer_output_dir)
        except Exception:
            # Skip layers that fail to resolve
            continue

    # Build allowed directory set from materialized paths
    allowed_dirs: set[Path] = set()

    for path_str in materialized_paths:
        path = Path(path_str)

        # Find which output_dir this path belongs to
        parent_output_dir = None
        for out_dir in output_dirs:
            try:
                if path.is_relative_to(out_dir):
                    parent_output_dir = out_dir
                    break
            except (ValueError, TypeError):
                continue

        if not parent_output_dir:
            continue

        # Add all parent directories up to parent_output_dir
        current = path.parent
        while current != parent_output_dir and current != current.parent:
            allowed_dirs.add(current)
            current = current.parent

    # Scan actual directories in all output_dirs
    actual_dirs: set[Path] = set()

    for out_dir in output_dirs:
        if not out_dir.exists():
            continue

        for item in out_dir.rglob("*"):
            if item.is_dir():
                # Skip hidden directories
                if any(part.startswith(".") for part in item.parts):
                    continue

                actual_dirs.add(item)

    # Find undeclared directories
    undeclared = actual_dirs - allowed_dirs

    for undeclared_dir in undeclared:
        # Check if it's truly undeclared (not a parent of allowed)
        is_parent = any(
            allowed.is_relative_to(undeclared_dir) for allowed in allowed_dirs
        )

        if not is_parent:
            errors.append(
                CompilerError(
                    code=ErrorCode.E402_UNDECLARED_OUTPUT,
                    message=f"Undeclared output directory: {undeclared_dir}",
                    phase="VERIFY",
                    context={
                        "undeclared_directory": str(undeclared_dir),
                        "suggestion": "Remove directory or add artifacts to it",
                    },
                )
            )

    return errors
