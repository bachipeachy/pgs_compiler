"""
CT (Capability Transform) validator.

Validates:
- Required fields exist
- Types are correct
- No invalid fields
"""

from typing import Any

from pgs_compiler.compiler.atoms import CompilerError, ErrorCode


def validate_ct(artifact: dict[str, Any]) -> list[CompilerError]:
    """
    Validate CT artifact structure.

    Required fields:
    - ct_code: str (top level)
    - core: dict (execution surface)
    - core.summary: str
    - core.description: str

    Note: inputs/outputs are documented in markdown body,
    not in Machine section frontmatter.

    Args:
        artifact: Parsed artifact dict

    Returns:
        List of validation errors (empty if valid)
    """
    errors: list[CompilerError] = []
    fqdn_id = artifact.get("fqdn_id")
    artifact_code = artifact.get("artifact_code")
    frontmatter = artifact.get("frontmatter", {})

    # Check top-level required fields
    if "ct_code" not in frontmatter:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: ct_code",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "ct_code"},
            )
        )

    # Check core section exists (execution surface)
    core = frontmatter.get("core")
    if not core:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: core",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "core"},
            )
        )
        return errors  # Cannot proceed without core

    # Check required fields in core (minimal execution surface)
    if "summary" not in core:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: summary",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "summary", "location": "core"},
            )
        )

    if "description" not in core:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: description",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "description", "location": "core"},
            )
        )

    # Check types
    if "ct_code" in frontmatter and not isinstance(frontmatter["ct_code"], str):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'ct_code' must be a string",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "ct_code"},
            )
        )

    if "summary" in core and not isinstance(core["summary"], str):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'summary' must be a string",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "summary", "location": "core"},
            )
        )

    if "description" in core and not isinstance(core["description"], str):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'description' must be a string",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "description", "location": "core"},
            )
        )

    return errors
