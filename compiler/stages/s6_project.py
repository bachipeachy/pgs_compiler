"""
S6 PROJECT — Generate projections from Graph.

Input: State from S5 (graph with IR populated on CT/CS/CC/WF nodes)
Output: State with named projections populated

Orchestrates projection generators. Each projection is a deterministic
derivation of the Graph — the sole semantic authority. No projection
derives from another projection.

Current projections:
    - canonical: human/governance/tooling authority (protocol_snapshot/)
    - vocabulary: per-structure address space realization (semantic_vocabulary/)
    - tokenized: machine/silicon/runtime topology (tokenized_snapshot/)
    - evidence: dual-form observability/replay substrate (evidence_snapshot/)
"""

from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.compiler.projections import ProjectionType
from pgs_compiler.compiler.projections.canonical import project_canonical
from pgs_compiler.compiler.projections.vocabulary import project_vocabulary
from pgs_compiler.compiler.projections.tokenized import project_tokenized
from pgs_compiler.compiler.projections.evidence import project_evidence
from pgs_compiler.compiler.projections.dispatch import project_dispatch
from pgs_compiler.compiler.projections.handlers import project_handlers


def s6_project(state: State) -> State:
    """
    S6 PROJECT: Generate projections from Graph.

    Pure function: State → State.
    """
    state = state.with_stage("S6_PROJECT")
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []

    # --- Canonical projection (protocol_snapshot/) ---
    canonical_projection, canonical_trace = project_canonical(state.graph)
    trace.extend(canonical_trace)

    # --- Vocabulary projection (semantic_vocabulary/) ---
    vocabulary_projection, voc_trace = project_vocabulary(state.graph)
    trace.extend(voc_trace)

    # --- Tokenized projection (tokenized_snapshot/) ---
    tokenized_projection, tok_trace = project_tokenized(state.graph)
    trace.extend(tok_trace)

    # --- Evidence projection (evidence_snapshot/) ---
    evidence_projection, evi_trace = project_evidence(state.graph)
    trace.extend(evi_trace)

    # --- Dispatch projection (tokenized_snapshot/ — routing tables) ---
    dispatch_projection, dis_trace = project_dispatch(state.graph)
    trace.extend(dis_trace)

    # --- Handlers projection (tokenized_snapshot/ — implementation dispatch) ---
    handlers_projection, han_trace = project_handlers(state.graph)
    trace.extend(han_trace)

    projections = {
        ProjectionType.CANONICAL.value: canonical_projection,
        ProjectionType.VOCABULARY.value: vocabulary_projection,
        ProjectionType.TOKENIZED.value: tokenized_projection,
        ProjectionType.EVIDENCE.value: evidence_projection,
        ProjectionType.DISPATCH.value: dispatch_projection,
        ProjectionType.HANDLERS.value: handlers_projection,
    }

    state = state.with_projections(projections)

    if errors:
        state = state.with_errors(*errors)
    if trace:
        state = state.with_trace_events(*trace)

    state = state.with_metadata("projected_count", len(canonical_projection.content))
    state = state.with_metadata("vocabulary_address_count", len(vocabulary_projection.content.get("forward", {})))
    state = state.with_metadata("tokenized_node_count", len(tokenized_projection.content.get("nodes", [])))
    state = state.with_metadata("tokenized_edge_count", len(tokenized_projection.content.get("edges", [])))
    state = state.with_metadata("evidence_node_count", len(evidence_projection.content.get("nodes", [])))
    state = state.with_metadata("evidence_edge_count", len(evidence_projection.content.get("edges", [])))
    state = state.with_metadata("evidence_event_count", len(evidence_projection.content.get("event_catalog", [])))
    state = state.with_metadata("dispatch_routing_count", len(dispatch_projection.content.get("routing", {})))
    state = state.with_metadata("dispatch_pipeline_count", len(dispatch_projection.content.get("pipeline", {})))
    state = state.with_metadata("dispatch_entry_count", len(dispatch_projection.content.get("entry", {})))
    state = state.with_metadata("handlers_ct_count", len(handlers_projection.content.get("ct", {})))
    state = state.with_metadata("handlers_cs_count", len(handlers_projection.content.get("cs", {})))
    state = state.with_metadata("handlers_rb_policy_count", len(handlers_projection.content.get("rb_policy", {})))

    return state