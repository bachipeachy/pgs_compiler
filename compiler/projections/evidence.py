"""
Evidence projection — dual-form observability/replay substrate.

Derives from PIRGraph. Produces the correlation substrate that bridges
canonical (FQDN) and tokenized (integer address) semantic spaces.

Workspace target: evidence_snapshot/<structure_id>/

Projection content:
    - nodes: all graph nodes in dual form (FQDN + address + kind)
    - edges: all graph edges in dual form (source/target FQDN + address, kind, metadata)
    - event_catalog: EV_ nodes with declared schemas for trace event validation

Purpose:
    - Runtime trace decoding (FQDN ↔ address correlation)
    - Compact telemetry (tokenized trace events)
    - Silicon debugging (address-level trace inspection)
    - Distributed replay (portable trace reconstruction)
    - Trace event schema validation (EV_ schemas)

Design constraint:
    Evidence projection and tokenized projection should evolve together.
    Evidence explains topology; tokenization optimizes topology.
    Together they create inspectable high-performance governed
    execution topology.

    Every entity appears in BOTH semantic spaces — this IS the
    correlation substrate.
"""

from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.graph.graph import Graph
from pgs_compiler.compiler.graph.hashing import compute_projection_hash
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.graph.types import NodeKind
from pgs_compiler.compiler.projections import (
    COMPILER_VERSION,
    PROJECTION_SCHEMA_VERSION,
    Projection,
    ProjectionType,
    make_metadata,
)


def project_evidence(graph: Graph) -> tuple[Projection, list[TraceEvent]]:
    """
    Generate the evidence projection from Graph.

    Produces dual-form (FQDN + address) representation of every node
    and edge in the graph, plus an event catalog with EV_ schemas.

    Content shape:
        {
            "nodes": [{"fqdn": "...", "address": N, "kind": "CC", "kind_address": M}, ...],
            "edges": [{"source_fqdn": "...", "target_fqdn": "...",
                        "source_address": N, "target_address": M,
                        "kind": "NODE_NEXT", "kind_address": K,
                        "metadata": {...}}, ...],
            "event_catalog": [{"fqdn": "...", "address": N,
                                "kind": "EV", "kind_address": M,
                                "schema": {...}}, ...],
        }

    Args:
        graph: Fully constructed PIRGraph with addresses populated

    Returns:
        Tuple of (Projection with evidence content, trace events)
    """
    trace: list[TraceEvent] = []

    # Nodes: dual-form, sorted by address
    nodes: list[dict[str, Any]] = []
    for fqdn in sorted(graph.nodes):
        node = graph.nodes[fqdn]
        if node.address < 0:
            continue
        kind_key = f"node_kind::{node.kind.value}"
        nodes.append({
            "fqdn": node.fqdn,
            "address": node.address,
            "kind": node.kind.value,
            "kind_address": graph.address_table.get(kind_key, -1),
        })
    nodes.sort(key=lambda n: n["address"])

    # Edges: dual-form, sorted by (source_address, target_address, kind_address)
    edges: list[dict[str, Any]] = []
    for edge in graph.edges:
        if edge.source_address < 0 or edge.target_address < 0:
            continue
        edges.append({
            "source_fqdn": edge.source_fqdn,
            "target_fqdn": edge.target_fqdn,
            "source_address": edge.source_address,
            "target_address": edge.target_address,
            "kind": edge.kind.value,
            "kind_address": edge.kind_address,
            "metadata": _deep_dict(edge.metadata),
        })
    edges.sort(key=lambda e: (e["source_address"], e["target_address"], e["kind_address"]))

    # Event catalog: EV_ nodes with declared schemas
    event_catalog: list[dict[str, Any]] = []
    ev_kind_key = f"node_kind::{NodeKind.EV.value}"
    ev_kind_address = graph.address_table.get(ev_kind_key, -1)
    for fqdn in sorted(graph.nodes):
        node = graph.nodes[fqdn]
        if node.kind != NodeKind.EV or node.address < 0:
            continue
        frontmatter = dict(node.frontmatter) if node.frontmatter else {}
        core = frontmatter.get("core", {})
        schema = _deep_dict(core.get("schema", {}))
        event_catalog.append({
            "fqdn": node.fqdn,
            "address": node.address,
            "kind": NodeKind.EV.value,
            "kind_address": ev_kind_address,
            "schema": schema,
        })
    event_catalog.sort(key=lambda e: e["address"])

    content = {
        "nodes": nodes,
        "edges": edges,
        "event_catalog": event_catalog,
    }

    projection_hash = compute_projection_hash(content)

    metadata = make_metadata(
        projection_type=ProjectionType.EVIDENCE,
        graph_topology_hash=graph.topology_hash,
        graph_address_hash=graph.address_hash,
        projection_hash=projection_hash,
        compiler_version=COMPILER_VERSION,
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
    )

    projection = Projection(
        projection_type=ProjectionType.EVIDENCE,
        metadata=metadata,
        content=MappingProxyType(content),
    )

    trace.append(TraceEvent.create(
        stage="S6_PROJECT",
        operation="evidence_projected",
        detail={
            "node_count": len(nodes),
            "edge_count": len(edges),
            "ev_schema_count": len(event_catalog),
            "projection_hash": projection_hash,
        },
        family=EventFamily.PROJECTION.value,
    ))

    return projection, trace


def _deep_dict(obj: Any) -> Any:
    """Recursively convert MappingProxyType and other mappings to plain dicts."""
    if hasattr(obj, "items"):
        return {k: _deep_dict(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_deep_dict(item) for item in obj]
    return obj
