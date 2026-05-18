"""
WF (Workflow) validator.

Validates:
- Required fields exist
- DAG structure (nodes + transitions)
- Runtime binding reference
"""

from typing import Any

from pgs_compiler.compiler.atoms import CompilerError, ErrorCode


def validate_wf(artifact: dict[str, Any]) -> list[CompilerError]:
    """
    Validate WF artifact structure.

    Required fields:
    - wf_code: str
    - core: dict (workflow structure)
    - core.nodes: dict (DAG node definitions)
    - runtime_binding: str (FQDN reference to RB artifact)

    Optional fields:
    - description: str
    - structure: str (FQDN reference to STRUCTURE artifact)
    - inputs: dict (input parameters)
    - outputs: dict (output schema)

    Args:
        artifact: Parsed artifact dict

    Returns:
        List of validation errors (empty if valid)
    """
    errors: list[CompilerError] = []
    fqdn_id = artifact.get("fqdn_id")
    artifact_code = artifact.get("artifact_code")
    frontmatter = artifact.get("frontmatter", {})

    # Check required top-level fields
    required_fields = ["wf_code", "core", "runtime_binding"]

    for field in required_fields:
        if field not in frontmatter:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message=f"Missing required field: {field}",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": field},
                )
            )

    # Check types
    if "wf_code" in frontmatter and not isinstance(frontmatter["wf_code"], str):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'wf_code' must be a string",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "wf_code"},
            )
        )

    # Check core structure (DAG topology)
    if "core" in frontmatter:
        if not isinstance(frontmatter["core"], dict):
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
            # Check for nodes (DAG structure)
            core = frontmatter["core"]
            if "nodes" not in core:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E102_MISSING_FIELD,
                        message="Missing required field: core.nodes",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"missing_field": "core.nodes"},
                    )
                )
            elif not isinstance(core["nodes"], dict):
                errors.append(
                    CompilerError(
                        code=ErrorCode.E103_TYPE_MISMATCH,
                        message="Field 'core.nodes' must be a dict (DAG node map)",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"field": "core.nodes"},
                    )
                )

    if "runtime_binding" in frontmatter and not isinstance(
        frontmatter["runtime_binding"], str
    ):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'runtime_binding' must be a string (FQDN)",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "runtime_binding"},
            )
        )

    return errors
