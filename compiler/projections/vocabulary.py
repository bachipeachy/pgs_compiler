"""
Vocabulary projection — per-structure address space realization.

Derives from PIRGraph address tables (Graph.address_table, Graph.reverse_table).
Produces forward and reverse lookup tables mapping semantic identities to
deterministic integer addresses.

Workspace target: semantic_vocabulary/<structure_id>/

Projection content:
    - forward: {hex_address: identity_string} for all identity classes
    - reverse: {identity_string: hex_address} for all identity classes

Purpose:
    - Debug substrate (resolve addresses to human-readable names)
    - Trace decoding substrate (reconstruct symbolic traces from tokenized)
    - Runtime symbol substrate (symbol tables for debuggers)
    - Distributed replay (portable address <-> identity mapping)
    - Silicon image generation (bounded deterministic memory images)

Architectural doctrine:
    - Semantic ontology is global (Phase Type B)
    - Semantic address space is structure-local (this projection)
    - Each structure build defines its own admissible universe, topology,
      and deterministic address space
    - Per-structure address spaces required for: isolated silicon images,
      federated compilation, partial topology loading, bounded runtime
      substrates, independent projection deployment
    - Vocabulary projection is a lookup substrate, not an execution topology
"""

from types import MappingProxyType

from pgs_compiler.compiler.graph.graph import Graph
from pgs_compiler.compiler.graph.hashing import compute_projection_hash
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.projections import (
    COMPILER_VERSION,
    PROJECTION_SCHEMA_VERSION,
    Projection,
    ProjectionType,
    make_metadata,
)


def project_vocabulary(graph: Graph) -> tuple[Projection, list[TraceEvent]]:
    """
    Generate the vocabulary projection from Graph.

    Derives entirely from Graph.address_table (forward: identity -> int)
    and Graph.reverse_table (reverse: int -> identity), populated by
    S3 SEMANTIC_ADDRESSING.

    Content shape:
        {
            "forward": {"0x0000": "blockchain::CC_...", ...},
            "reverse": {"blockchain::CC_...": "0x0000", ...},
        }

    Args:
        graph: Fully constructed PIRGraph with addresses populated

    Returns:
        Tuple of (Projection with vocabulary content, trace events)
    """
    trace: list[TraceEvent] = []

    # Build forward table: int_address -> identity_string (hex keys, sorted by address)
    forward: dict[str, str] = {}
    for address, identity in sorted(graph.reverse_table.items()):
        forward[f"0x{address:04X}"] = identity

    # Build reverse table: identity_string -> hex_address (sorted by identity)
    reverse: dict[str, str] = {}
    for identity, address in sorted(graph.address_table.items()):
        reverse[identity] = f"0x{address:04X}"

    content = {"forward": forward, "reverse": reverse}

    projection_hash = compute_projection_hash(content)

    metadata = make_metadata(
        projection_type=ProjectionType.VOCABULARY,
        graph_topology_hash=graph.topology_hash,
        graph_address_hash=graph.address_hash,
        projection_hash=projection_hash,
        compiler_version=COMPILER_VERSION,
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
    )

    projection = Projection(
        projection_type=ProjectionType.VOCABULARY,
        metadata=metadata,
        content=MappingProxyType(content),
    )

    trace.append(TraceEvent.create(
        stage="S6_PROJECT",
        operation="vocabulary_projected",
        detail={
            "address_count": len(graph.address_table),
            "projection_hash": projection_hash,
        },
        family=EventFamily.PROJECTION.value,
    ))

    return projection, trace
