"""Semantic Projection Protocol — the shared contract every semantic projection satisfies (SPP · DP5).

A semantic projection is a governed, deterministic, snapshot-addressable view over the protocol graph.
This module is the *contract* — the thing that makes "semantic projections" a **layer**, not a set of
one-off features. Discovery Projection (DP1) and Impact Projection (DP5) are instances of it; future
Authority / Transformation projections reuse it unchanged.

Per the Knowledge Partition Theorem, a projection is a **deterministic knowledge product**: it acquires,
normalizes, and presents evidence — it never interprets it (semantic relevance is the worker's).

The contract has three parts:
  * **Projection Identity** — projection_type, protocol_version, source_snapshot_id, subject, bounds,
    and a content `projection_id`. Snapshot-addressable: reproducible from the same snapshot + subject.
  * **Determinism** — same snapshot + same subject ⇒ identical `projection_id` (the id is a content
    hash over identity(sans id) + evidence).
  * **Projection Closure** — every evidence element carries a reason for inclusion; nothing appears
    "because traversal happened." (Enforced by each instance over its own evidence shape.)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

PROTOCOL_VERSION = "0"


def canonical(obj: Any) -> str:
    """Stable canonical serialization — sort_keys + compact separators (order/whitespace-invariant)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_of(obj: Any) -> str:
    """Canonical `sha256:…` digest of a json-serializable object."""
    return "sha256:" + hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def snapshot_fingerprint(graph) -> str:
    """Deterministic content fingerprint of the graph (sorted nodes + edges)."""
    payload = {
        "nodes": sorted((fqdn, kind) for fqdn, kind in graph.nodes.items()),
        "edges": [(e.source, e.kind, e.target) for e in graph.edges],
    }
    return sha256_of(payload)


def build_projection(*, projection_type: str, source_snapshot_id: str, subject: str,
                     bounds: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Assemble a semantic projection and stamp its content `projection_id` (determinism invariant).

    Every instance builds its own typed `evidence`; this fixes the identity shape + the id computation
    so all projections are addressable and comparable the same way."""
    identity: dict[str, Any] = {
        "projection_type": projection_type,
        "protocol_version": PROTOCOL_VERSION,
        "source_snapshot_id": source_snapshot_id,
        "subject": subject,
        "bounds": bounds,
    }
    projection = {"projection_identity": identity, "evidence": evidence}
    identity["projection_id"] = sha256_of(projection)   # over identity(sans id) + evidence
    return projection
