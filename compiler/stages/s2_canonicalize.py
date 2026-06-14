"""
S2 CANONICALIZE — Type generic REFERENCES edges into specific edge kinds.

Input: State from S1 (nodes populated, all edges are REFERENCES)
Output: State with typed edges (WF_CONTAINS_NODE, CC_BINDS_CT, etc.)

This stage examines each REFERENCES edge, looks at the source and target
node kinds and frontmatter, and promotes it to the correct EdgeKind.

Also performs structural validation:
- All reference targets exist as nodes in the graph
- No dangling references
- Edge kinds are legal for their source/target node kinds
"""

from pgs_compiler.compiler.graph.types import NodeKind, EdgeKind
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.edge import Edge
from pgs_compiler.compiler.graph.graph import Graph, GraphBuilder
from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.compiler.atoms.error_codes import ErrorCode


def s2_canonicalize(state: State) -> State:
    """
    S2 CANONICALIZE: Promote REFERENCES edges to typed edge kinds.

    Pure function: State → State.

    Steps:
        1. Validate all edge targets exist in graph
        2. Classify each REFERENCES edge by source/target kind
        3. Build WF execution topology edges from frontmatter
        4. Rebuild graph with typed edges

    Args:
        state: State from S1 EXTRACT

    Returns:
        New State with typed edges
    """
    state = state.with_stage("S2_CANONICALIZE")
    errors: list[CompilerError] = []
    warnings: list[CompilerError] = []
    trace: list[TraceEvent] = []
    graph = state.graph

    builder = GraphBuilder()

    # Copy all nodes unchanged
    for node in graph.nodes.values():
        builder.add_node(node)

    # --- Step 1: Validate edge targets exist ---
    for edge in graph.edges:
        if edge.target_fqdn not in graph.nodes:
            errors.append(CompilerError(
                code=ErrorCode.E104_INVALID_FQDN,
                message=(
                    f"Dangling reference: {edge.source_fqdn} → {edge.target_fqdn} "
                    f"(target not found in graph)"
                ),
                phase="S2_CANONICALIZE",
                fqdn_id=edge.source_fqdn,
            ))

    if errors:
        return state.with_errors(*errors)

    # --- Step 2: Classify REFERENCES edges ---
    for edge in graph.edges:
        if edge.kind != EdgeKind.REFERENCES:
            # Already typed (shouldn't happen after S1, but defensive)
            builder.add_edge(edge)
            continue

        source_node = graph.nodes[edge.source_fqdn]
        target_node = graph.nodes[edge.target_fqdn]
        typed_kind = _classify_edge(source_node, target_node)

        if typed_kind != EdgeKind.REFERENCES:
            trace.append(TraceEvent.create(
                stage="S2_CANONICALIZE",
                operation="edge_typed",
                subject_fqdn=edge.source_fqdn,
                detail={"target": edge.target_fqdn, "kind": typed_kind.value},
                family=EventFamily.TOPOLOGY.value,
            ))

        builder.add_edge(edge.replace(kind=typed_kind))

    # --- Step 3: Build WF execution topology edges from frontmatter ---
    _build_wf_topology_edges(graph, builder, errors, warnings)

    # --- Step 4: Build CC pipeline binding edges from frontmatter ---
    _build_cc_pipeline_edges(graph, builder, errors)

    # --- Step 5: Build RB mapping edges from frontmatter ---
    _build_rb_mapping_edges(graph, builder, errors)

    # --- Step 6: Build TI invocation edges from frontmatter ---
    _build_ti_invocation_edges(graph, builder, errors)

    # --- Step 7: Drop bare duplicates shadowed by metadata-rich edges ---
    # The same binding is legitimately declared twice (references header +
    # frontmatter pipeline step); only the metadata-rich edge survives.
    dropped = builder.drop_bare_duplicate_edges()
    if dropped:
        trace.append(TraceEvent.create(
            stage="S2_CANONICALIZE",
            operation="bare_duplicate_edges_dropped",
            detail={"count": dropped},
            family=EventFamily.TOPOLOGY.value,
        ))

    if errors:
        state = state.with_errors(*errors)
    if warnings:
        state = state.with_warnings(*warnings)
    if trace:
        state = state.with_trace_events(*trace)

    new_graph = builder.build()
    state = state.with_graph(new_graph)

    # Record canonicalization metadata
    edge_kind_counts: dict[str, int] = {}
    for edge in new_graph.edges:
        k = edge.kind.value
        edge_kind_counts[k] = edge_kind_counts.get(k, 0) + 1
    state = state.with_metadata("edge_kind_counts", edge_kind_counts)

    return state


def _classify_edge(source: Node, target: Node) -> EdgeKind:
    """
    Determine the correct edge kind based on source and target node kinds.

    Classification rules (source_kind → target_kind → edge_kind):
    - WF → IN  → WF_ADMITS_VIA_IN
    - WF → RB  → WF_BINDS_RB
    - WF → CC  → WF_CONTAINS_NODE (generic; START and NEXT come from frontmatter)
    - CC → CT  → CC_BINDS_CT
    - CC → CS  → CC_BINDS_CS
    - RB → CT  → RB_MAPS
    - RB → CS  → RB_MAPS
    - * → GOVERNANCE → GOVERNED_BY
    - * → ASSERT → ASSERTED_BY
    - CT → CT  → MOLECULE_COMPOSES_ATOM
    - Otherwise → REFERENCES (unresolved)
    """
    sk = source.kind
    tk = target.kind

    # Governance edges
    if tk == NodeKind.GOVERNANCE:
        return EdgeKind.GOVERNED_BY
    if tk == NodeKind.ASSERT:
        return EdgeKind.ASSERTED_BY

    # WF outgoing edges
    if sk == NodeKind.WF:
        if tk == NodeKind.IN:
            return EdgeKind.WF_ADMITS_VIA_IN
        if tk == NodeKind.RB:
            return EdgeKind.WF_BINDS_RB
        if tk == NodeKind.CC:
            return EdgeKind.WF_CONTAINS_NODE

    # CC binding edges
    if sk == NodeKind.CC:
        if tk == NodeKind.CT:
            return EdgeKind.CC_BINDS_CT
        if tk == NodeKind.CS:
            return EdgeKind.CC_BINDS_CS

    # RB mapping edges
    if sk == NodeKind.RB:
        if tk in (NodeKind.CT, NodeKind.CS):
            return EdgeKind.RB_MAPS

    # TI invocation entry point
    if sk == NodeKind.TI and tk == NodeKind.WF:
        return EdgeKind.TI_INVOKES_WF

    # CT composition
    if sk == NodeKind.CT and tk == NodeKind.CT:
        return EdgeKind.MOLECULE_COMPOSES_ATOM

    # Unresolvable — keep as generic reference
    return EdgeKind.REFERENCES


def _build_wf_topology_edges(
    graph: Graph,
    builder: GraphBuilder,
    errors: list[CompilerError],
    warnings: list[CompilerError],
) -> None:
    """
    Build WF execution topology edges from WF frontmatter.

    WF topology uses local node keys (e.g. "entry", "lookup", "exit") which
    reference artifacts via `code` or `fqdn_id` fields. This stage resolves
    those local keys to graph-level FQDNs and builds:
    - WF_START edge (from WF to the start node's resolved FQDN)
    - WF_CONTAINS_NODE edges (for CC/IN nodes that reference graph artifacts)
    - NODE_NEXT edges (from inline `next` maps or `transitions[]`)
    """
    # Build code → FQDN lookup once; depends only on graph, not on any specific WF
    code_to_fqdn: dict[str, str] = {
        graph_node.artifact_code: graph_fqdn
        for graph_fqdn, graph_node in graph.nodes.items()
    }

    for fqdn, node in graph.nodes.items():
        if node.kind != NodeKind.WF:
            continue

        core = node.frontmatter.get("core", {})
        if not isinstance(core, dict):
            continue

        wf_nodes = core.get("nodes", {})
        if not isinstance(wf_nodes, dict):
            continue

        # Build local-key → FQDN resolution map
        key_to_fqdn: dict[str, str | None] = {}
        for key, node_spec in wf_nodes.items():
            if not isinstance(node_spec, dict):
                key_to_fqdn[key] = None
                continue
            ref = node_spec.get("fqdn_id") or node_spec.get("code")
            if ref and "::" in ref and ref in graph.nodes:
                key_to_fqdn[key] = ref
            elif ref and "::" not in ref:
                # Short code — resolve via namespace prefix or artifact_code lookup
                ns_fqdn = f"{node.namespace}::{ref}"
                if ns_fqdn in graph.nodes:
                    key_to_fqdn[key] = ns_fqdn
                elif ref in code_to_fqdn:
                    key_to_fqdn[key] = code_to_fqdn[ref]
                else:
                    key_to_fqdn[key] = None
            else:
                key_to_fqdn[key] = None

        # WF_START edge
        start_node = core.get("start_node")
        if isinstance(start_node, str) and start_node:
            resolved_start = key_to_fqdn.get(start_node) if start_node in key_to_fqdn else (
                start_node if start_node in graph.nodes else None
            )
            if resolved_start:
                builder.add_edge(Edge.create(
                    source_fqdn=fqdn,
                    target_fqdn=resolved_start,
                    kind=EdgeKind.WF_START,
                ))

        # WF_CONTAINS_NODE edges from nodes map
        for key, resolved_fqdn in key_to_fqdn.items():
            if resolved_fqdn:
                builder.add_edge(Edge.create(
                    source_fqdn=fqdn,
                    target_fqdn=resolved_fqdn,
                    kind=EdgeKind.WF_CONTAINS_NODE,
                ))

        # NODE_NEXT edges from inline `next` maps on each node
        for key, node_spec in wf_nodes.items():
            if not isinstance(node_spec, dict):
                continue
            next_map = node_spec.get("next", {})
            if not isinstance(next_map, dict):
                continue

            source_resolved = key_to_fqdn.get(key)
            for condition, target_key in next_map.items():
                target_resolved = key_to_fqdn.get(target_key)
                if source_resolved and target_resolved:
                    builder.add_edge(Edge.create(
                        source_fqdn=source_resolved,
                        target_fqdn=target_resolved,
                        kind=EdgeKind.NODE_NEXT,
                        metadata={"condition": condition, "wf_fqdn": fqdn},
                    ))

        # NODE_NEXT edges from explicit transitions[] (FQDN-based)
        transitions = core.get("transitions", [])
        for transition in transitions:
            if not isinstance(transition, dict):
                continue

            from_node = transition.get("from")
            to_node = transition.get("to")
            condition = transition.get("condition", "")

            if not from_node or not to_node:
                continue

            # Resolve via key map or direct FQDN lookup
            from_resolved = key_to_fqdn.get(from_node, from_node if from_node in graph.nodes else None)
            to_resolved = key_to_fqdn.get(to_node, to_node if to_node in graph.nodes else None)

            if not from_resolved:
                errors.append(CompilerError(
                    code=ErrorCode.E104_INVALID_FQDN,
                    message=f"Transition from-node not found: {from_node}",
                    phase="S2_CANONICALIZE",
                    fqdn_id=fqdn,
                ))
                continue

            if not to_resolved:
                errors.append(CompilerError(
                    code=ErrorCode.E104_INVALID_FQDN,
                    message=f"Transition to-node not found: {to_node}",
                    phase="S2_CANONICALIZE",
                    fqdn_id=fqdn,
                ))
                continue

            builder.add_edge(Edge.create(
                source_fqdn=from_resolved,
                target_fqdn=to_resolved,
                kind=EdgeKind.NODE_NEXT,
                metadata={"condition": condition, "wf_fqdn": fqdn},
            ))


def _build_ti_invocation_edges(
    graph: Graph,
    builder: GraphBuilder,
    errors: list[CompilerError],
) -> None:
    """
    Build TI invocation edges from TI frontmatter.

    TI artifacts declare their workflow entry point via `core.workflow`
    (semantics: TI → invokes → WF; WF → binds → RB). These become
    TI_INVOKES_WF edges carrying the declared route.
    """
    for fqdn, node in graph.nodes.items():
        if node.kind != NodeKind.TI:
            continue

        core = node.frontmatter.get("core", {})
        if not isinstance(core, dict):
            continue

        wf_ref = core.get("workflow")
        if not isinstance(wf_ref, str) or not wf_ref:
            continue  # no declaration → no edge (zero inference)

        if wf_ref not in graph.nodes:
            errors.append(CompilerError(
                code=ErrorCode.E104_INVALID_FQDN,
                message=f"TI workflow target not found: {fqdn} → {wf_ref}",
                phase="S2_CANONICALIZE",
                fqdn_id=fqdn,
            ))
            continue

        route = core.get("route") if isinstance(core.get("route"), dict) else {}
        builder.add_edge(Edge.create(
            source_fqdn=fqdn,
            target_fqdn=wf_ref,
            kind=EdgeKind.TI_INVOKES_WF,
            metadata={
                "route_path": route.get("path", ""),
                "route_method": route.get("method", ""),
            },
        ))


def _build_cc_pipeline_edges(
    graph: Graph,
    builder: GraphBuilder,
    errors: list[CompilerError],
) -> None:
    """
    Build CC pipeline binding edges from CC frontmatter.

    CC frontmatter declares pipeline steps that reference CT/CS artifacts.
    These become CC_BINDS_CT / CC_BINDS_CS edges with step metadata.
    """
    for fqdn, node in graph.nodes.items():
        if node.kind != NodeKind.CC:
            continue

        core = node.frontmatter.get("core", {})
        if not isinstance(core, dict):
            continue

        pipeline = core.get("pipeline", [])
        for idx, step in enumerate(pipeline):
            if not isinstance(step, dict):
                continue

            # Each step may reference a transform or side_effect
            transform_ref = step.get("transform")
            if isinstance(transform_ref, str) and transform_ref:
                if transform_ref in graph.nodes:
                    target = graph.nodes[transform_ref]
                    edge_kind = (
                        EdgeKind.CC_BINDS_CT if target.kind == NodeKind.CT
                        else EdgeKind.CC_BINDS_CS if target.kind == NodeKind.CS
                        else EdgeKind.REFERENCES
                    )
                    builder.add_edge(Edge.create(
                        source_fqdn=fqdn,
                        target_fqdn=transform_ref,
                        kind=edge_kind,
                        metadata={
                            "pipeline_index": idx,
                            "step_id": step.get("step", ""),
                            "inputs": step.get("inputs", {}),
                            "outputs": step.get("outputs", {}),
                            "on_result": step.get("on_result", {}),
                        },
                    ))

            side_effect_ref = step.get("side_effect")
            if isinstance(side_effect_ref, str) and side_effect_ref:
                if side_effect_ref in graph.nodes:
                    builder.add_edge(Edge.create(
                        source_fqdn=fqdn,
                        target_fqdn=side_effect_ref,
                        kind=EdgeKind.CC_BINDS_CS,
                        metadata={
                            "pipeline_index": idx,
                            "step_id": step.get("step", ""),
                            "op": step.get("op", ""),
                            "inputs": step.get("inputs", {}),
                            "outputs": step.get("outputs", {}),
                            "on_result": step.get("on_result", {}),
                            "store": step.get("store", ""),
                        },
                    ))


def _build_rb_mapping_edges(
    graph: Graph,
    builder: GraphBuilder,
    errors: list[CompilerError],
) -> None:
    """
    Build RB mapping edges from RB frontmatter.

    RB core.bindings maps artifact FQDNs to implementation handlers.
    Each binding key → RB_MAPS edge.
    """
    for fqdn, node in graph.nodes.items():
        if node.kind != NodeKind.RB:
            continue

        core = node.frontmatter.get("core", {})
        if not isinstance(core, dict):
            continue

        bindings = core.get("bindings", {})
        if not isinstance(bindings, dict):
            continue

        for target_fqdn, binding_config in bindings.items():
            if target_fqdn not in graph.nodes:
                # Already caught in S1 reference validation
                continue

            handler_ref = ""
            if isinstance(binding_config, dict):
                handler_ref = binding_config.get("handler", "")

            builder.add_edge(Edge.create(
                source_fqdn=fqdn,
                target_fqdn=target_fqdn,
                kind=EdgeKind.RB_MAPS,
                metadata={"handler_ref": handler_ref},
            ))
