"""
Validate phase: Check references, cycles, schemas, RB bindings.

Input: Parsed artifacts (list[dict])
Output: PhaseResult with validated artifacts (list[dict])

Validates exactly 5 invariants (bounded validation):
1. References exist (all referenced FQDNs are in artifact set)
2. No circular dependencies (dependency graph is acyclic)
3. Schema valid (Pydantic validation passes)
4. RB bindings valid (RB artifacts reference valid CS artifacts)
5. CT validation (CT-IR host shape and category invariants)

Design:
- Bounded validation
- Reference extraction from frontmatter fields
- Topological sort for cycle detection
- JSON Schema validation against FB_CONSTITUTION declared schemas
"""

from typing import Any

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    PhaseResult,
    PhaseStatus,
    require,
    sort_artifacts_by_fqdn,
)
from pgs_compiler.compiler.validators.ct_validator import validate_ct_ir


def validate_phase(
    parsed_artifacts: list[dict[str, Any]],
    validate_schemas: bool = True,
) -> PhaseResult:
    """
    Validate parsed artifacts (5 bounded invariants).

    Args:
        parsed_artifacts: Output from parse_phase
        validate_schemas: Enable JSON Schema validation against FB_CONSTITUTION declared schemas

    Returns:
        PhaseResult with validated artifacts (sorted by FQDN)

    Errors:
        E201_MISSING_REFERENCE: Referenced FQDN not found
        E202_CIRCULAR_DEPENDENCY: Circular dependency detected
        E203_SCHEMA_INVALID: Schema validation failed
        E204_INVALID_RB_BINDING: RB references invalid CS
        E205_CT_VALIDATION_FAILED: CT-IR validation failed
    """
    errors: list[CompilerError] = []

    # Build FQDN index for reference checking
    fqdn_index: dict[str, dict[str, Any]] = {
        artifact["fqdn_id"]: artifact for artifact in parsed_artifacts
    }

    # Use pre-computed references from parse phase (already normalized to FQDN)
    all_references: dict[str, set[str]] = {}  # fqdn_id -> set of referenced fqdn_ids

    for artifact in parsed_artifacts:
        fqdn_id = artifact["fqdn_id"]
        references = set(artifact.get("references", []))
        all_references[fqdn_id] = references

    # Invariant 1: References exist
    for fqdn_id, references in all_references.items():
        artifact = fqdn_index[fqdn_id]
        artifact_code = artifact["artifact_code"]

        for ref_fqdn in references:
            if ref_fqdn not in fqdn_index:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E201_MISSING_REFERENCE,
                        message=f"Reference not found: {ref_fqdn}",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={
                            "missing_reference": ref_fqdn,
                            "referenced_from": fqdn_id,
                        },
                    )
                )

    # Invariant 2: No circular dependencies
    cycle_errors = _detect_cycles(all_references, fqdn_index)
    errors.extend(cycle_errors)

    # Invariant 3: Schema validation (Pydantic)
    if validate_schemas:
        schema_errors = _validate_schemas(parsed_artifacts)
        errors.extend(schema_errors)

    # Invariant 4: RB bindings valid (RB references CS artifacts)
    rb_errors = _validate_rb_bindings(parsed_artifacts, fqdn_index)
    errors.extend(rb_errors)

    # Invariant 5: CT Validation (New)
    ct_errors = _validate_ct_artifacts(parsed_artifacts)
    errors.extend(ct_errors)

    # Invariant 6: CS Implementation Validation
    cs_errors = _validate_cs_artifacts(parsed_artifacts)
    errors.extend(cs_errors)

    # Sort artifacts by FQDN (deterministic ordering - Patch E)
    validated_artifacts = sort_artifacts_by_fqdn(parsed_artifacts)

    # Build result
    if errors:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={"validated_artifacts": validated_artifacts},
            errors=tuple(errors),
        )
    else:
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={"validated_artifacts": validated_artifacts},
            errors=tuple(),
        )


def _detect_cycles(
    references: dict[str, set[str]],
    fqdn_index: dict[str, dict[str, Any]],
) -> list[CompilerError]:
    """Detect circular dependencies using DFS."""
    errors: list[CompilerError] = []
    visited: set[str] = set()
    path: list[str] = []

    def visit(fqdn_id: str) -> None:
        if fqdn_id in path:
            cycle_start = path.index(fqdn_id)
            cycle = path[cycle_start:] + [fqdn_id]
            artifact = fqdn_index[fqdn_id]

            errors.append(
                CompilerError(
                    code=ErrorCode.E202_CIRCULAR_DEPENDENCY,
                    message=f"Circular dependency: {' → '.join(cycle)}",
                    phase="VALIDATE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact["artifact_code"],
                    context={"cycle": cycle},
                )
            )
            return

        if fqdn_id in visited:
            return

        visited.add(fqdn_id)
        path.append(fqdn_id)

        for dep_fqdn in references.get(fqdn_id, set()):
            if dep_fqdn in fqdn_index:
                visit(dep_fqdn)

        path.pop()

    for fqdn_id in references.keys():
        if fqdn_id not in visited:
            visit(fqdn_id)

    return errors


def _validate_schemas(parsed_artifacts: list[dict[str, Any]]) -> list[CompilerError]:
    """Validate artifact frontmatter against JSON schemas declared in FB_CONSTITUTION."""
    import json
    from pathlib import Path

    import pgs_governance
    from jsonschema import Draft202012Validator

    errors: list[CompilerError] = []

    schema_dir = Path(pgs_governance.__file__).parent / "registry" / "FB_CONSTITUTION" / "schemas"

    schema_file_map = {
        "CT": "SCHEMA_CAPABILITY_TRANSFORM_V0.json",
        "CS": "SCHEMA_CAPABILITY_SIDE_EFFECT_V0.json",
        "CC": "SCHEMA_CAPABILITY_CONTRACT_V0.json",
        "WF": "SCHEMA_WORKFLOW_V0.json",
        "RB": "SCHEMA_RUNTIME_BINDING_V0.json",
    }

    # Load and cache schemas once
    loaded_schemas: dict[str, Any] = {}
    for art_type, schema_file in schema_file_map.items():
        schema_path = schema_dir / schema_file
        if schema_path.exists():
            with open(schema_path) as f:
                loaded_schemas[art_type] = json.load(f)

    for artifact in parsed_artifacts:
        artifact_type = artifact.get("artifact_type")
        schema = loaded_schemas.get(artifact_type)
        if schema is None:
            continue

        frontmatter = artifact.get("frontmatter", {})
        validator = Draft202012Validator(schema)

        for error in validator.iter_errors(frontmatter):
            errors.append(
                CompilerError(
                    code=ErrorCode.E203_SCHEMA_INVALID,
                    message=f"Schema violation at {error.json_path}: {error.message}",
                    phase="VALIDATE",
                    fqdn_id=artifact["fqdn_id"],
                    artifact_code=artifact["artifact_code"],
                    context={
                        "schema": schema_file_map[artifact_type],
                        "json_path": error.json_path,
                        "validator": error.validator,
                    },
                )
            )

    return errors


def _validate_rb_bindings(
    parsed_artifacts: list[dict[str, Any]],
    fqdn_index: dict[str, dict[str, Any]],
) -> list[CompilerError]:
    """Validate RB bindings reference valid CS artifacts only (side-effects, not computation)."""
    errors: list[CompilerError] = []

    for artifact in parsed_artifacts:
        if artifact["artifact_type"] != "RB":
            continue

        fqdn_id = artifact["fqdn_id"]
        artifact_code = artifact["artifact_code"]
        frontmatter = artifact["frontmatter"]
        core = frontmatter.get("core", {})
        bindings = core.get("bindings", {})
        normalized_references = set(artifact.get("references", []))

        for binding_key in bindings.keys():
            # CONSTITUTIONAL: RB bindings must use FQDN keys (INVARIANT_FQDN_ONLY_REFERENCES_V0)
            # Binding key IS the FQDN (e.g., "capability_side_effects::CS_REGISTRY_V0")
            if "::" not in binding_key:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E204_INVALID_RB_BINDING,
                        message=f"RB binding key must be FQDN: {binding_key}",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"bare_code": binding_key, "rb_artifact": fqdn_id},
                    )
                )
                continue

            cs_fqdn = binding_key

            if cs_fqdn not in normalized_references:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E204_INVALID_RB_BINDING,
                        message=f"RB binding not found in normalized references: {cs_fqdn}",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"cs_fqdn": cs_fqdn, "rb_artifact": fqdn_id},
                    )
                )
                continue

            if cs_fqdn not in fqdn_index:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E204_INVALID_RB_BINDING,
                        message=f"RB references non-existent CS: {cs_fqdn}",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"cs_reference": cs_fqdn, "rb_artifact": fqdn_id},
                    )
                )
                continue

            cs_artifact = fqdn_index[cs_fqdn]
            if cs_artifact["artifact_type"] != "CS":
                errors.append(
                    CompilerError(
                        code=ErrorCode.E204_INVALID_RB_BINDING,
                        message=f"RB references non-CS artifact: {cs_fqdn} (type={cs_artifact['artifact_type']})",
                        phase="VALIDATE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={
                            "cs_reference": cs_fqdn,
                            "actual_type": cs_artifact["artifact_type"],
                            "expected_type": "CS",
                        },
                    )
                )

    return errors


def _validate_ct_artifacts(parsed_artifacts: list[dict[str, Any]]) -> list[CompilerError]:
    """Add CT validation during validate phase."""
    errors: list[CompilerError] = []

    for artifact in parsed_artifacts:
        if artifact["artifact_type"] == "CT":
            frontmatter = artifact.get("frontmatter", {})
            machine = frontmatter.get("machine", {})
            ct_kind = machine.get("ct_kind")

            # ASSERT_CT_IMPLEMENTATION_VALID_V0
            # Every atom CT MUST declare machine.implementation with non-empty module and callable.
            # Structural check only — no import, no runtime coupling.
            if ct_kind == "atom":
                implementation = machine.get("implementation")
                if not implementation:
                    errors.append(
                        CompilerError(
                            code=ErrorCode.E205_CT_VALIDATION_FAILED,
                            message="ASSERT_CT_IMPLEMENTATION_VALID_V0: atom CT missing machine.implementation",
                            phase="VALIDATE",
                            fqdn_id=artifact["fqdn_id"],
                            artifact_code=artifact["artifact_code"],
                        )
                    )
                else:
                    module_val = implementation.get("module", "")
                    callable_val = implementation.get("callable", "")
                    if not isinstance(module_val, str) or not module_val.strip():
                        errors.append(
                            CompilerError(
                                code=ErrorCode.E205_CT_VALIDATION_FAILED,
                                message="ASSERT_CT_IMPLEMENTATION_VALID_V0: machine.implementation.module is missing or empty",
                                phase="VALIDATE",
                                fqdn_id=artifact["fqdn_id"],
                                artifact_code=artifact["artifact_code"],
                            )
                        )
                    if not isinstance(callable_val, str) or not callable_val.strip():
                        errors.append(
                            CompilerError(
                                code=ErrorCode.E205_CT_VALIDATION_FAILED,
                                message="ASSERT_CT_IMPLEMENTATION_VALID_V0: machine.implementation.callable is missing or empty",
                                phase="VALIDATE",
                                fqdn_id=artifact["fqdn_id"],
                                artifact_code=artifact["artifact_code"],
                            )
                        )

            # CT-IR candidate validation (existing)
            ct_ir_candidate = machine
            try:
                validate_ct_ir({
                    "ct_code": artifact["artifact_code"],
                    "atom_stream": ct_ir_candidate.get("atom_stream", []),
                    "ct_composition_version": "V0",
                    "inputs": ct_ir_candidate.get("inputs", {}),
                    "outputs": ct_ir_candidate.get("outputs", {}),
                })
            except Exception as e:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E205_CT_VALIDATION_FAILED,
                        message=str(e),
                        phase="VALIDATE",
                        fqdn_id=artifact["fqdn_id"],
                        artifact_code=artifact["artifact_code"],
                        context={"error": str(e)}
                    )
                )

    return errors


def _validate_cs_artifacts(parsed_artifacts: list[dict[str, Any]]) -> list[CompilerError]:
    """Validate CS artifacts have machine.implementation declared."""
    errors: list[CompilerError] = []

    for artifact in parsed_artifacts:
        if artifact["artifact_type"] != "CS":
            continue

        frontmatter = artifact.get("frontmatter", {})
        implementation = frontmatter.get("implementation")

        # ASSERT_CS_IMPLEMENTATION_VALID_V0
        # Every CS MUST declare implementation with non-empty module and callable.
        # Structural check only — no import, no runtime coupling.
        if not implementation:
            errors.append(
                CompilerError(
                    code=ErrorCode.E205_CT_VALIDATION_FAILED,
                    message="ASSERT_CS_IMPLEMENTATION_VALID_V0: CS missing implementation",
                    phase="VALIDATE",
                    fqdn_id=artifact["fqdn_id"],
                    artifact_code=artifact["artifact_code"],
                )
            )
        else:
            module_val = implementation.get("module", "")
            callable_val = implementation.get("callable", "")
            if not isinstance(module_val, str) or not module_val.strip():
                errors.append(
                    CompilerError(
                        code=ErrorCode.E205_CT_VALIDATION_FAILED,
                        message="ASSERT_CS_IMPLEMENTATION_VALID_V0: implementation.module is missing or empty",
                        phase="VALIDATE",
                        fqdn_id=artifact["fqdn_id"],
                        artifact_code=artifact["artifact_code"],
                    )
                )
            if not isinstance(callable_val, str) or not callable_val.strip():
                errors.append(
                    CompilerError(
                        code=ErrorCode.E205_CT_VALIDATION_FAILED,
                        message="ASSERT_CS_IMPLEMENTATION_VALID_V0: implementation.callable is missing or empty",
                        phase="VALIDATE",
                        fqdn_id=artifact["fqdn_id"],
                        artifact_code=artifact["artifact_code"],
                    )
                )

    return errors
