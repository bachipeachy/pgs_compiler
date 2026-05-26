"""
S5 CONSTRUCT — Build intermediate representations on graph nodes.

Input: State from S4 (governed graph)
Output: State with IR populated on CT, CS, and CC nodes

Builds:
- CT nodes: ct_ir (atom_stream, inputs, outputs, handler_refs)
- CS nodes: cs_ir (handler_ref, operations metadata)
- CC nodes: cc_projection (pipeline step signatures)
- WF nodes: enriched node fqdn_ids
"""

from typing import Any

from pgs_compiler.compiler.graph.types import NodeKind
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.graph import Graph, GraphBuilder
from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.compiler.atoms.error_codes import ErrorCode

from types import MappingProxyType


def s5_construct(state: State) -> State:
    """
    S5 CONSTRUCT: Build IR on CT, CS, CC, and WF nodes.

    Pure function: State → State.
    """
    state = state.with_stage("S5_CONSTRUCT")
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []
    graph = state.graph

    builder = GraphBuilder.from_graph(graph)

    # Build indices for cross-node lookups
    ct_index: dict[str, Node] = {}  # artifact_code → node
    cs_index: dict[str, Node] = {}
    code_to_fqdn: dict[str, str] = {}

    for node in graph.nodes.values():
        code_to_fqdn[node.artifact_code] = node.fqdn
        if node.kind == NodeKind.CT:
            ct_index[node.artifact_code] = node
        elif node.kind == NodeKind.CS:
            cs_index[node.artifact_code] = node

    # --- Build CT-IR ---
    for fqdn, node in graph.nodes.items():
        if node.kind != NodeKind.CT:
            continue

        ct_ir, ct_errors = _build_ct_ir(node, ct_index)
        errors.extend(ct_errors)

        if ct_ir is not None:
            builder.replace_node(fqdn, ir=MappingProxyType(ct_ir))
            trace.append(TraceEvent.create(
                stage="S5_CONSTRUCT",
                operation="ct_ir_built",
                subject_fqdn=fqdn,
                detail={"atom_stream_length": len(ct_ir.get("atom_stream", []))},
                family=EventFamily.CONSTRUCTION.value,
            ))

    # --- Build CS-IR ---
    for fqdn, node in graph.nodes.items():
        if node.kind != NodeKind.CS:
            continue

        cs_ir, cs_errors = _build_cs_ir(node)
        errors.extend(cs_errors)

        if cs_ir is not None:
            builder.replace_node(fqdn, ir=MappingProxyType(cs_ir))
            trace.append(TraceEvent.create(
                stage="S5_CONSTRUCT",
                operation="cs_ir_built",
                subject_fqdn=fqdn,
                family=EventFamily.CONSTRUCTION.value,
            ))

    # --- Build CC projection ---
    for fqdn, node in graph.nodes.items():
        if node.kind != NodeKind.CC:
            continue

        cc_proj, cc_errors = _build_cc_projection(node, ct_index, cs_index)
        errors.extend(cc_errors)

        if cc_proj is not None:
            builder.replace_node(fqdn, ir=MappingProxyType(cc_proj))
            trace.append(TraceEvent.create(
                stage="S5_CONSTRUCT",
                operation="cc_projection_built",
                subject_fqdn=fqdn,
                detail={"pipeline_steps": len(cc_proj.get("cc_projection", {}).get("steps", []))},
                family=EventFamily.CONSTRUCTION.value,
            ))

    # --- Enrich WF nodes ---
    for fqdn, node in graph.nodes.items():
        if node.kind != NodeKind.WF:
            continue

        wf_errors = _enrich_wf_nodes(node, code_to_fqdn, builder)
        errors.extend(wf_errors)

    if errors:
        state = state.with_errors(*errors)

    new_graph = builder.build()
    state = state.with_graph(new_graph)

    ir_count = sum(1 for n in new_graph.nodes.values() if n.ir is not None)
    state = state.with_metadata("ir_count", ir_count)

    trace.append(TraceEvent.create(
        stage="S5_CONSTRUCT",
        operation="construction_complete",
        detail={"ir_count": ir_count},
        family=EventFamily.CONSTRUCTION.value,
    ))
    if trace:
        state = state.with_trace_events(*trace)

    return state


def _build_ct_ir(
    node: Node, ct_index: dict[str, Node],
) -> tuple[dict[str, Any] | None, list[CompilerError]]:
    """Build CT-IR for a CT node."""
    errors: list[CompilerError] = []
    machine = node.frontmatter.get("machine", {})
    core = node.frontmatter.get("core", {})

    if not isinstance(machine, dict):
        return None, errors

    ct_kind = machine.get("ct_kind")
    if not ct_kind:
        errors.append(CompilerError(
            code=ErrorCode.E205_CT_VALIDATION_FAILED,
            message="CT missing ct_kind in machine section",
            phase="S5_CONSTRUCT",
            fqdn_id=node.fqdn,
        ))
        return None, errors

    atom_stream: list[dict] = []
    ct_ir_outputs: dict[str, Any] = {}

    if ct_kind == "atom":
        implementation = machine.get("implementation", {})
        if not implementation:
            errors.append(CompilerError(
                code=ErrorCode.E205_CT_VALIDATION_FAILED,
                message="Atom CT missing implementation",
                phase="S5_CONSTRUCT",
                fqdn_id=node.fqdn,
            ))
            return None, errors

        impl_module = implementation.get("module", "")
        impl_callable = implementation.get("callable", "")
        if not impl_module or not impl_callable:
            errors.append(CompilerError(
                code=ErrorCode.E205_CT_VALIDATION_FAILED,
                message="Atom CT implementation missing module or callable",
                phase="S5_CONSTRUCT",
                fqdn_id=node.fqdn,
            ))
            return None, errors

        result_symbol = "__atom_result__"
        atom_stream = [{
            "atom": node.fqdn,
            "handler_ref": {
                "module": impl_module,
                "callable": impl_callable,
            },
            "out": result_symbol,
            "args": {
                key: f"$.inputs.{key}"
                for key in (core.get("inputs", {}) if isinstance(core, dict) else {}).keys()
            },
        }]

        core_outputs = core.get("outputs", {}) if isinstance(core, dict) else {}
        for output_name in core_outputs.keys():
            ct_ir_outputs[output_name] = {"from": result_symbol}

    elif ct_kind == "molecule":
        steps = machine.get("steps", [])
        if not steps:
            errors.append(CompilerError(
                code=ErrorCode.E205_CT_VALIDATION_FAILED,
                message="Molecule CT missing steps",
                phase="S5_CONSTRUCT",
                fqdn_id=node.fqdn,
            ))
            return None, errors

        for step in steps:
            step_kind = step.get("kind")

            if step_kind == "atom":
                atom_code = step.get("atom")
                atom_node = ct_index.get(atom_code)
                if not atom_node:
                    errors.append(CompilerError(
                        code=ErrorCode.E201_MISSING_REFERENCE,
                        message=f"Unresolved atom reference: {atom_code}",
                        phase="S5_CONSTRUCT",
                        fqdn_id=node.fqdn,
                    ))
                    continue

                atom_machine = atom_node.frontmatter.get("machine", {})
                atom_impl = atom_machine.get("implementation", {}) if isinstance(atom_machine, dict) else {}
                atom_core = atom_node.frontmatter.get("core", {})

                if not atom_impl.get("module") or not atom_impl.get("callable"):
                    errors.append(CompilerError(
                        code=ErrorCode.E205_CT_VALIDATION_FAILED,
                        message=f"Atom '{atom_code}' has no implementation — cannot embed handler_ref",
                        phase="S5_CONSTRUCT",
                        fqdn_id=node.fqdn,
                    ))
                    continue

                transformed = {
                    "atom": atom_node.fqdn,
                    "out": step.get("as"),
                    "args": step.get("with", {}),
                    "handler_ref": {
                        "module": atom_impl["module"],
                        "callable": atom_impl["callable"],
                    },
                    "input_types": _extract_input_types(
                        atom_core.get("inputs", {}) if isinstance(atom_core, dict) else {}
                    ),
                }
                atom_stream.append(transformed)

            elif step_kind == "molecule":
                mol_code = step.get("molecule")
                mol_node = ct_index.get(mol_code)
                if not mol_node:
                    errors.append(CompilerError(
                        code=ErrorCode.E201_MISSING_REFERENCE,
                        message=f"Unresolved molecule reference: {mol_code}",
                        phase="S5_CONSTRUCT",
                        fqdn_id=node.fqdn,
                    ))
                    continue

                mol_core = mol_node.frontmatter.get("core", {})
                transformed = {
                    "atom": mol_node.fqdn,
                    "out": step.get("as"),
                    "args": step.get("with", {}),
                    "input_types": _extract_input_types(
                        mol_core.get("inputs", {}) if isinstance(mol_core, dict) else {}
                    ),
                }
                atom_stream.append(transformed)

            elif step_kind == "loop":
                mol_code = step.get("molecule")
                mol_node = ct_index.get(mol_code)
                if not mol_node:
                    errors.append(CompilerError(
                        code=ErrorCode.E201_MISSING_REFERENCE,
                        message=f"Unresolved molecule reference: {mol_code}",
                        phase="S5_CONSTRUCT",
                        fqdn_id=node.fqdn,
                    ))
                    continue

                mol_core = mol_node.frontmatter.get("core", {})
                loop_spec = {
                    "over": step.get("over"),
                    "iterator": step.get("iterator"),
                    "accumulator": step.get("accumulator", {}),
                    "inputs": step.get("inputs", {}),
                    "update_accumulator": step.get("update_accumulator", {}),
                }
                transformed = {
                    "atom": mol_node.fqdn,
                    "out": step.get("as"),
                    "loop": loop_spec,
                    "input_types": _extract_input_types(
                        mol_core.get("inputs", {}) if isinstance(mol_core, dict) else {}
                    ),
                }
                atom_stream.append(transformed)

            else:
                atom_stream.append(step)

        # Transform emit → outputs
        emit_config = machine.get("emit", {})
        for output_name, from_symbol in (emit_config.items() if isinstance(emit_config, dict) else []):
            ct_ir_outputs[output_name] = {"from": from_symbol}

    else:
        errors.append(CompilerError(
            code=ErrorCode.E205_CT_VALIDATION_FAILED,
            message=f"Unknown ct_kind: {ct_kind}",
            phase="S5_CONSTRUCT",
            fqdn_id=node.fqdn,
        ))
        return None, errors

    ct_ir = {
        "ct_code": node.artifact_code,
        "ct_fqdn": node.fqdn,
        "atom_stream": atom_stream,
        "ct_composition_version": "V0",
        "inputs": dict(core.get("inputs", {})) if isinstance(core, dict) else {},
        "outputs": ct_ir_outputs,
    }

    return ct_ir, errors


def _build_cs_ir(node: Node) -> tuple[dict[str, Any] | None, list[CompilerError]]:
    """Build CS-IR for a CS node."""
    errors: list[CompilerError] = []
    implementation = node.frontmatter.get("implementation")

    if not implementation or not implementation.get("module") or not implementation.get("callable"):
        errors.append(CompilerError(
            code=ErrorCode.E205_CT_VALIDATION_FAILED,
            message="CS missing implementation — cannot emit cs_ir",
            phase="S5_CONSTRUCT",
            fqdn_id=node.fqdn,
        ))
        return None, errors

    core = node.frontmatter.get("core", {})
    policy_ops = core.get("policy", {}).get("operations", []) if isinstance(core, dict) else []
    operations = core.get("operations", {}) if isinstance(core, dict) else {}

    cs_ir = {
        "handler_ref": {
            "module": implementation["module"],
            "callable": implementation["callable"],
        },
        "cs_metadata": {
            "capability": {
                "supported_operation_specs": list(policy_ops),
            },
            "operations": {
                "operations": dict(operations) if operations else {},
            },
        },
    }

    return cs_ir, errors


def _build_cc_projection(
    node: Node,
    ct_index: dict[str, Node],
    cs_index: dict[str, Node],
) -> tuple[dict[str, Any] | None, list[CompilerError]]:
    """Build CC pipeline projection for a CC node."""
    errors: list[CompilerError] = []
    core = node.frontmatter.get("core", {})
    pipeline = core.get("pipeline", []) if isinstance(core, dict) else []

    _MAX_SIG = 5
    _MAX_BIND = 5

    steps: list[dict] = []
    seen_fqdns: set[str] = set()

    for step in pipeline:
        if not isinstance(step, dict):
            continue

        t = step.get("transform")
        s = step.get("side_effect")
        ref_fqdn = t or s
        if not ref_fqdn or ref_fqdn in seen_fqdns:
            continue
        seen_fqdns.add(ref_fqdn)

        code = ref_fqdn.split("::")[-1] if "::" in ref_fqdn else ref_fqdn
        kind = "CT" if t else "CS"

        if kind == "CT":
            ref_node = ct_index.get(code)
            if not ref_node:
                continue
            ref_core = ref_node.frontmatter.get("core", {})
            ref_core = ref_core if isinstance(ref_core, dict) else {}
            inputs_sig = list(ref_core.get("inputs", {}).keys())
            outputs_sig = list(ref_core.get("outputs", {}).keys())

            raw_bindings = step.get("inputs", {})
            bindings: dict[str, str] = {}
            for k, v in (raw_bindings.items() if isinstance(raw_bindings, dict) else []):
                normalized = _normalize_binding(v)
                if normalized is not None:
                    bindings[k] = normalized
                if len(bindings) >= _MAX_BIND:
                    break

            entry: dict = {
                "id": code,
                "fqdn": ref_fqdn,
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
            ref_node = cs_index.get(code)
            if not ref_node:
                continue
            ref_core = ref_node.frontmatter.get("core", {})
            ref_core = ref_core if isinstance(ref_core, dict) else {}
            policy_ops = ref_core.get("policy", {}).get("operations", [])
            ops_sig = list(policy_ops) if isinstance(policy_ops, list) else list(policy_ops.keys())

            entry = {
                "id": code,
                "fqdn": ref_fqdn,
                "kind": "CS",
                "ops": ops_sig[:_MAX_SIG],
                "outputs": ["result_status"],
            }
            if len(ops_sig) > _MAX_SIG:
                entry["ops_truncated"] = True

        steps.append(entry)

    return {"cc_projection": {"steps": steps}}, errors


def _enrich_wf_nodes(
    node: Node,
    code_to_fqdn: dict[str, str],
    builder: GraphBuilder,
) -> list[CompilerError]:
    """Enrich WF frontmatter nodes with fqdn_id resolution."""
    errors: list[CompilerError] = []
    wf_nodes = node.frontmatter.get("core", {}).get("nodes", {})

    if not isinstance(wf_nodes, dict):
        return errors

    # Build enriched frontmatter with fqdn_ids resolved
    enriched_nodes = {}
    for node_key, wf_node in wf_nodes.items():
        if not isinstance(wf_node, dict):
            enriched_nodes[node_key] = wf_node
            continue

        node_type = wf_node.get("type")
        if node_type not in ("CC", "IN"):
            enriched_nodes[node_key] = dict(wf_node)
            continue

        ref_code = wf_node.get("code") or wf_node.get("fqdn_id")
        if not ref_code:
            enriched_nodes[node_key] = dict(wf_node)
            continue

        enriched = dict(wf_node)
        if "::" in ref_code:
            enriched["fqdn_id"] = ref_code
        elif ref_code in code_to_fqdn:
            enriched["fqdn_id"] = code_to_fqdn[ref_code]
        else:
            errors.append(CompilerError(
                code=ErrorCode.E201_MISSING_REFERENCE,
                message=f"WF node '{node_key}' references '{ref_code}' — no matching artifact",
                phase="S5_CONSTRUCT",
                fqdn_id=node.fqdn,
            ))

        enriched_nodes[node_key] = enriched

    # Update the frontmatter with enriched nodes
    fm = dict(node.frontmatter)
    core = dict(fm.get("core", {}))
    core["nodes"] = enriched_nodes
    fm["core"] = core
    builder.replace_node(node.fqdn, frontmatter=MappingProxyType(fm))

    return errors


def _extract_input_types(core_inputs: Any) -> dict[str, str]:
    """Extract input types from core.inputs spec."""
    input_types: dict[str, str] = {}
    if isinstance(core_inputs, dict):
        for key, spec in core_inputs.items():
            if isinstance(spec, dict) and "type" in spec:
                input_types[key] = spec["type"]
    return input_types


def _normalize_binding(value: object) -> str | None:
    """Normalize a CC pipeline binding value for projection display."""
    if not isinstance(value, str):
        return None
    if len(value) > 80:
        return None
    if value.startswith("$.results."):
        return value[len("$.results."):]
    if value.startswith("$.inputs."):
        return "in." + value[len("$.inputs."):]
    if value.startswith("$."):
        return value
    return None
