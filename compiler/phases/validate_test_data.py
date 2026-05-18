"""
Validate TEST_DATA phase: Ensure test cases match CT contracts.

Input: Validated artifacts (list[dict])
Output: PhaseResult with validation results

Design:
- Validate each TEST_DATA artifact against its target CT
- Check that bindings contain all required inputs
- Check that bindings don't contain unknown inputs
- Check that bindings have correct input types
- Check that expected outputs match CT.outputs exactly (structural enforcement)
- Check that expected outputs have correct types
- Detect and reject placeholder values (computed_value, NOT_NONE, etc.)
- Detect atom-level TEST_DATA (common error: writing raw atom outputs instead of CT projection)
- Fail fast on violations (bad TEST_DATA should not reach execution)

CRITICAL VALIDATION RULES:
1. TEST_DATA.expected MUST match CT.outputs structure exactly
2. Placeholders are BANNED (violates determinism)
3. Output keys must match CT.outputs, not atom outputs
4. Object types must be nested dicts, not flattened fields

This phase runs AFTER validate phase, BEFORE conformance_generate phase.
"""

import re
from typing import Any

import yaml

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    PhaseResult,
    PhaseStatus,
)


def _is_placeholder(value: Any) -> bool:
    """
    Detect placeholder values that should be banned in TEST_DATA.

    Placeholders are meta-syntax like (computed_value), NOT_NONE, etc.
    These are not valid runtime values and violate determinism.

    Args:
        value: Value to check

    Returns:
        True if value is a placeholder pattern
    """
    if not isinstance(value, str):
        return False

    # Detect common placeholder patterns
    placeholder_patterns = [
        "(computed_",      # (computed_value), (computed_recovery_id)
        "(random_",        # (random_bytes)
        "NOT_NONE",        # Lazy placeholder
        "(derived_",       # (derived_key)
        "(generated_",     # (generated_entropy)
    ]

    for pattern in placeholder_patterns:
        if pattern in value:
            return True

    return False


def _validate_type(value: Any, schema: dict | str) -> str | None:
    """
    Validate that value matches expected semantic type from schema.

    Args:
        value: Actual value from TEST_DATA bindings/expected
        schema: Type schema from CT contract (dict with type/nullable/etc or string type)

    Returns:
        Error message if type mismatch, None if valid

    Supported types (lightweight, minimal):
    - Primitives: string, integer, number, boolean, null
    - Semantic: hex_string (string starting with 0x), any (allows all types)
    - Containers: object, array
    - Typed arrays: array[integer], array[string], etc.

    CRITICAL: Rejects placeholder patterns (computed_value, NOT_NONE, etc.)
    """
    # FAIL FAST: Reject placeholders (architectural violation)
    if _is_placeholder(value):
        return f"placeholder detected: {value} (TEST_DATA must contain real values, not meta-syntax)"

    # Extract type and nullable from schema
    if isinstance(schema, dict):
        expected_type = schema.get("type")
        nullable = schema.get("nullable", False)
    else:
        expected_type = schema
        nullable = False

    if not expected_type:
        return None  # No type constraint

    # Special: any type (allows everything, including null)
    if expected_type == "any":
        return None

    # Null/None handling
    if expected_type == "null":
        return None if value is None else f"expected null, got {type(value).__name__}"

    # Check nullable BEFORE rejecting None
    if value is None:
        if nullable:
            return None  # Null is valid for nullable types
        return f"expected {expected_type}, got null"

    # Primitives
    if expected_type == "string":
        return None if isinstance(value, str) else f"expected string, got {type(value).__name__}"
    if expected_type in ("integer", "int"):
        return None if isinstance(value, int) and not isinstance(value, bool) else f"expected integer, got {type(value).__name__}"
    if expected_type == "number":
        return None if isinstance(value, (int, float)) and not isinstance(value, bool) else f"expected number, got {type(value).__name__}"
    if expected_type == "boolean":
        return None if isinstance(value, bool) else f"expected boolean, got {type(value).__name__}"

    # Semantic types
    if expected_type == "hex_string":
        if not isinstance(value, str):
            return f"expected hex string, got {type(value).__name__}"
        if not value.startswith("0x"):
            return f"hex string must start with '0x', got '{value[:20]}...'"
        try:
            bytes.fromhex(value[2:])
            return None
        except ValueError as e:
            return f"invalid hex string: {e}"

    # Containers
    if expected_type == "object":
        return None if isinstance(value, dict) else f"expected object, got {type(value).__name__}"
    if expected_type == "array":
        return None if isinstance(value, list) else f"expected array, got {type(value).__name__}"

    # Typed arrays (e.g., "array[integer]", "array[string]")
    if expected_type.startswith("array[") and expected_type.endswith("]"):
        if not isinstance(value, list):
            return f"expected array, got {type(value).__name__}"
        element_type = expected_type[6:-1]  # Extract type between [ ]
        for i, elem in enumerate(value):
            elem_error = _validate_type(elem, element_type)
            if elem_error:
                return f"array element {i}: {elem_error}"
        return None

    # Unknown type - don't enforce (forward compatibility)
    return None


def validate_test_data_phase(
    validated_artifacts: list[dict[str, Any]],
) -> PhaseResult:
    """
    Validate TEST_DATA artifacts against their target CT contracts.

    Ensures:
    1. Target CT exists and is compiled
    2. All required CT inputs are present in test bindings
    3. No unknown inputs are present in test bindings
    4. Input types match CT.inputs declarations
    5. Expected outputs are present and shaped as dict
    6. All declared CT outputs are present in expected
    7. No unknown outputs are present in expected
    8. Output types match CT.outputs declarations

    Args:
        validated_artifacts: Output from validate_phase

    Returns:
        PhaseResult with validation status

    Errors:
        E803_TEST_DATA_INVALID: Test data does not match CT contract
    """
    errors: list[CompilerError] = []

    # Index CT artifacts by artifact_code
    ct_artifacts = {
        a["artifact_code"]: a for a in validated_artifacts
        if a["artifact_type"] == "CT"
    }

    # Find all TEST_DATA artifacts
    test_data_artifacts = [
        a for a in validated_artifacts
        if a["artifact_type"] == "TEST_DATA"
    ]

    if not test_data_artifacts:
        # No TEST_DATA to validate - this is OK
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={"validated_test_data": 0},
            errors=tuple(),
        )

    validated_count = 0

    for td in test_data_artifacts:
        fqdn_id = td["fqdn_id"]
        artifact_code = td["artifact_code"]

        # Extract target CT code
        target_ct_code = td.get("frontmatter", {}).get("target", {}).get("ct_code")

        if not target_ct_code:
            # Try parsing from content if not in frontmatter
            try:
                content = td.get("content", "")
                target_match = re.search(r"## Target\s*\n+```yaml\s*\n(.*?)\n```", content, re.DOTALL)
                if target_match:
                    target_yaml = yaml.safe_load(target_match.group(1))
                    target_ct_code = target_yaml.get("ct_code")
            except Exception:
                pass

        if not target_ct_code:
            errors.append(
                CompilerError(
                    code=ErrorCode.E803_TEST_DATA_INVALID,
                    message=f"TEST_DATA missing target.ct_code",
                    phase="VALIDATE_TEST_DATA",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                )
            )
            continue

        # Check if target CT exists
        if target_ct_code not in ct_artifacts:
            errors.append(
                CompilerError(
                    code=ErrorCode.E803_TEST_DATA_INVALID,
                    message=f"Target CT not found: {target_ct_code} (not in compile batch)",
                    phase="VALIDATE_TEST_DATA",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"target_ct_code": target_ct_code},
                )
            )
            continue

        ct = ct_artifacts[target_ct_code]
        ct_inputs = ct.get("frontmatter", {}).get("core", {}).get("inputs", {})

        # Parse test cases from content
        content = td.get("content", "")
        case_blocks = re.findall(
            r"### Case \d+: (?P<case_id>\w+).*?```yaml\n(?P<case_data>.*?)```",
            content,
            re.DOTALL
        )

        for case_id, case_data in case_blocks:
            try:
                case_dict = yaml.safe_load(case_data)
            except Exception as e:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E101_INVALID_YAML,
                        message=f"Failed to parse case {case_id}: {e}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"case_id": case_id},
                    )
                )
                continue

            bindings = case_dict.get("bindings", {})

            # Validate required inputs are present
            for input_name, input_spec in ct_inputs.items():
                if isinstance(input_spec, dict):
                    is_required = input_spec.get("required", False)
                    if is_required and input_name not in bindings:
                        errors.append(
                            CompilerError(
                                code=ErrorCode.E803_TEST_DATA_INVALID,
                                message=f"Missing required input '{input_name}' in case {case_id}",
                                phase="VALIDATE_TEST_DATA",
                                fqdn_id=fqdn_id,
                                artifact_code=artifact_code,
                                context={
                                    "target_ct_code": target_ct_code,
                                    "case_id": case_id,
                                    "missing_input": input_name,
                                },
                            )
                        )

            # Validate no unknown inputs are present
            for binding_name in bindings.keys():
                if binding_name not in ct_inputs:
                    errors.append(
                        CompilerError(
                            code=ErrorCode.E803_TEST_DATA_INVALID,
                            message=f"Unknown input '{binding_name}' in case {case_id}",
                            phase="VALIDATE_TEST_DATA",
                            fqdn_id=fqdn_id,
                            artifact_code=artifact_code,
                            context={
                                "target_ct_code": target_ct_code,
                                "case_id": case_id,
                                "unknown_input": binding_name,
                                "valid_inputs": list(ct_inputs.keys()),
                            },
                        )
                    )

            # Validate input types match contract (CRITICAL: prevent runtime type errors)
            for binding_name, binding_value in bindings.items():
                if binding_name not in ct_inputs:
                    continue  # Already reported as unknown input

                input_spec = ct_inputs[binding_name]
                if not isinstance(input_spec, dict):
                    continue  # No type spec available

                expected_type = input_spec.get("type")
                if not expected_type:
                    continue  # No type constraint declared

                # Type validation (lightweight, no overengineering)
                type_error = _validate_type(binding_value, input_spec)
                if type_error:
                    errors.append(
                        CompilerError(
                            code=ErrorCode.E803_TEST_DATA_INVALID,
                            message=f"Type mismatch for '{binding_name}' in case {case_id}: {type_error}",
                            phase="VALIDATE_TEST_DATA",
                            fqdn_id=fqdn_id,
                            artifact_code=artifact_code,
                            context={
                                "target_ct_code": target_ct_code,
                                "case_id": base_id,
                                "input_name": binding_name,
                                "expected_type": expected_type,
                                "actual_value": str(binding_value)[:100],  # Truncate long values
                            },
                        )
                    )

            # Validate expected outputs match contract (CRITICAL: prevent runtime mismatches)
            ct_outputs = ct.get("frontmatter", {}).get("core", {}).get("outputs", {})
            expected_outputs = case_dict.get("expected", {})

            # FAIL FAST: expected must be present
            if "expected" not in case_dict:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"Missing 'expected' field in case {case_id}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={
                            "target_ct_code": target_ct_code,
                            "case_id": case_id,
                        },
                    )
                )
                continue

            # FAIL FAST: expected must be dict (contract-shaped outputs)
            if not isinstance(expected_outputs, dict):
                errors.append(
                    CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"'expected' must be dict (contract-shaped outputs), got {type(expected_outputs).__name__} in case {case_id}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={
                            "target_ct_code": target_ct_code,
                            "case_id": case_id,
                            "expected_type": "dict",
                            "actual_type": type(expected_outputs).__name__,
                        },
                    )
                )
                continue

            # Validate assertion specs against closed vocabulary
            # (INVARIANT_CONFORMANCE_ASSERTION_MODE_VALID_V0)
            _ALLOWED_MODES = {"exact", "property", "schema"}
            _ALLOWED_TYPES: dict[str, set[str]] = {
                "property": {"hex_string", "byte_length_range", "non_zero"},
                "schema": {"json_schema"},
            }
            _REQUIRED_FIELDS: dict[str, list[str]] = {
                "byte_length_range": ["min", "max"],
                "json_schema": ["schema_ref"],
            }

            assertions = case_dict.get("assertions", {})
            for assert_field, assert_spec in (assertions or {}).items():
                if not isinstance(assert_spec, dict):
                    errors.append(CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"Assertion spec for '{assert_field}' must be a dict in case {case_id}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"case_id": case_id, "field": assert_field},
                    ))
                    continue
                mode = assert_spec.get("mode")
                if mode is None:
                    errors.append(CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"Assertion for '{assert_field}' in case {case_id} missing required 'mode' field",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"case_id": case_id, "field": assert_field, "allowed_modes": sorted(_ALLOWED_MODES)},
                    ))
                    continue
                if mode not in _ALLOWED_MODES:
                    errors.append(CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"Assertion for '{assert_field}' in case {case_id} has unknown mode '{mode}'; allowed: {sorted(_ALLOWED_MODES)}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"case_id": case_id, "field": assert_field, "mode": mode, "allowed_modes": sorted(_ALLOWED_MODES)},
                    ))
                    continue
                if mode == "exact":
                    continue  # exact is valid; no type required
                assert_type = assert_spec.get("type")
                allowed_types = _ALLOWED_TYPES.get(mode, set())
                if assert_type is None:
                    errors.append(CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"Assertion for '{assert_field}' in case {case_id} with mode '{mode}' missing required 'type' field; allowed types: {sorted(allowed_types)}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"case_id": case_id, "field": assert_field, "mode": mode},
                    ))
                    continue
                if assert_type not in allowed_types:
                    errors.append(CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"Assertion for '{assert_field}' in case {case_id} has unknown type '{assert_type}' for mode '{mode}'; allowed: {sorted(allowed_types)}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"case_id": case_id, "field": assert_field, "mode": mode, "type": assert_type, "allowed_types": sorted(allowed_types)},
                    ))
                    continue
                for req_field in _REQUIRED_FIELDS.get(assert_type, []):
                    if req_field not in assert_spec:
                        errors.append(CompilerError(
                            code=ErrorCode.E803_TEST_DATA_INVALID,
                            message=f"Assertion for '{assert_field}' in case {case_id} type '{assert_type}' missing required parameter '{req_field}'",
                            phase="VALIDATE_TEST_DATA",
                            fqdn_id=fqdn_id,
                            artifact_code=artifact_code,
                            context={"case_id": case_id, "field": assert_field, "type": assert_type, "missing_param": req_field},
                        ))

            # Validate expected output keys match CT.outputs exactly
            # Keys covered by assertions count as declared — they are validated structurally at runtime
            assertion_keys = set(assertions.keys())
            expected_keys = set(expected_outputs.keys())
            declared_keys = set(ct_outputs.keys())

            # DIAGNOSTIC: Detect atom-level TEST_DATA (common error pattern)
            # If NO expected keys match CT.outputs, user likely wrote atom outputs instead of CT projection
            if expected_keys and declared_keys and not expected_keys.intersection(declared_keys):
                errors.append(
                    CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"TEST_DATA appears to be written at ATOM level, not CT level in case {case_id}. "
                                f"Expected keys {sorted(expected_keys)} do not match ANY declared outputs {sorted(declared_keys)}. "
                                f"Did you write raw atom outputs instead of CT.outputs projection?",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={
                            "target_ct_code": target_ct_code,
                            "case_id": case_id,
                            "expected_keys": sorted(expected_keys),
                            "declared_outputs": sorted(declared_keys),
                            "hint": f"Wrap expected outputs under CT.outputs keys: {sorted(declared_keys)}",
                        },
                    )
                )
                # Skip further validation for this case - the fundamental structure is wrong
                continue

            # Missing required outputs (assertion-covered keys satisfy the requirement)
            missing_outputs = declared_keys - expected_keys - assertion_keys
            if missing_outputs:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"Missing required outputs {sorted(missing_outputs)} in case {case_id}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={
                            "target_ct_code": target_ct_code,
                            "case_id": case_id,
                            "missing_outputs": sorted(missing_outputs),
                            "declared_outputs": sorted(declared_keys),
                        },
                    )
                )

            # Unknown outputs (not declared in contract)
            unknown_outputs = expected_keys - declared_keys
            if unknown_outputs:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E803_TEST_DATA_INVALID,
                        message=f"Unknown outputs {sorted(unknown_outputs)} in case {case_id}",
                        phase="VALIDATE_TEST_DATA",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={
                            "target_ct_code": target_ct_code,
                            "case_id": case_id,
                            "unknown_outputs": sorted(unknown_outputs),
                            "valid_outputs": sorted(declared_keys),
                        },
                    )
                )

            # Validate output types match contract (structural enforcement)
            for output_name, output_value in expected_outputs.items():
                if output_name not in ct_outputs:
                    continue  # Already reported as unknown output

                output_spec = ct_outputs[output_name]
                if not isinstance(output_spec, dict):
                    continue  # No type spec available

                expected_type = output_spec.get("type")
                if not expected_type:
                    continue  # No type constraint declared

                # Type validation (includes placeholder detection)
                type_error = _validate_type(output_value, output_spec)
                if type_error:
                    # Enhanced context for object types (common source of confusion)
                    context = {
                        "target_ct_code": target_ct_code,
                        "case_id": case_id,
                        "output_name": output_name,
                        "expected_type": expected_type,
                        "actual_value": str(output_value)[:100],  # Truncate long values
                    }

                    # Add structural hint for object types
                    if expected_type == "object" and not isinstance(output_value, dict):
                        context["hint"] = f"Output '{output_name}' must be object (dict). Did you unwrap the nested structure?"

                    errors.append(
                        CompilerError(
                            code=ErrorCode.E803_TEST_DATA_INVALID,
                            message=f"Output type mismatch for '{output_name}' in case {case_id}: {type_error}",
                            phase="VALIDATE_TEST_DATA",
                            fqdn_id=fqdn_id,
                            artifact_code=artifact_code,
                            context=context,
                        )
                    )

        validated_count += 1

    if errors:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={"validated_test_data": validated_count},
            errors=tuple(errors),
        )
    else:
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={"validated_test_data": validated_count},
            errors=tuple(),
        )
