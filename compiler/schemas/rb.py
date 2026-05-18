"""
RB (Runtime Binding) validator.

Validates:
- Required fields exist
- CS bindings structure
- No business logic or control flow
"""

from typing import Any

from pgs_compiler.compiler.atoms import CompilerError, ErrorCode


def validate_rb(artifact: dict[str, Any]) -> list[CompilerError]:
    """
    Validate RB artifact structure.

    Required fields:
    - rb_code: str
    - core.bindings: dict[str, dict] (CS FQDN -> runtime config)

    Optional fields:
    - description: str
    - parameters: list[str] (parameter names)

    Constitutional constraint:
    - RB MUST NOT contain business logic or control flow
    - Only CS bindings to runtime implementations

    Args:
        artifact: Parsed artifact dict

    Returns:
        List of validation errors (empty if valid)
    """
    errors: list[CompilerError] = []
    fqdn_id = artifact.get("fqdn_id")
    artifact_code = artifact.get("artifact_code")
    frontmatter = artifact.get("frontmatter", {})

    # Check required fields
    if "rb_code" not in frontmatter:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: rb_code",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "rb_code"},
            )
        )

    if "core" not in frontmatter:
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
    elif not isinstance(frontmatter["core"], dict):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'core' must be a dict",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "core"},
            )
        )
    else:
        # Check core.bindings exists
        core = frontmatter["core"]
        if "bindings" not in core:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message="Missing required field: core.bindings",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": "core.bindings"},
                )
            )
        elif not isinstance(core["bindings"], dict):
            errors.append(
                CompilerError(
                    code=ErrorCode.E103_TYPE_MISMATCH,
                    message="Field 'core.bindings' must be a dict",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"field": "core.bindings"},
                )
            )

    # Check rb_code type
    if "rb_code" in frontmatter and not isinstance(frontmatter["rb_code"], str):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'rb_code' must be a string",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "rb_code"},
            )
        )

    return errors
