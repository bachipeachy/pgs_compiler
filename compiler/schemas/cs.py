"""
CS (Capability Side-effect) validator.

Validates:
- Required fields exist
- Types are correct
- Runtime binding references
"""

from typing import Any

from pgs_compiler.compiler.atoms import CompilerError, ErrorCode


def validate_cs(artifact: dict[str, Any]) -> list[CompilerError]:
    """
    Validate CS artifact structure.

    Required fields:
    - cs_code: str (top level)
    - core: dict (execution surface)
    - core.policy: dict (side-effect policy)
    - core.policy.operations: list[str] (allowed operations)

    Optional fields:
    - core.summary: str
    - core.description: str

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
    if "cs_code" not in frontmatter:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: cs_code",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "cs_code"},
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

    # Check policy section exists (side-effect specification)
    policy = core.get("policy")
    if not policy:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: policy",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "policy", "location": "core"},
            )
        )
        return errors  # Cannot proceed without policy

    # Check operations array exists in policy
    if "operations" not in policy:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: operations",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "operations", "location": "core.policy"},
            )
        )

    # Check types
    if "cs_code" in frontmatter and not isinstance(frontmatter["cs_code"], str):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'cs_code' must be a string",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "cs_code"},
            )
        )

    if "operations" in policy and not isinstance(policy["operations"], list):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'operations' must be a list",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={
                    "field": "operations",
                    "location": "core.policy",
                },
            )
        )

    return errors
