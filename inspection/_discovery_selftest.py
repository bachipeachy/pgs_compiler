"""Discovery Projection proof (SPP · DP1) — validated against the blockchain/chain stage-2 test data.

This is the experiment that motivated the Semantic Projection Protocol made deterministic. The Guided
S2 came out ~half the depth of the golden domain model because the worker had to *search* the
neighbourhood. Here the PLATFORM computes that neighbourhood. The proof asserts:

  * Closure/completeness — the projection CONTAINS the neighbourhood a deep S2 needs (the artifacts a
    shallow search misses): block proposal, consensus loop, proposer selection, mempool, wallet,
    validator registry.
  * Negative evidence — absent concepts (GENESIS / LEDGER / BOOTSTRAP) are first-class findings.
  * Structural observations are RELIABLE-ONLY — the projection emits orphans/dangling references but
    NOT event producer-analysis (the graph models no producer→event edge, so it would be a false
    positive). The committed event is surfaced as neighbourhood the worker dispositions, not as an
    unreliable platform claim.
  * Projection Closure invariant — every existing node carries an inclusion reason.
  * Determinism — same snapshot + same scope ⇒ identical projection_id.

Run:  PGS_WORKSPACE=/abs python -m pgs_compiler.inspection._discovery_selftest
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pgs_compiler.inspection.loader import Workspace
from pgs_compiler.inspection.traversal import SemanticGraph
from pgs_compiler.inspection.discovery import TransformationScope, compute_discovery_projection

PASS, FAIL = "✅", "❌"

# The declared transformation scope for blockchain/chain — the concept tokens the CR carries
# (business vocabulary + system beliefs). v0's realization of "declared transformation scope".
CHAIN_TOKENS = (
    "BLOCK", "COMMIT", "CONSENSUS", "PROPOSE", "PROPOSER", "VALIDATOR", "WALLET",
    "TRANSACTION", "MEMPOOL", "SLOT", "GENESIS", "LEDGER", "BOOTSTRAP", "MINT",
)

# The neighbourhood a deep S2 must reach — the artifacts the shallow Guided S2 missed by searching.
GOLDEN_NEIGHBOURHOOD = {
    "blockchain::CC_FORM_BLOCK_V0",
    "blockchain::RB_RUN_CONSENSUS_LOOP_V0",
    "blockchain::CC_SELECT_PROPOSER_V0",
    "blockchain::CC_QUERY_MEMPOOL_TXS_V0",
    "blockchain::CC_CREATE_WALLET_RECORD_V0",
    "blockchain::CC_WRITE_VALIDATOR_RECORD_V0",
}
ABSENT_EXPECTED = {"GENESIS", "LEDGER", "BOOTSTRAP"}
ORPHAN_EVENT = "blockchain::EV_BLOCK_COMMITTED_V0"


def _check(cond: bool, label: str) -> bool:
    print(f"  {PASS if cond else FAIL} {label}")
    return cond


def _workspace() -> Workspace:
    root = os.environ.get("PGS_WORKSPACE")
    if hasattr(Workspace, "resolve"):
        return Workspace.resolve(None)
    return Workspace(Path(root))


def main() -> int:
    ok = True
    graph = SemanticGraph(_workspace())
    scope = TransformationScope(domain="blockchain", subdomain="chain", concept_tokens=CHAIN_TOKENS)
    proj = compute_discovery_projection(graph, scope)

    ident = proj["projection_identity"]
    ev = proj["evidence"]
    existing_fqdns = {n["fqdn"] for n in ev["existing"]}
    print(f"projection: {len(existing_fqdns)} existing nodes · {len(ev['relationships'])} relationships "
          f"· {len(ev['absent'])} absent · roots={len(ident['bounds']['roots'])}")

    # 1. closure/completeness — the golden neighbourhood is present (supplied, not searched)
    missing = GOLDEN_NEIGHBOURHOOD - existing_fqdns
    ok &= _check(not missing, f"projection contains the golden S2 neighbourhood"
                 + (f" (MISSING {sorted(missing)})" if missing else ""))

    # 2. negative evidence — absent concepts are first-class
    absent_concepts = {a["concept"] for a in ev["absent"]}
    ok &= _check(ABSENT_EXPECTED <= absent_concepts,
                 f"negative evidence carries absent concepts {sorted(ABSENT_EXPECTED)} "
                 f"(got {sorted(absent_concepts)})")

    # 3. reliability — the committed event is surfaced as neighbourhood (worker dispositions it),
    #    and the projection does NOT over-claim a producer-analysis the edge model can't support.
    ok &= _check(ORPHAN_EVENT in existing_fqdns and "missing_producers" not in ev["structural"],
                 f"structural is reliable-only: {ORPHAN_EVENT.split('::')[1]} in neighbourhood, "
                 "no unreliable missing-producer claim emitted")

    # 4. Projection Closure — every existing node carries a non-empty inclusion reason
    reasons = {n["included_because"] for n in ev["existing"]}
    closure_ok = all(n["included_because"] for n in ev["existing"])
    ok &= _check(closure_ok and reasons <= {"root", "dependency", "reference"},
                 f"Projection Closure: every node has inclusion provenance {sorted(reasons)}")

    # 5. identity present
    ok &= _check(ident["projection_id"].startswith("sha256:")
                 and ident["source_snapshot_id"].startswith("sha256:"),
                 "projection identity carries projection_id + source_snapshot_id")

    # 6. determinism — a second computation is byte-identical on the id
    proj2 = compute_discovery_projection(graph, scope)
    ok &= _check(proj2["projection_identity"]["projection_id"] == ident["projection_id"],
                 "determinism: identical projection_id across two computations")

    # informative: neighbourhood by kind (the depth now supplied to the worker)
    bykind: dict[str, int] = {}
    for n in ev["existing"]:
        bykind[n["kind"]] = bykind.get(n["kind"], 0) + 1
    print("  neighbourhood by kind:", dict(sorted(bykind.items())))

    print(f"\n{'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
