"""
S3 SEMANTIC_ADDRESSING — Allocate deterministic machine addresses.

Input: State from S2 (typed edges, canonical FQDNs)
Output: State with all addresses populated (nodes, edges, address table)

This is NOT indexing. It is governed symbolic identity →
deterministic machine address allocation. The compiler owns
semantic addressing forever — addresses are compile-time allocated,
never runtime-generated.
"""

from pgs_compiler.compiler.graph.addressing import allocate_addresses
from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.compiler.atoms.error_codes import ErrorCode


def s3_semantic_addressing(state: State) -> State:
    """
    S3 SEMANTIC_ADDRESSING: Allocate addresses to all governed identities.

    Pure function: State → State.

    Address space partitions:
        Nodes:       0x0000 — 0x3FFF  (16384 slots)
        Edge kinds:  0x4000 — 0x40FF  (256 slots)
        Node kinds:  0x4100 — 0x41FF  (256 slots)
        Outcomes:    0x5000 — 0x5FFF  (4096 slots)
        Transitions: 0x6000 — 0x6FFF  (4096 slots)
        Vocabulary:  0x7000 — 0x7FFF  (4096 slots)

    Args:
        state: State from S2 CANONICALIZE

    Returns:
        New State with addresses populated
    """
    state = state.with_stage("S3_SEMANTIC_ADDRESSING")

    try:
        addressed_graph, address_hash = allocate_addresses(state.graph)
    except Exception as e:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=f"Address allocation failed: {e}",
            phase="S3_SEMANTIC_ADDRESSING",
        ))

    state = state.with_graph(addressed_graph)
    state = state.with_metadata("address_hash", address_hash)
    state = state.with_metadata("address_table_size", len(addressed_graph.address_table))

    state = state.with_trace_events(TraceEvent.create(
        stage="S3_SEMANTIC_ADDRESSING",
        operation="addresses_allocated",
        detail={
            "address_table_size": len(addressed_graph.address_table),
            "address_hash": address_hash,
        },
        family=EventFamily.ADDRESSING.value,
    ))

    return state
