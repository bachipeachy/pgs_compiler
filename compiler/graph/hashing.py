"""
Topology and projection hashing.

Three hash levels for attestation and verification:

1. Topology hash — graph structure (nodes + edges + IR)
2. Address hash — semantic address allocation determinism
3. Projection hash — per-projection content verification

Together these enable:
- Attestation: snapshot produced by this compiler from this topology
- Runtime compatibility proof: runtime binary matches snapshot version
- Deterministic replay validation: trace produced against exact snapshot
"""

import hashlib
import json
from typing import Any

from pgs_compiler.compiler.graph.graph import Graph
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.edge import Edge


def compute_topology_hash(graph: Graph) -> str:
    """
    Compute deterministic hash of graph topology.

    Covers: all node identities + content hashes + all edges (typed).
    Does NOT cover: addresses (those are in address_hash).

    Same governed topology → same topology hash, regardless of
    when or where compilation happens.

    Args:
        graph: The Graph to hash

    Returns:
        SHA-256 hex digest of canonical topology representation
    """
    # Canonical node representation: sorted FQDNs with content hashes and kinds
    node_entries = []
    for fqdn in sorted(graph.nodes.keys()):
        node = graph.nodes[fqdn]
        node_entries.append({
            "fqdn": node.fqdn,
            "kind": node.kind.value,
            "content_hash": node.content_hash,
            "version": node.version,
        })

    # Canonical edge representation: sorted deterministically
    edge_entries = []
    for edge in graph.edges:  # Already sorted by build()
        edge_entries.append({
            "source": edge.source_fqdn,
            "target": edge.target_fqdn,
            "kind": edge.kind.value,
        })

    canonical = json.dumps(
        {"nodes": node_entries, "edges": edge_entries},
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_projection_hash(projection_data: Any) -> str:
    """
    Compute deterministic hash of a projection's serializable content.

    Used to verify that a materialized projection is a faithful
    derivation of the Graph.

    Args:
        projection_data: JSON-serializable projection content

    Returns:
        SHA-256 hex digest
    """
    canonical = json.dumps(
        projection_data,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
