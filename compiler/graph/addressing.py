"""
Semantic address allocation.

This is NOT indexing. It is governed symbolic identity →
deterministic machine address allocation.

All governed identities are allocated integer addresses:
- Node FQDNs
- Edge kinds
- Result surfaces (CC outcomes)
- Transition conditions
- Artifact kinds
- Vocabulary entries

Addresses are:
- Compile-time allocated (never runtime-generated)
- Deterministic (same identities → same addresses)
- Reproducible (same input → same allocation)
- Immutable for a snapshot version

The compiler owns semantic addressing forever.
"""

import hashlib
import json
from types import MappingProxyType

from pgs_compiler.compiler.graph.types import NodeKind, EdgeKind
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.edge import Edge
from pgs_compiler.compiler.graph.graph import Graph, GraphBuilder


# Address space partitions
# Nodes:       0x0000 — 0x3FFF  (16384 slots)
# Edge kinds:  0x4000 — 0x40FF  (256 slots)
# Node kinds:  0x4100 — 0x41FF  (256 slots)
# Outcomes:    0x5000 — 0x5FFF  (4096 slots)
# Transitions: 0x6000 — 0x6FFF  (4096 slots)
# Vocabulary:  0x7000 — 0x7FFF  (4096 slots)

_NODE_BASE = 0x0000
_EDGE_KIND_BASE = 0x4000
_NODE_KIND_BASE = 0x4100
_OUTCOME_BASE = 0x5000
_TRANSITION_BASE = 0x6000
_VOCABULARY_BASE = 0x7000


def allocate_addresses(graph: Graph) -> tuple[Graph, str]:
    """
    Allocate deterministic semantic addresses to all governed identities.

    This is the core operation of S3 SEMANTIC_ADDRESSING.

    Address allocation rule: Sort all identities within each partition
    lexicographically, assign sequential integers from partition base.
    This is deterministic given the same set of identities.

    Args:
        graph: Graph with canonical FQDNs (output of S2 CANONICALIZE)

    Returns:
        Tuple of (new Graph with addresses populated, address_hash)
    """
    address_table: dict[str, int] = {}

    # --- Node FQDNs (primary identity addresses) ---
    sorted_fqdns = sorted(graph.nodes.keys())
    for i, fqdn in enumerate(sorted_fqdns):
        address_table[fqdn] = _NODE_BASE + i

    # --- Edge kinds (fixed enum ordinal from partition base) ---
    for i, kind in enumerate(sorted(EdgeKind, key=lambda k: k.value)):
        address_table[f"edge_kind::{kind.value}"] = _EDGE_KIND_BASE + i

    # --- Node kinds (fixed enum ordinal from partition base) ---
    for i, kind in enumerate(sorted(NodeKind, key=lambda k: k.value)):
        address_table[f"node_kind::{kind.value}"] = _NODE_KIND_BASE + i

    # --- Result surfaces (CC outcomes) ---
    # Outcomes are declared in CC.frontmatter.core.result_status_contract.allowed
    outcomes: set[str] = set()
    for node in graph.nodes.values():
        if node.kind == NodeKind.CC:
            core = node.frontmatter.get("core", {})
            rsc = core.get("result_status_contract", {})
            for outcome_name in rsc.get("allowed", []):
                if outcome_name:
                    outcomes.add(str(outcome_name))

    for i, outcome in enumerate(sorted(outcomes)):
        address_table[f"outcome::{outcome}"] = _OUTCOME_BASE + i

    # --- Transition conditions (WF routing conditions) ---
    # Transitions are the keys of WF node `next` dicts — i.e. CC outcome names
    # used as routing conditions in the workflow graph.
    transitions: set[str] = set()
    for node in graph.nodes.values():
        if node.kind == NodeKind.WF:
            core = node.frontmatter.get("core", {})
            for wf_node in core.get("nodes", {}).values():
                if isinstance(wf_node, dict):
                    for condition in wf_node.get("next", {}).keys():
                        if condition:
                            transitions.add(str(condition))

    for i, transition in enumerate(sorted(transitions)):
        address_table[f"transition::{transition}"] = _TRANSITION_BASE + i

    # --- Compute address hash ---
    address_hash = _compute_address_hash(address_table)

    # --- Build new graph with addresses populated ---
    builder = GraphBuilder.from_graph(graph)
    builder.set_address_table(address_table)
    builder.set_address_hash(address_hash)

    # Update node addresses
    for fqdn, node in graph.nodes.items():
        builder.replace_node(fqdn, address=address_table[fqdn])

    # Rebuild edges with addresses
    builder._edges = []
    for edge in graph.edges:
        source_addr = address_table.get(edge.source_fqdn, -1)
        target_addr = address_table.get(edge.target_fqdn, -1)
        kind_addr = address_table.get(f"edge_kind::{edge.kind.value}", -1)
        builder.add_edge(edge.replace(
            source_address=source_addr,
            target_address=target_addr,
            kind_address=kind_addr,
        ))

    new_graph = builder.build()
    return new_graph, address_hash


def _compute_address_hash(address_table: dict[str, int]) -> str:
    """
    Compute deterministic hash of address allocation.

    The hash covers the complete mapping of identity → address.
    Same identities + same allocation = same hash.
    """
    # Deterministic serialization: sorted keys
    canonical = json.dumps(
        sorted(address_table.items()),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
