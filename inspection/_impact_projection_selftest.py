"""Impact Projection proof (SPP · DP5) — the second projection proves the LAYER.

Asserts: (1) Impact Projection shares the Projection-Identity contract with Discovery (same identity
keys, both via `build_projection`) — so "semantic projection" is a reusable layer, not a one-off;
(2) it computes a real blast radius with Projection Closure + determinism; (3) the Public Semantic
Surface (cross-boundary consumers) is well-defined here because the subject already exists.

Run: PGS_WORKSPACE=/abs python -m pgs_compiler.inspection._impact_projection_selftest
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pgs_compiler.inspection.loader import Workspace
from pgs_compiler.inspection.traversal import SemanticGraph
from pgs_compiler.inspection.impact_projection import compute_impact_projection
from pgs_compiler.inspection.discovery import TransformationScope, compute_discovery_projection

PASS, FAIL = "✅", "❌"
_IDENTITY_KEYS = {"projection_type", "protocol_version", "source_snapshot_id", "subject",
                  "bounds", "projection_id"}


def _check(cond: bool, label: str) -> bool:
    print(f"  {PASS if cond else FAIL} {label}")
    return cond


def main() -> int:
    ok = True
    graph = SemanticGraph(Workspace(Path(os.environ["PGS_WORKSPACE"])))

    # pick a subject with a real blast radius (largest transitive consumer closure)
    target = max(graph.nodes, key=lambda fq: len(graph.refs(fq, transitive=True)))
    proj = compute_impact_projection(graph, target)
    ident, ev = proj["projection_identity"], proj["evidence"]
    print(f"impact subject: {target.split('::')[-1]}  → {len(ev['impacted'])} impacted "
          f"({len(ev['direct'])} direct, {len(ev['public_surface'])} cross-boundary) · by_kind={ev['by_kind']}")

    # 1. LAYER proof — identical Projection-Identity contract as Discovery
    disc = compute_discovery_projection(
        graph, TransformationScope(domain="blockchain", subdomain="chain",
                                   concept_tokens=("BLOCK", "COMMIT", "CHAIN")))
    ok &= _check(set(ident) == _IDENTITY_KEYS == set(disc["projection_identity"]),
                 "Impact + Discovery share ONE Projection-Identity contract (same keys)")
    ok &= _check(ident["projection_type"] == "impact"
                 and disc["projection_identity"]["projection_type"] == "discovery",
                 "each is a distinct instance (impact vs discovery) of the same protocol")

    # 2. real blast radius + Projection Closure
    ok &= _check(len(ev["impacted"]) > 0, f"non-empty blast radius ({len(ev['impacted'])} consumers)")
    ok &= _check(all(n["included_because"] == "consumer" and "depth" in n for n in ev["impacted"]),
                 "Projection Closure: every impacted node carries provenance + depth")

    # 3. determinism + snapshot-addressable
    proj2 = compute_impact_projection(graph, target)
    ok &= _check(proj2["projection_identity"]["projection_id"] == ident["projection_id"],
                 "determinism: identical projection_id across two computations")
    ok &= _check(ident["source_snapshot_id"].startswith("sha256:")
                 and ident["source_snapshot_id"] == disc["projection_identity"]["source_snapshot_id"],
                 "snapshot-addressable: both projections stamp the same source_snapshot_id")

    # 4. Public Semantic Surface is well-defined here (subject exists) — all cross-boundary consumers
    tdom = target.split("::", 1)[0]
    ok &= _check(all(f.split("::", 1)[0] != tdom for f in ev["public_surface"]),
                 f"Public Semantic Surface = cross-boundary consumers ({len(ev['public_surface'])})")

    print(f"\n{'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
