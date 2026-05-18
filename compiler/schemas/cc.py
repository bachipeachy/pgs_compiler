"""
CC (Capability Contract) validator.

Validates:
- Required fields exist
- Pipeline is a list of typed step objects (not strings)
- Each step has required fields and correct types
- Step IDs are unique within the pipeline
- Each step has exactly one capability reference (transform XOR side_effect)
"""

from typing import Any

from pgs_compiler.compiler.atoms import CompilerError, ErrorCode


def validate_cc(artifact: dict[str, Any]) -> list[CompilerError]:
    """
    Validate CC artifact structure.

    Required fields:
    - cc_code: str
    - pipeline: list[dict] (typed execution topology steps)
    - inputs: dict (input contracts)
    - outputs: dict (output contracts)

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
    if "cc_code" not in frontmatter:
        errors.append(
            CompilerError(
                code=ErrorCode.E102_MISSING_FIELD,
                message="Missing required field: cc_code",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"missing_field": "cc_code"},
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

    # Check required fields in core (execution surface)
    required_core_fields = ["pipeline", "inputs", "outputs"]

    for field in required_core_fields:
        if field not in core:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message=f"Missing required field: {field}",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": field, "location": "core"},
                )
            )

    # Check types
    if "cc_code" in frontmatter and not isinstance(frontmatter["cc_code"], str):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'cc_code' must be a string",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "cc_code"},
            )
        )

    # Type check fields in core (execution surface)
    if "pipeline" in core and not isinstance(core["pipeline"], list):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'pipeline' must be a list",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "pipeline", "location": "core"},
            )
        )

    if "inputs" in core and not isinstance(core["inputs"], dict):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'inputs' must be a dict",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "inputs", "location": "core"},
            )
        )

    if "outputs" in core and not isinstance(core["outputs"], dict):
        errors.append(
            CompilerError(
                code=ErrorCode.E103_TYPE_MISMATCH,
                message="Field 'outputs' must be a dict",
                phase="VALIDATE",
                fqdn_id=fqdn_id,
                artifact_code=artifact_code,
                context={"field": "outputs", "location": "core"},
            )
        )

    # Step-level structural validation
    # Only proceed if pipeline is a non-empty list (type already checked above)
    pipeline = core.get("pipeline")
    if isinstance(pipeline, list) and pipeline:
        errors.extend(_validate_pipeline_steps(pipeline, fqdn_id, artifact_code))

    return errors


def _validate_pipeline_steps(
    pipeline: list[Any],
    fqdn_id: str | None,
    artifact_code: str | None,
) -> list[CompilerError]:
    """Validate each pipeline step has required structure."""
    errors: list[CompilerError] = []
    seen_step_ids: set[str] = set()

    for i, step in enumerate(pipeline):
        step_location = f"core.pipeline[{i}]"

        # Each step must be a dict (typed step object, not a string)
        if not isinstance(step, dict):
            errors.append(
                CompilerError(
                    code=ErrorCode.E103_TYPE_MISMATCH,
                    message=f"Pipeline step at index {i} must be a dict (typed step object), got {type(step).__name__}",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"location": step_location, "index": i},
                )
            )
            continue  # Cannot validate fields of a non-dict step

        step_id = step.get("step")

        # Required: step (str)
        if "step" not in step:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message=f"Pipeline step at index {i} missing required field: step",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": "step", "location": step_location},
                )
            )
        elif not isinstance(step_id, str):
            errors.append(
                CompilerError(
                    code=ErrorCode.E103_TYPE_MISMATCH,
                    message=f"Pipeline step at index {i} field 'step' must be a string",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"field": "step", "location": step_location},
                )
            )
        else:
            # Duplicate step ID check
            if step_id in seen_step_ids:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E203_SCHEMA_INVALID,
                        message=f"Duplicate step ID '{step_id}' in pipeline — step IDs must be unique within a CC",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"duplicate_step_id": step_id, "location": step_location},
                    )
                )
            else:
                seen_step_ids.add(step_id)

        # Required: exactly one of transform or side_effect (str)
        has_transform = "transform" in step
        has_side_effect = "side_effect" in step

        if not has_transform and not has_side_effect:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message=f"Pipeline step '{step_id or i}' missing capability reference — exactly one of 'transform' or 'side_effect' is required",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": "transform|side_effect", "location": step_location},
                )
            )
        elif has_transform and has_side_effect:
            errors.append(
                CompilerError(
                    code=ErrorCode.E203_SCHEMA_INVALID,
                    message=f"Pipeline step '{step_id or i}' has both 'transform' and 'side_effect' — exactly one is allowed",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"conflict": "transform+side_effect", "location": step_location},
                )
            )
        else:
            capability_field = "transform" if has_transform else "side_effect"
            if not isinstance(step[capability_field], str):
                errors.append(
                    CompilerError(
                        code=ErrorCode.E103_TYPE_MISMATCH,
                        message=f"Pipeline step '{step_id or i}' field '{capability_field}' must be a string",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"field": capability_field, "location": step_location},
                    )
                )

        # Required: inputs (dict)
        if "inputs" not in step:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message=f"Pipeline step '{step_id or i}' missing required field: inputs",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": "inputs", "location": step_location},
                )
            )
        elif not isinstance(step["inputs"], dict):
            errors.append(
                CompilerError(
                    code=ErrorCode.E103_TYPE_MISMATCH,
                    message=f"Pipeline step '{step_id or i}' field 'inputs' must be a dict",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"field": "inputs", "location": step_location},
                )
            )

        # Required: outputs (dict)
        if "outputs" not in step:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message=f"Pipeline step '{step_id or i}' missing required field: outputs",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": "outputs", "location": step_location},
                )
            )
        elif not isinstance(step["outputs"], dict):
            errors.append(
                CompilerError(
                    code=ErrorCode.E103_TYPE_MISMATCH,
                    message=f"Pipeline step '{step_id or i}' field 'outputs' must be a dict",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"field": "outputs", "location": step_location},
                )
            )

        # Required: result_surface (list)
        if "result_surface" not in step:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message=f"Pipeline step '{step_id or i}' missing required field: result_surface",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": "result_surface", "location": step_location},
                )
            )
        elif not isinstance(step["result_surface"], list):
            errors.append(
                CompilerError(
                    code=ErrorCode.E103_TYPE_MISMATCH,
                    message=f"Pipeline step '{step_id or i}' field 'result_surface' must be a list",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"field": "result_surface", "location": step_location},
                )
            )

        # Required: on_result (dict)
        if "on_result" not in step:
            errors.append(
                CompilerError(
                    code=ErrorCode.E102_MISSING_FIELD,
                    message=f"Pipeline step '{step_id or i}' missing required field: on_result",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"missing_field": "on_result", "location": step_location},
                )
            )
        elif not isinstance(step["on_result"], dict):
            errors.append(
                CompilerError(
                    code=ErrorCode.E103_TYPE_MISMATCH,
                    message=f"Pipeline step '{step_id or i}' field 'on_result' must be a dict",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"field": "on_result", "location": step_location},
                )
            )

    return errors
