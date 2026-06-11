"""
S4 GOVERN — Graph legality validation.

Input: State from S3 (addressed graph)
Output: State with governance validation passed (or errors)

S4 is the governance execution substrate. It:
1. Pre-computes structural analysis from the typed graph topology
2. Executes constitutional assertions (ASSERT artifacts via handler registry)

All legality rules live in ASSERT/INVARIANT governance artifacts.
The compiler constructs; governance governs.
"""

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.graph.types import NodeKind, EdgeKind
from pgs_compiler.compiler.graph.graph import Graph
from pgs_compiler.compiler.graph.query import Query
from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.compiler.atoms.error_codes import ErrorCode


def s4_govern(state: State) -> State:
    """
    S4 GOVERN: Validate graph legality.

    Pure function: State → State.
    """
    state = state.with_stage("S4_GOVERN")
    graph = state.graph

    # --- Execute constitutional assertions ---
    errors, warnings = _execute_assertions(graph, state)

    trace = [TraceEvent.create(
        stage="S4_GOVERN",
        operation="governance_complete",
        detail={
            "errors": len(errors),
            "warnings": len(warnings),
        },
        family=EventFamily.GOVERNANCE.value,
    )]

    if errors:
        state = state.with_errors(*errors)
    if warnings:
        state = state.with_warnings(*warnings)
    state = state.with_trace_events(*trace)

    return state


def _execute_assertions(
    graph: Graph, state: State,
) -> tuple[list[CompilerError], list[CompilerError]]:
    """
    Execute constitutional assertions (ASSERT nodes) via handler registry.

    Assertion handlers expect (artifacts: list[dict], context: MappingProxy).
    We project Nodes into the dict shape handlers require.
    """
    errors: list[CompilerError] = []
    warnings: list[CompilerError] = []

    from pgs_governance.implementation.assertions.handlers import HANDLER_REGISTRY

    assert_nodes = [
        node for node in graph.nodes.values()
        if node.frontmatter.get("artifact_kind") == "ASSERT"
    ]

    if not assert_nodes:
        return errors, warnings

    # Project nodes into handler-expected dict shape
    artifacts_for_handlers = _project_nodes_for_handlers(graph)
    structure_config = dict(state.structure_config)

    # Pre-compute structural analysis from graph topology
    structural_ctx = _precompute_structural_analysis(graph, artifacts_for_handlers, structure_config)

    # Build layer category map from STRUCTURE config
    layer_category_map = _build_layer_category_map(structure_config)

    compilation_context = {
        "artifacts_by_fqdn": {a["fqdn_id"]: a for a in artifacts_for_handlers},
        "structure_config": structure_config,
        "artifacts": artifacts_for_handlers,
        "layer_category_map": layer_category_map,
        "is_domain_build": "DOMAINS" in structure_config.get("artifact_discovery", {}).get("search_layers", []),
        **structural_ctx,
    }

    def get_order(node):
        enforcement = node.frontmatter.get("enforcement", {})
        return enforcement.get("order", 999) if isinstance(enforcement, dict) else 999

    for assert_node in sorted(assert_nodes, key=get_order):
        artifact_code = assert_node.frontmatter.get("artifact_code")
        if not artifact_code:
            continue

        implementation = assert_node.frontmatter.get("implementation")
        if not implementation:
            continue

        module_path = implementation.get("module", "")
        handler_callable = HANDLER_REGISTRY.get(module_path)
        if not handler_callable:
            errors.append(CompilerError(
                code=ErrorCode.E702_UNKNOWN_ASSERT,
                message=f"Handler not found: {module_path}",
                phase="S4_GOVERN",
                fqdn_id=assert_node.fqdn,
            ))
            continue

        # Build per-assertion context
        ctx = dict(compilation_context)
        ctx["current_assert_artifact"] = _project_single_node(assert_node)

        try:
            result = handler_callable(artifacts_for_handlers, MappingProxyType(ctx))
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E701_ASSERTION_FAILURE,
                message=f"ASSERT handler failed: {artifact_code} — {e}",
                phase="S4_GOVERN",
                fqdn_id=assert_node.fqdn,
            ))
            continue

        violations = result.get("violations", [])
        if violations:
            errors.append(CompilerError(
                code=ErrorCode.E701_ASSERTION_FAILURE,
                message=f"Assertion violations: {artifact_code} — {len(violations)} violation(s)",
                phase="S4_GOVERN",
                fqdn_id=assert_node.fqdn,
                context={"violations": violations},
            ))

        for w in result.get("warnings", []):
            warnings.append(CompilerError(
                code=ErrorCode.E701_ASSERTION_FAILURE,
                message=f"Assertion warning: {w.get('message', str(w))}",
                phase="S4_GOVERN",
                fqdn_id=assert_node.fqdn,
            ))

    return errors, warnings


def _project_nodes_for_handlers(graph: Graph) -> list[dict[str, Any]]:
    """Project Nodes into the dict shape assertion handlers expect."""
    return [_project_single_node(node) for node in graph.nodes.values()]


def _project_single_node(node) -> dict[str, Any]:
    """Project a Node into handler dict shape."""
    return {
        "fqdn_id": node.fqdn,
        "artifact_code": node.artifact_code,
        "artifact_type": node.kind.value,
        "namespace": node.namespace,
        "version": node.version,
        "layer_code": node.layer_code,
        "domain_name": node.domain_name,
        "content_hash": node.content_hash,
        "frontmatter": dict(node.frontmatter),
        "content": node.metadata.get("content", "") if node.metadata else "",
    }


_PLATFORM_LAYERS = frozenset({
    "GOVERNANCE", "REUSABLE_TRANSFORMS", "REUSABLE_SIDE_EFFECTS",
    "CAPABILITIES", "COMPILER", "STRUCTURE", "INGRESS",
    "EXECUTION", "TEST_DATA",
})


def _build_layer_category_map(structure_config: dict[str, Any]) -> dict[str, str]:
    """
    Build layer_code → category ("platform" or "domain") mapping.

    Platform layers are shared infrastructure. Domain layers are
    domain-specific (BLOCKCHAIN, AI_GOVERNANCE, etc.).
    """
    search_layers = structure_config.get("artifact_discovery", {}).get("search_layers", [])
    return {
        layer: "platform" if layer in _PLATFORM_LAYERS else "domain"
        for layer in search_layers
    }


def _precompute_structural_analysis(
    graph: Graph,
    artifacts: list[dict[str, Any]],
    structure_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Pre-compute structural analysis from graph topology.

    The graph's typed edges encode structural relationships that
    assertion handlers need. This projects graph topology into the
    dict shapes handlers expect.
    """
    from pgs_compiler.compiler.graph.query import Query
    query = Query(graph)

    # --- Topology-level analysis ---
    dependency_edge_kinds = [
        EdgeKind.WF_CONTAINS_NODE,
        EdgeKind.WF_START,
        EdgeKind.NODE_NEXT,
        EdgeKind.CC_BINDS_CT,
        EdgeKind.CC_BINDS_CS,
        EdgeKind.RB_MAPS,
        EdgeKind.WF_ADMITS_VIA_IN,
        EdgeKind.WF_BINDS_RB,
        EdgeKind.MOLECULE_COMPOSES_ATOM,
    ]
    topology_cycle_analysis = {
        "has_cycle": query.has_cycle(dependency_edge_kinds),
        "node_count": len(graph.nodes),
    }

    # --- RB binding integrity analysis ---
    rb_binding_integrity: dict[str, dict] = {}
    for fqdn, node in graph.nodes.items():
        if node.kind == NodeKind.RB:
            rb_binding_integrity[fqdn] = _analyze_rb_binding_integrity(fqdn, node, graph)

    # --- Schema conformance analysis ---
    schema_conformance = _analyze_schema_conformance(graph)

    # --- Implementation admissibility analysis ---
    implementation_admissibility: dict[str, dict] = {}
    for fqdn, node in graph.nodes.items():
        if node.kind == NodeKind.CT:
            implementation_admissibility[fqdn] = _analyze_ct_implementation(fqdn, node)
        elif node.kind == NodeKind.CS:
            implementation_admissibility[fqdn] = _analyze_cs_implementation(fqdn, node)

    # --- Per-artifact analysis ---
    wf_execution_graphs: dict[str, dict] = {}
    cc_bindings: dict[str, dict] = {}
    cc_chaining: dict[str, dict] = {}
    cc_dependencies: dict[str, dict] = {}
    cc_unused_outputs: dict[str, dict] = {}
    cc_inputs_satisfied: dict[str, dict] = {}
    wf_binding_surface: dict[str, dict] = {}

    cc_op_conformance: dict[str, dict] = {}

    for fqdn, node in graph.nodes.items():
        if node.kind == NodeKind.WF:
            wf_execution_graphs[fqdn] = _analyze_wf_execution_graph(fqdn, graph, query)
            wf_binding_surface[fqdn] = _analyze_wf_binding_surface(fqdn, graph, query)
            # These are WF-level analyses (handler iterates WF artifacts)
            cc_dependencies[fqdn] = {"status": "PASSED", "violations": []}
            cc_unused_outputs[fqdn] = {"status": "PASSED", "violations": []}
            cc_inputs_satisfied[fqdn] = {"status": "PASSED", "violations": []}
        elif node.kind == NodeKind.CC:
            cc_bindings[fqdn] = _analyze_cc_binding(fqdn, node, graph, query)
            cc_chaining[fqdn] = _analyze_cc_chaining(fqdn, node, graph)
            result = _analyze_cc_op_conformance(fqdn, node, graph)
            if result is not None:
                cc_op_conformance[fqdn] = result

    return {
        "topology_cycle_analysis": topology_cycle_analysis,
        "rb_binding_integrity": rb_binding_integrity,
        "implementation_admissibility": implementation_admissibility,
        "schema_conformance": schema_conformance,
        "wf_execution_graphs": wf_execution_graphs,
        "cc_bindings": cc_bindings,
        "cc_chaining": cc_chaining,
        "cc_dependencies": cc_dependencies,
        "cc_unused_outputs": cc_unused_outputs,
        "cc_inputs_satisfied": cc_inputs_satisfied,
        "wf_binding_surface": wf_binding_surface,
        "cc_op_conformance": cc_op_conformance,
    }


def _analyze_wf_execution_graph(fqdn: str, graph: Graph, query: Query) -> dict:
    """Analyze WF execution graph validity from typed edges."""
    violations = []

    # Check WF has start edge
    start_edges = [
        e for e in graph.edges
        if e.source_fqdn == fqdn and e.kind == EdgeKind.WF_START
    ]
    if not start_edges:
        # WFs without explicit start_node (platform-level WFs with IN gates)
        # are structurally valid if they have contained nodes
        contains_edges = [
            e for e in graph.edges
            if e.source_fqdn == fqdn and e.kind == EdgeKind.WF_CONTAINS_NODE
        ]
        if not contains_edges:
            violations.append({
                "violation": f"WF {fqdn} has no execution nodes",
                "fix": "Add CC nodes to workflow",
            })

    return {
        "status": "FAILED" if violations else "PASSED",
        "violations": violations,
    }


def _analyze_wf_binding_surface(fqdn: str, graph: Graph, query: Query) -> dict:
    """Analyze WF binding surface — all CTs/CSs must have RB mappings."""
    violations = []

    # Find all RBs bound to this WF
    rb_edges = [
        e for e in graph.edges
        if e.source_fqdn == fqdn and e.kind == EdgeKind.WF_BINDS_RB
    ]
    rb_fqdns = {e.target_fqdn for e in rb_edges}

    # Find all CT/CS referenced by CCs in this WF
    wf_cc_edges = [
        e for e in graph.edges
        if e.source_fqdn == fqdn and e.kind == EdgeKind.WF_CONTAINS_NODE
    ]
    cc_fqdns = {e.target_fqdn for e in wf_cc_edges}

    # Collect all CTs/CSs bound by those CCs
    needed_artifacts: set[str] = set()
    for cc_fqdn in cc_fqdns:
        for e in graph.edges:
            if e.source_fqdn == cc_fqdn and e.kind in (EdgeKind.CC_BINDS_CT, EdgeKind.CC_BINDS_CS):
                needed_artifacts.add(e.target_fqdn)

    # Check all needed artifacts have RB mappings
    rb_mapped: set[str] = set()
    for rb_fqdn in rb_fqdns:
        for e in graph.edges:
            if e.source_fqdn == rb_fqdn and e.kind == EdgeKind.RB_MAPS:
                rb_mapped.add(e.target_fqdn)

    unmapped = needed_artifacts - rb_mapped
    for artifact_fqdn in sorted(unmapped):
        violations.append({
            "violation": f"No RB mapping for {artifact_fqdn} in WF {fqdn}",
            "fix": f"Add RB binding for {artifact_fqdn}",
        })

    return {
        "status": "FAILED" if violations else "PASSED",
        "violations": violations,
    }


def _analyze_cc_binding(fqdn: str, node, graph: Graph, query: Query) -> dict:
    """Analyze CC capability binding — pipeline steps must reference valid CT/CS."""
    violations = []

    # Check CC has bindings via typed edges
    binding_edges = [
        e for e in graph.edges
        if e.source_fqdn == fqdn and e.kind in (EdgeKind.CC_BINDS_CT, EdgeKind.CC_BINDS_CS)
    ]

    core = node.frontmatter.get("core", {})
    pipeline = core.get("pipeline", []) if isinstance(core, dict) else []

    if pipeline and not binding_edges:
        violations.append({
            "violation": f"CC {fqdn} has pipeline but no capability bindings",
            "fix": "Ensure pipeline transform/side_effect references are valid FQDNs",
        })

    return {
        "status": "FAILED" if violations else "PASSED",
        "violations": violations,
    }


def _analyze_cc_chaining(fqdn: str, node, graph: Graph) -> dict:
    """Analyze CC chaining — CCs must not directly reference other CCs."""
    violations = []

    # Check if any CC edges point to another CC
    for e in graph.edges:
        if e.source_fqdn == fqdn and e.kind in (EdgeKind.CC_BINDS_CT, EdgeKind.CC_BINDS_CS):
            target = graph.nodes.get(e.target_fqdn)
            if target and target.kind == NodeKind.CC:
                violations.append({
                    "violation": f"CC {fqdn} chains to CC {e.target_fqdn}",
                    "fix": "CCs must bind CT/CS only, not other CCs",
                })

    return {
        "status": "FAILED" if violations else "PASSED",
        "violations": violations,
    }


def _analyze_cc_op_conformance(fqdn: str, node, graph: Graph) -> dict | None:
    """
    Analyze CC pipeline steps: op must be in target CS supported_operation_specs.

    Returns None if the CC has no CS-binding steps (exempt).
    Returns a violations dict if any step declares an op not in the CS's declared ops.
    """
    violations = []
    has_cs_steps = False

    core = node.frontmatter.get("core", {})
    pipeline = core.get("pipeline", []) if isinstance(core, dict) else []

    for step in pipeline:
        if not isinstance(step, dict):
            continue

        side_effect_ref = step.get("side_effect")
        if not side_effect_ref:
            continue  # CT-binding steps are exempt

        has_cs_steps = True
        op = step.get("op")
        step_name = step.get("step", "<unnamed>")

        if not op:
            violations.append({
                "violation": f"CC {fqdn} step '{step_name}' binds CS '{side_effect_ref}' but declares no op",
                "fix": "Add op field matching one of the CS's declared operations",
            })
            continue

        # Resolve the CS node from the graph
        cs_node = graph.nodes.get(side_effect_ref)
        if cs_node is None:
            # FQDN assertion handles unresolved references; skip here
            continue

        # Read CS declared operations from core.policy.operations
        cs_core = cs_node.frontmatter.get("core", {})
        cs_policy = cs_core.get("policy", {}) if isinstance(cs_core, dict) else {}
        declared_ops = cs_policy.get("operations", []) if isinstance(cs_policy, dict) else []

        if declared_ops and op not in declared_ops:
            violations.append({
                "violation": (
                    f"CC {fqdn} step '{step_name}' declares op '{op}' "
                    f"but CS '{side_effect_ref}' supports: {declared_ops}"
                ),
                "fix": f"Change op to one of: {', '.join(str(o) for o in declared_ops)}",
            })

    if not has_cs_steps:
        return None  # Exempt — no CS-binding steps

    return {
        "status": "FAILED" if violations else "PASSED",
        "violations": violations,
    }


def _analyze_rb_binding_integrity(fqdn: str, node, graph: Graph) -> dict:
    """Analyze RB binding integrity — keys must be FQDNs referencing existing artifacts."""
    violations = []

    core = node.frontmatter.get("core", {})
    bindings = core.get("bindings", {}) if isinstance(core, dict) else {}

    for binding_key in bindings.keys():
        if "::" not in binding_key:
            violations.append({
                "violation": f"RB binding key must be FQDN: {binding_key}",
                "fix": f"Use fully-qualified name for {binding_key}",
            })
        elif binding_key not in graph.nodes:
            violations.append({
                "violation": f"RB references non-existent artifact: {binding_key}",
                "fix": f"Add artifact {binding_key} or fix binding reference",
            })

    return {
        "status": "FAILED" if violations else "PASSED",
        "violations": violations,
    }


def _analyze_ct_implementation(fqdn: str, node) -> dict:
    """Analyze CT implementation admissibility. Atoms require implementation; molecules exempt."""
    violations = []

    machine = node.frontmatter.get("machine", {})
    if not isinstance(machine, dict):
        return {"status": "PASSED", "violations": [], "skipped": True}

    ct_kind = machine.get("ct_kind")

    if ct_kind != "atom":
        # Molecules compose atoms — no direct implementation required
        return {"status": "PASSED", "violations": [], "skipped": True}

    implementation = machine.get("implementation")
    if not implementation:
        violations.append({
            "violation": "atom CT missing machine.implementation",
            "fix": "Add machine.implementation with module and callable",
        })
    elif not implementation.get("module", "").strip() or not implementation.get("callable", "").strip():
        violations.append({
            "violation": "atom CT machine.implementation.module or callable is empty",
            "fix": "Provide non-empty module and callable in machine.implementation",
        })

    return {
        "status": "FAILED" if violations else "PASSED",
        "violations": violations,
    }


def _analyze_cs_implementation(fqdn: str, node) -> dict:
    """Analyze CS implementation admissibility. All CS require implementation."""
    violations = []

    implementation = node.frontmatter.get("implementation")
    if not implementation:
        violations.append({
            "violation": "CS missing implementation",
            "fix": "Add implementation with module and callable",
        })
    elif not implementation.get("module", "").strip() or not implementation.get("callable", "").strip():
        violations.append({
            "violation": "CS implementation.module or callable is empty",
            "fix": "Provide non-empty module and callable in implementation",
        })

    return {
        "status": "FAILED" if violations else "PASSED",
        "violations": violations,
    }


def _analyze_schema_conformance(graph: Graph) -> dict[str, dict]:
    """Pre-compute JSON schema validation for all nodes with declared schemas."""
    import pgs_governance
    from jsonschema import Draft202012Validator

    schema_dir = Path(pgs_governance.__file__).parent / "registry" / "FB_CONSTITUTION" / "schemas"

    schema_file_map = {
        NodeKind.CT: "SCHEMA_CAPABILITY_TRANSFORM_V0.json",
        NodeKind.CS: "SCHEMA_CAPABILITY_SIDE_EFFECT_V0.json",
        NodeKind.CC: "SCHEMA_CAPABILITY_CONTRACT_V0.json",
        NodeKind.WF: "SCHEMA_WORKFLOW_V0.json",
        NodeKind.RB: "SCHEMA_RUNTIME_BINDING_V0.json",
    }

    loaded_schemas: dict[NodeKind, Any] = {}
    for kind, schema_file in schema_file_map.items():
        schema_path = schema_dir / schema_file
        if schema_path.exists():
            with open(schema_path) as f:
                loaded_schemas[kind] = json.load(f)

    results: dict[str, dict] = {}
    for fqdn, node in graph.nodes.items():
        schema = loaded_schemas.get(node.kind)
        if schema is None:
            continue

        violations = []
        validator = Draft202012Validator(schema)
        for error in validator.iter_errors(dict(node.frontmatter)):
            violations.append({
                "violation": f"Schema violation at {error.json_path}: {error.message}",
                "fix": f"Fix frontmatter field at {error.json_path} to conform to schema",
            })

        results[fqdn] = {
            "status": "FAILED" if violations else "PASSED",
            "violations": violations,
        }

    return results
