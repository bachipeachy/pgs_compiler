"""
Materialize phase: Write compiled JSON artifacts to disk.

Input: Validated artifacts (list[dict])
Output: PhaseResult with materialized paths (list[Path])

Output format (JSON):
{
    "fqdn_id": "namespace::artifact_code",
    "artifact_code": "CT_FOO_V0",
    "artifact_type": "CT",
    "namespace": "namespace",
    "version": "0",
    "frontmatter": {...},
    "content": "...",
    "ct_ir": {...} (for CT types)
}

Note: compiler-transient pipeline fields (source_path, etc.) are stripped before
materialization. See pgs_compiler.compiler.atoms.pipeline for the canonical registry.

Design:
- Write to {output_dir}/artifacts/{artifact_type_lower}/{encoded_fqdn}.json
- encoded_fqdn = fqdn_id.replace("::", "_")
- Create parent directories automatically
- Deterministic JSON (sorted keys, stable formatting)
- Atomic writes (write to temp, then rename)

Post-Materialization:
- Generate workflow graphs for all WF artifacts (best-effort)
- Store in {output_dir}/visualization/{wf_code}/
"""

import json
from pathlib import Path
from typing import Any

from pgs_governance.structure.structure.resolution import LayerResolver
from pgs_governance.structure.structure.loading.protocol_loader import _get_artifact_type_dir_from_prefix

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    PhaseResult,
    PhaseStatus,
    ensure_deterministic_output,
    sort_artifacts_by_fqdn,
    strip_transient_pipeline_fields,
)


def _normalize_binding(value: object) -> str | None:
    """
    Normalize a CC pipeline binding value for projection display.

    Accepts: scalar string refs under 80 chars.
    Rejects: dicts (inline specs), long strings, non-string values.
    Normalizes:
      $.results.CC_X.field  →  CC_X.field
      $.inputs.field        →  in.field
      other $.xxx           →  keep as-is
    Returns None if value should be omitted from display.
    """
    if not isinstance(value, str):
        return None
    if len(value) > 80:
        return None
    if value.startswith("$.results."):
        return value[len("$.results."):]
    if value.startswith("$.inputs."):
        return "in." + value[len("$.inputs."):]
    if value.startswith("$."):
        return value  # keep short refs verbatim
    return None  # literal/inline string — skip


def _extract_input_types(core_inputs: dict) -> dict[str, str]:
    """
    Extract input types from core.inputs spec.

    Args:
        core_inputs: The core.inputs dict from CT artifact

    Returns:
        Dict mapping input name → type string
    """
    input_types = {}
    if isinstance(core_inputs, dict):
        for key, spec in core_inputs.items():
            if isinstance(spec, dict) and "type" in spec:
                input_types[key] = spec["type"]
    return input_types


def _generate_workflow_graphs(
    validated_artifacts: list[dict[str, Any]],
    structure: dict | None,
    layer_output_map: dict[str, Path] | None,
    resolver: LayerResolver,
) -> list[str]:
    """
    Generate workflow graph artifacts (JSON, PNG, MD) for all WF artifacts.

    This runs AFTER materialization succeeds, as a best-effort post-process.
    Graph generation failures are logged as warnings, not errors.

    Args:
        validated_artifacts: All validated artifacts
        structure: STRUCTURE artifact (for output path resolution)
        layer_output_map: Legacy output map (backward compat)
        resolver: LayerResolver instance

    Returns:
        List of warning messages (empty if all graphs generated successfully)
    """
    warnings = []

    try:
        from pgs_compiler.compiler.visualization.wf_graph_generator import generate_workflow_graph
    except ImportError as e:
        warnings.append(f"Graph generation skipped: visualization module not available ({e})")
        return warnings

    # Collect WF and CC artifacts
    wf_artifacts = {}
    cc_artifacts = {}

    for artifact in validated_artifacts:
        artifact_type = artifact.get("artifact_type")
        if artifact_type == "WF":
            wf_code = artifact.get("frontmatter", {}).get("wf_code")
            if wf_code:
                wf_artifacts[wf_code] = artifact
        elif artifact_type == "CC":
            cc_code = artifact.get("frontmatter", {}).get("cc_code")
            if cc_code:
                cc_artifacts[cc_code] = artifact

    if not wf_artifacts:
        return warnings  # No workflows to process

    # Generate graphs for each workflow
    for wf_code, wf_artifact in wf_artifacts.items():
        try:
            # Resolve output path for this workflow's graphs using LayerResolver
            layer_code = wf_artifact.get("layer_code")
            domain_name = wf_artifact.get("domain_name")  # For DOMAINS layer artifacts

            if not layer_code:
                warnings.append(f"{wf_code}: Missing layer_code (required for output path resolution)")
                continue

            try:
                # Use resolver.resolve_output_path() (same as artifact materialization)
                if structure:
                    # STRUCTURE-driven: resolver handles domain-specific paths automatically
                    compiled_root = resolver.resolve_output_path(
                        "layer_outputs",
                        layer_code,
                        structure,
                        domain=domain_name  # Pass domain context (None for platform layers)
                    )
                    visualization_root = compiled_root.parent / "visualization"
                elif layer_output_map and layer_code in layer_output_map:
                    # dict-based fallback: layer_output_map provided directly
                    layer_output = layer_output_map[layer_code]
                    if layer_code == "DOMAINS" and domain_name:
                        visualization_root = layer_output / "domains" / domain_name / "compiled" / "visualization"
                    else:
                        visualization_root = layer_output / "visualization"
                else:
                    warnings.append(f"{wf_code}: Cannot resolve output path (no structure or layer_output_map)")
                    continue
            except Exception as e:
                warnings.append(f"{wf_code}: Failed to resolve visualization path: {e}")
                continue

            # Generate graph
            result = generate_workflow_graph(wf_artifact, cc_artifacts, visualization_root)

            if result["status"] == "FAILED":
                warnings.append(f"{wf_code}: Graph generation failed - {', '.join(result.get('errors', []))}")
            elif result["status"] == "PARTIAL":
                warnings.append(f"{wf_code}: Partial graph generation - {', '.join(result.get('errors', []))}")

        except Exception as e:
            warnings.append(f"{wf_code}: Unexpected error during graph generation - {e}")

    return warnings


def materialize_phase(
    validated_artifacts: list[dict[str, Any]],
    structure: dict | None = None,
    output_dir: Path | dict[str, Path] | None = None,
    indent: int = 2,
) -> PhaseResult:
    """
    Materialize validated artifacts as JSON files.

    STRUCTURE-DRIVEN: Uses structure configuration for output path resolution.

    Args:
        validated_artifacts: Output from validate_phase
        structure: STRUCTURE artifact dict (required for STRUCTURE-driven resolution)
        output_dir: DEPRECATED - Legacy output directory configuration (backward compat)
        indent: JSON indentation

    Returns:
        PhaseResult with materialized_paths

    Errors:
        E301_WRITE_FAILED: Failed to write file
        E302_JSON_SERIALIZE_FAILED: JSON serialization failed

    Governed By:
        INVARIANT_NO_UNDECLARED_BEHAVIOR_SURFACE_V0
        STRUCTURE_BUILD_PLATFORM_CONFIG_V0
    """
    errors: list[CompilerError] = []
    materialized_paths: list[str] = []

    # Initialize LayerResolver for STRUCTURE-driven path resolution
    resolver = LayerResolver()

    # Support dict-based output_dir for callers that supply layer_output_map directly
    layer_output_map: dict[str, Path] | None = None
    if isinstance(output_dir, dict):
        layer_output_map = output_dir
    elif structure is None and output_dir is None:
        raise RuntimeError(
            "materialize_phase requires either 'structure' parameter (preferred) "
            "or 'output_dir' parameter (deprecated). "
            "Pass STRUCTURE artifact for constitutional path resolution."
        )

    # Build CT index for atom input type lookup (compile-time resolution)
    ct_index: dict[str, dict] = {}
    for artifact in validated_artifacts:
        if artifact.get("artifact_type") == "CT":
            ct_index[artifact["artifact_code"]] = artifact

    # Build CS index for projection signature lookup (compile-time resolution)
    cs_index: dict[str, dict] = {}
    for artifact in validated_artifacts:
        if artifact.get("artifact_type") == "CS":
            cs_index[artifact["artifact_code"]] = artifact

    # Build code→fqdn index for WF node enrichment (compile-time resolution)
    code_to_fqdn: dict[str, str] = {
        a["artifact_code"]: a["fqdn_id"]
        for a in validated_artifacts
    }

    # Materialize each artifact
    for artifact in validated_artifacts:
        fqdn_id = artifact["fqdn_id"]
        artifact_code = artifact["artifact_code"]
        artifact_type = artifact["artifact_type"]
        layer_code = artifact.get("layer_code")

        # Skip TEST_DATA - used only for conformance generation, not materialized
        if artifact_type == "TEST_DATA":
            continue

        # Task 2: Build ct_ir field for CT artifacts
        if artifact_type == "CT":
            frontmatter = artifact.get("frontmatter", {})
            machine = frontmatter.get("machine", {})
            core = frontmatter.get("core", {})

            ct_kind = machine.get("ct_kind")
            if not ct_kind:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E201_VALIDATION_FAILED,
                        message=f"CT missing ct_kind in machine section",
                        phase="MATERIALIZE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                    )
                )
                continue

            # Build atom_stream and outputs based on ct_kind (deterministic transformation)
            atom_stream = []
            ct_ir_outputs = {}

            if ct_kind == "atom":
                # Transform: implementation → single-step atom_stream
                implementation = machine.get("implementation", {})
                if not implementation:
                    errors.append(
                        CompilerError(
                            code=ErrorCode.E205_CT_VALIDATION_FAILED,
                            message=f"Atom CT missing implementation",
                            phase="MATERIALIZE",
                            fqdn_id=fqdn_id,
                            artifact_code=artifact_code,
                        )
                    )
                    continue

                impl_module = implementation.get("module", "")
                impl_callable = implementation.get("callable", "")
                if not impl_module or not impl_callable:
                    errors.append(
                        CompilerError(
                            code=ErrorCode.E205_CT_VALIDATION_FAILED,
                            message=f"Atom CT implementation missing module or callable",
                            phase="MATERIALIZE",
                            fqdn_id=fqdn_id,
                            artifact_code=artifact_code,
                            context={"module": impl_module, "callable": impl_callable},
                        )
                    )
                    continue

                # Store result in a symbol
                result_symbol = "__atom_result__"
                atom_stream = [{
                    "atom": fqdn_id,  # Use fqdn_id (not artifact_code)
                    "handler_ref": {
                        "module": impl_module,
                        "callable": impl_callable,
                    },
                    "out": result_symbol,
                    "args": {
                        key: f"$.inputs.{key}"
                        for key in core.get("inputs", {}).keys()
                    }
                }]

                # Build outputs mapping - all outputs reference the result symbol
                # Atoms return a single dict containing all output fields
                if core.get("outputs"):
                    for output_name in core.get("outputs", {}).keys():
                        ct_ir_outputs[output_name] = {"from": result_symbol}

            elif ct_kind == "molecule":
                # Transform: steps → atom_stream (source format → executor format)
                steps = machine.get("steps", [])
                if not steps:
                    errors.append(
                        CompilerError(
                            code=ErrorCode.E201_VALIDATION_FAILED,
                            message=f"Molecule CT missing steps",
                            phase="MATERIALIZE",
                            fqdn_id=fqdn_id,
                            artifact_code=artifact_code,
                        )
                    )
                    continue

                atom_stream = []
                for step in steps:
                    step_kind = step.get("kind")

                    if step_kind == "atom":
                        # Transform: with → args, as → out
                        atom_code = step.get("atom")

                        # STRICT: Resolve atom via ct_index ONLY (no cross-package loading)
                        if atom_code not in ct_index:
                            errors.append(
                                CompilerError(
                                    code=ErrorCode.E201_VALIDATION_FAILED,
                                    message=f"Unresolved atom reference: {atom_code} (not in compile batch)",
                                    phase="MATERIALIZE",
                                    fqdn_id=fqdn_id,
                                    artifact_code=artifact_code,
                                    context={"referenced_atom": atom_code},
                                )
                            )
                            continue  # Skip this step, continue with next

                        atom_artifact = ct_index[atom_code]
                        atom_fqdn_id = atom_artifact["fqdn_id"]

                        transformed_step = {
                            "atom": atom_fqdn_id,  # Use fqdn_id (not artifact_code)
                            "out": step.get("as"),
                            "args": step.get("with", {})
                        }

                        # Embed handler_ref from atom's machine.implementation (compile-time binding)
                        atom_machine = atom_artifact.get("frontmatter", {}).get("machine", {})
                        atom_impl = atom_machine.get("implementation", {})
                        if not atom_impl or not atom_impl.get("module") or not atom_impl.get("callable"):
                            errors.append(
                                CompilerError(
                                    code=ErrorCode.E205_CT_VALIDATION_FAILED,
                                    message=f"Atom '{atom_code}' has no machine.implementation — cannot embed handler_ref",
                                    phase="MATERIALIZE",
                                    fqdn_id=fqdn_id,
                                    artifact_code=artifact_code,
                                    context={"referenced_atom": atom_code, "atom_fqdn": atom_fqdn_id},
                                )
                            )
                            continue
                        transformed_step["handler_ref"] = {
                            "module": atom_impl["module"],
                            "callable": atom_impl["callable"],
                        }

                        # Embed atom's input types (compile-time resolution)
                        # ALWAYS embed input_types (even if empty) to ensure IR self-sufficiency
                        atom_core = atom_artifact.get("frontmatter", {}).get("core", {})
                        atom_input_types = _extract_input_types(atom_core.get("inputs", {}))
                        transformed_step["input_types"] = atom_input_types

                        atom_stream.append(transformed_step)

                    elif step_kind == "molecule":
                        # Transform: molecule step → atom with fqdn
                        molecule_code = step.get("molecule")

                        # STRICT: Resolve molecule via ct_index ONLY (no cross-package loading)
                        if molecule_code not in ct_index:
                            errors.append(
                                CompilerError(
                                    code=ErrorCode.E201_VALIDATION_FAILED,
                                    message=f"Unresolved molecule reference: {molecule_code} (not in compile batch)",
                                    phase="MATERIALIZE",
                                    fqdn_id=fqdn_id,
                                    artifact_code=artifact_code,
                                    context={"referenced_molecule": molecule_code},
                                )
                            )
                            continue  # Skip this step, continue with next

                        molecule_artifact = ct_index[molecule_code]
                        molecule_fqdn_id = molecule_artifact["fqdn_id"]

                        transformed_step = {
                            "atom": molecule_fqdn_id,  # Use fqdn_id (not artifact_code)
                            "out": step.get("as"),
                            "args": step.get("with", {})
                        }

                        # Embed molecule's input types (compile-time resolution)
                        # ALWAYS embed input_types (even if empty) to ensure IR self-sufficiency
                        molecule_core = molecule_artifact.get("frontmatter", {}).get("core", {})
                        molecule_input_types = _extract_input_types(molecule_core.get("inputs", {}))
                        transformed_step["input_types"] = molecule_input_types

                        atom_stream.append(transformed_step)

                    elif step_kind == "loop":
                        # Transform: flat loop → nested loop structure
                        molecule_code = step.get("molecule")

                        # STRICT: Resolve molecule via ct_index ONLY (no cross-package loading)
                        if molecule_code not in ct_index:
                            errors.append(
                                CompilerError(
                                    code=ErrorCode.E201_VALIDATION_FAILED,
                                    message=f"Unresolved molecule reference: {molecule_code} (not in compile batch)",
                                    phase="MATERIALIZE",
                                    fqdn_id=fqdn_id,
                                    artifact_code=artifact_code,
                                    context={"referenced_molecule": molecule_code},
                                )
                            )
                            continue  # Skip this step, continue with next

                        molecule_artifact = ct_index[molecule_code]
                        molecule_fqdn_id = molecule_artifact["fqdn_id"]

                        loop_spec = {
                            "over": step.get("over"),
                            "iterator": step.get("iterator"),
                            "accumulator": step.get("accumulator", {}),
                            "inputs": step.get("inputs", {}),
                            "update_accumulator": step.get("update_accumulator", {})
                        }
                        transformed_step = {
                            "atom": molecule_fqdn_id,  # Use fqdn_id (not molecule_code)
                            "out": step.get("as"),
                            "loop": loop_spec
                        }

                        # Embed molecule's input types (compile-time resolution)
                        # ALWAYS embed input_types (even if empty) to ensure IR self-sufficiency
                        molecule_core = molecule_artifact.get("frontmatter", {}).get("core", {})
                        molecule_input_types = _extract_input_types(molecule_core.get("inputs", {}))
                        transformed_step["input_types"] = molecule_input_types

                        atom_stream.append(transformed_step)

                    else:
                        # Unknown step kind - preserve as-is for now
                        atom_stream.append(step)

                # Transform emit → outputs with "from" mappings
                emit_config = machine.get("emit", {})
                for output_name, from_symbol in emit_config.items():
                    ct_ir_outputs[output_name] = {"from": from_symbol}

                # ASSERTION: All steps MUST have input_types (fail fast on IR contract violation)
                for idx, step in enumerate(atom_stream):
                    if "input_types" not in step:
                        errors.append(
                            CompilerError(
                                code=ErrorCode.E201_VALIDATION_FAILED,
                                message=f"IR contract violation: step {idx} missing input_types",
                                phase="MATERIALIZE",
                                fqdn_id=fqdn_id,
                                artifact_code=artifact_code,
                                context={"step_index": idx, "step_atom": step.get("atom")},
                            )
                        )

            else:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E201_VALIDATION_FAILED,
                        message=f"Unknown ct_kind: {ct_kind}",
                        phase="MATERIALIZE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                    )
                )
                continue

            artifact["ct_ir"] = {
                "ct_code": artifact_code,  # Human-readable label
                "ct_fqdn": fqdn_id,  # Canonical identity (system)
                "atom_stream": atom_stream,
                "ct_composition_version": "V0",
                "inputs": core.get("inputs", {}),
                "outputs": ct_ir_outputs,
            }

        # Build cs_ir field for CS artifacts
        if artifact_type == "CS":
            frontmatter = artifact.get("frontmatter", {})
            implementation = frontmatter.get("implementation")

            if not implementation or not implementation.get("module") or not implementation.get("callable"):
                errors.append(
                    CompilerError(
                        code=ErrorCode.E205_CT_VALIDATION_FAILED,
                        message="CS missing implementation — cannot emit cs_ir",
                        phase="MATERIALIZE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                    )
                )
                continue

            core = frontmatter.get("core", {})
            policy_ops = core.get("policy", {}).get("operations", [])
            operations = core.get("operations", {})

            artifact["cs_ir"] = {
                "handler_ref": {
                    "module": implementation["module"],
                    "callable": implementation["callable"],
                },
                "cs_metadata": {
                    "capability": {
                        "supported_operation_specs": list(policy_ops),
                    },
                    "operations": {
                        "operations": operations,
                    },
                },
            }

        # Build cc_projection for CC artifacts (compile-time CT/CS extraction from pipeline)
        # Granularity: CT/CS artifact boundary only — never expose internal atom steps
        if artifact_type == "CC":
            frontmatter = artifact.get("frontmatter", {})
            core = frontmatter.get("core", {})
            pipeline = core.get("pipeline", [])

            _MAX_SIG = 5   # max inputs/outputs shown per node
            _MAX_BIND = 5  # max bindings shown per node

            steps: list[dict] = []
            seen_fqdns: set[str] = set()

            for step in pipeline:
                t = step.get("transform")
                s = step.get("side_effect")
                fqdn = t or s
                if not fqdn or fqdn in seen_fqdns:
                    continue
                seen_fqdns.add(fqdn)

                code = fqdn.split("::")[-1] if "::" in fqdn else fqdn
                kind = "CT" if t else "CS"

                # Extract input/output signature from declared artifact core
                if kind == "CT":
                    ref_art = ct_index.get(code, {})
                    ref_core = ref_art.get("frontmatter", {}).get("core", {})
                    inputs_sig = list(ref_core.get("inputs", {}).keys())
                    outputs_sig = list(ref_core.get("outputs", {}).keys())

                    # Extract bindings from CC pipeline step (CT input params → source refs)
                    raw_bindings = step.get("inputs", {})
                    bindings: dict[str, str] = {}
                    for k, v in raw_bindings.items():
                        normalized = _normalize_binding(v)
                        if normalized is not None:
                            bindings[k] = normalized
                        if len(bindings) >= _MAX_BIND:
                            break

                    entry: dict = {
                        "id": code,
                        "fqdn": fqdn,
                        "kind": "CT",
                        "inputs": inputs_sig[:_MAX_SIG],
                        "outputs": outputs_sig[:_MAX_SIG],
                        "bindings": bindings,
                    }
                    if len(inputs_sig) > _MAX_SIG:
                        entry["inputs_truncated"] = True
                    if len(outputs_sig) > _MAX_SIG:
                        entry["outputs_truncated"] = True

                else:  # CS
                    ref_art = cs_index.get(code, {})
                    ref_core = ref_art.get("frontmatter", {}).get("core", {})
                    policy_ops = ref_core.get("policy", {}).get("operations", [])
                    ops_sig = list(policy_ops) if isinstance(policy_ops, list) else list(policy_ops.keys())

                    entry = {
                        "id": code,
                        "fqdn": fqdn,
                        "kind": "CS",
                        "ops": ops_sig[:_MAX_SIG],
                        "outputs": ["result_status"],
                    }
                    if len(ops_sig) > _MAX_SIG:
                        entry["ops_truncated"] = True

                steps.append(entry)

            artifact["cc_projection"] = {"steps": steps}

        # Enrich WF nodes with fqdn_id (compile-time resolution, no runtime inference)
        if artifact_type == "WF":
            wf_frontmatter = artifact.get("frontmatter", {})
            wf_nodes = wf_frontmatter.get("core", {}).get("nodes", {})
            for node_key, node in wf_nodes.items():
                node_type = node.get("type")
                if node_type in ("CC", "IN"):
                    ref_code = node.get("code") or node.get("fqdn_id")
                    if not ref_code:
                        # Anonymous entry node (IN with no code) — no artifact to resolve
                        continue
                    if "::" in ref_code:
                        # Already a FQDN — trust it directly
                        node["fqdn_id"] = ref_code
                    elif ref_code in code_to_fqdn:
                        node["fqdn_id"] = code_to_fqdn[ref_code]
                    else:
                        errors.append(
                            CompilerError(
                                code=ErrorCode.E201_MISSING_REFERENCE,
                                message=f"WF node '{node_key}' references '{ref_code}' which has no matching artifact in compile batch",
                                phase="MATERIALIZE",
                                fqdn_id=fqdn_id,
                                artifact_code=artifact_code,
                                context={"node_key": node_key, "ref_code": ref_code},
                            )
                        )

        # Resolve output directory for this artifact
        if structure:
            # STRUCTURE-driven resolution (constitutional)
            if not layer_code:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E301_WRITE_FAILED,
                        message=f"Artifact missing layer_code (required for STRUCTURE-driven output)",
                        phase="MATERIALIZE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                    )
                )
                continue

            try:
                # Extract domain context from discovery (if present)
                domain_name = artifact.get("domain_name")

                # Use LayerResolver.resolve_output_path() with STRUCTURE
                artifact_output_dir = resolver.resolve_output_path(
                    "layer_outputs",
                    layer_code,
                    structure,
                    domain=domain_name  # Pass domain context to LayerResolver
                )
            except RuntimeError as e:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E301_WRITE_FAILED,
                        message=f"Failed to resolve output path from STRUCTURE: {e}",
                        phase="MATERIALIZE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"layer_code": layer_code, "error": str(e)},
                    )
                )
                continue
        elif layer_output_map:
            # dict-based path resolution
            if not layer_code:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E301_WRITE_FAILED,
                        message=f"Artifact missing layer_code (required for layer-specific output)",
                        phase="MATERIALIZE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                    )
                )
                continue

            layer_compiled_root = layer_output_map.get(layer_code)
            if not layer_compiled_root:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E301_WRITE_FAILED,
                        message=f"No output directory configured for layer: {layer_code}",
                        phase="MATERIALIZE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        context={"layer_code": layer_code},
                    )
                )
                continue
            artifact_output_dir = layer_compiled_root / "artifacts"
        else:
            # Single output_dir mode (simple case)
            artifact_output_dir = output_dir / "artifacts"

        # Build output path
        encoded_fqdn = fqdn_id.replace("::", "__")
        type_dir_name = _get_artifact_type_dir_from_prefix(artifact_type)
        type_dir = artifact_output_dir / type_dir_name
        output_path = type_dir / f"{encoded_fqdn}.json"

        # Create type directory
        try:
            type_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(
                CompilerError(
                    code=ErrorCode.E301_WRITE_FAILED,
                    message=f"Failed to create type directory: {e}",
                    phase="MATERIALIZE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"type_dir": str(type_dir), "error": str(e)},
                )
            )
            continue

        # Prepare output: strip compiler-transient pipeline fields, then order deterministically.
        # Transient fields (source_path, etc.) are compiler-operational state that must never
        # cross the materialization boundary into compiled artifacts or snapshots.
        # See: pgs_compiler.compiler.atoms.pipeline for the canonical transient field registry.
        output_data = ensure_deterministic_output(strip_transient_pipeline_fields(artifact))

        # Serialize to JSON
        try:
            json_content = json.dumps(output_data, indent=indent, sort_keys=True)
        except Exception as e:
            errors.append(
                CompilerError(
                    code=ErrorCode.E302_JSON_SERIALIZE_FAILED,
                    message=f"JSON serialization failed: {e}",
                    phase="MATERIALIZE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"error": str(e)},
                )
            )
            continue

        # Write to disk (atomic)
        try:
            temp_path = output_path.with_suffix(".tmp")
            temp_path.write_text(json_content, encoding="utf-8")
            temp_path.replace(output_path)
            materialized_paths.append(str(output_path))
        except Exception as e:
            errors.append(
                CompilerError(
                    code=ErrorCode.E301_WRITE_FAILED,
                    message=f"Failed to write file: {e}",
                    phase="MATERIALIZE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    context={"output_path": str(output_path), "error": str(e)},
                )
            )
            continue

    materialized_paths_sorted = sorted(materialized_paths)

    # Post-materialization: Generate workflow graphs (best-effort)
    graph_warnings = _generate_workflow_graphs(
        validated_artifacts=validated_artifacts,
        structure=structure,
        layer_output_map=layer_output_map,
        resolver=resolver,
    )

    # Build result
    if errors:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={
                "materialized_paths": materialized_paths_sorted,
                "graph_warnings": graph_warnings,
            },
            errors=tuple(errors),
        )
    else:
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={
                "materialized_paths": materialized_paths_sorted,
                "graph_warnings": graph_warnings,
            },
            errors=tuple(),
        )
