"""
Tokenized projection — machine/silicon address-space topology.

Derives from PIRGraph nodes, edges, and adjacency. Produces integer-addressed
topology for compact runtimes and silicon execution targets.

Workspace target: tokenized_snapshot/<structure_id>/

Projection content:
    - nodes: [{address, kind}] sorted by address
    - edges: [{from, to, kind}] sorted by (from, to, kind)
    - adjacency: {str(node_address): [target_addresses]} outgoing only

Design constraints:
    - Inspectable deterministic JSON (diffable, replayable, debuggable)
    - All FQDNs replaced by compile-time allocated integer addresses
    - No binary packing, no compressed encoding, no implicit offsets
    - Addresses are snapshot-scoped deterministic (compile-time allocated,
      immutable for snapshot, reproducible, stable across rebuilds)

Foundational rule:
    Tokenized projection semantics must NEVER leak into canonical
    governance semantics. Governance reasons in symbolic semantic space.
    Tokenization is machine realization space. Separation is absolute.

Adjacency is a derived realization artifact, not semantic authority.
The Graph remains the sole topology authority.
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


def project_tokenized(graph: Graph) -> tuple[Projection, list[TraceEvent]]:
    """
    Generate the tokenized topology projection from Graph.

    Derives from Graph.nodes (with addresses), Graph.edges (with
    source/target/kind addresses), and Graph.outgoing (adjacency).
    All populated by S3 SEMANTIC_ADDRESSING.

    Content shape:
        {
            "nodes": [{"address": 0, "kind": 16640}, ...],
            "edges": [{"from": 0, "to": 5, "kind": 16384}, ...],
            "adjacency": {"0": [5, 12], ...},
        }

    Args:
        graph: Fully constructed PIRGraph with addresses populated

    Returns:
        Tuple of (Projection with tokenized content, trace events)
    """
    trace: list[TraceEvent] = []

    # Nodes: sorted by address
    nodes: list[dict[str, int]] = []
    for fqdn in sorted(graph.nodes):
        node = graph.nodes[fqdn]
        if node.address < 0:
            continue
        kind_key = f"node_kind::{node.kind.value}"
        nodes.append({
            "address": node.address,
            "kind": graph.address_table.get(kind_key, -1),
        })
    nodes.sort(key=lambda n: n["address"])

    # Edges: sorted by (from, to, kind)
    edges: list[dict[str, int]] = []
    for edge in graph.edges:
        if edge.source_address < 0 or edge.target_address < 0:
            continue
        edges.append({
            "from": edge.source_address,
            "to": edge.target_address,
            "kind": edge.kind_address,
        })
    edges.sort(key=lambda e: (e["from"], e["to"], e["kind"]))

    # Adjacency: outgoing map, keyed by string node address (JSON requires string keys)
    adjacency: dict[str, list[int]] = {}
    for fqdn in sorted(graph.nodes):
        node = graph.nodes[fqdn]
        if node.address < 0:
            continue
        outgoing = graph.get_outgoing(fqdn)
        targets = sorted({e.target_address for e in outgoing if e.target_address >= 0})
        if targets:
            adjacency[str(node.address)] = targets

    content = {"nodes": nodes, "edges": edges, "adjacency": adjacency}

    projection_hash = compute_projection_hash(content)

    metadata = make_metadata(
        projection_type=ProjectionType.TOKENIZED,
        graph_topology_hash=graph.topology_hash,
        graph_address_hash=graph.address_hash,
        projection_hash=projection_hash,
        compiler_version=COMPILER_VERSION,
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
    )

    projection = Projection(
        projection_type=ProjectionType.TOKENIZED,
        metadata=metadata,
        content=MappingProxyType(content),
    )

    trace.append(TraceEvent.create(
        stage="S6_PROJECT",
        operation="tokenized_projected",
        detail={
            "node_count": len(nodes),
            "edge_count": len(edges),
            "adjacency_count": len(adjacency),
            "projection_hash": projection_hash,
        },
        family=EventFamily.PROJECTION.value,
    ))

    return projection, trace
