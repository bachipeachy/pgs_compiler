"""Semantic Model proof (the Semantic Dimension Model) — the guardrail made executable.

Asserts: (1) THE GUARDRAIL — every dimension of every artifact carries a derivation that is a structural
fact or an explicit `undetermined`; NEVER an inference, and no judgment dimension (e.g. `relevance`) is
ever produced (the Knowledge Partition Theorem applied to the model itself); (2) determinism; (3)
projections-as-queries — Discovery/Impact-shaped selections are `select(...)` over one model; (4)
derivation coverage — domain/kind are fully determined, subdomain/visibility partially (the `undetermined`
count is the signal for the next compiler-model enrichment, e.g. first-class subdomain).

Run: PGS_WORKSPACE=/abs python -m pgs_compiler.inspection._semantic_model_selftest
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pgs_compiler.inspection.loader import Workspace
from pgs_compiler.inspection.traversal import SemanticGraph
from pgs_compiler.inspection.semantic_model import (
    compute_semantic_model, select, derivation_coverage, DIMENSIONS, UNDETERMINED)

PASS, FAIL = "✅", "❌"
_ALLOWED_DERIVATIONS = {"structural:fqdn", "structural:graph_node", "declared:module_path",
                        "structural:reachability", UNDETERMINED}


def _check(cond: bool, label: str) -> bool:
    print(f"  {PASS if cond else FAIL} {label}")
    return cond


def main() -> int:
    ok = True
    ws = Workspace(Path(os.environ["PGS_WORKSPACE"]))
    graph = SemanticGraph(ws)
    model = compute_semantic_model(graph, ws)
    print(f"semantic model: {len(model)} artifacts × {len(DIMENSIONS)} dimensions")

    # 1. THE GUARDRAIL — every dimension deterministically derived (structural or explicit undetermined),
    #    never an inference; no judgment dimension is ever produced.
    all_derived = all(
        d.derivation in _ALLOWED_DERIVATIONS and d.derivation != ""
        for dims in model.values() for d in dims.values())
    ok &= _check(all_derived, "GUARDRAIL: every dimension carries a structural/declared derivation "
                 "(never an inference)")
    ok &= _check(all(set(dims) <= set(DIMENSIONS) for dims in model.values())
                 and "relevance" not in DIMENSIONS,
                 "no judgment dimension exists (relevance is disposition, not a dimension)")

    # 2. determinism
    model2 = compute_semantic_model(graph, ws)
    same = all(model[fq][d].to_dict() == model2[fq][d].to_dict()
               for fq in model for d in model[fq])
    ok &= _check(same, "determinism: identical model across two computations")

    # 3. projections-as-queries — a bespoke traversal becomes a select() over one model
    wfs = select(model, domain="blockchain", kind="WF")
    ok &= _check(len(wfs) > 0 and all(fq.startswith("blockchain::") and "::WF_" in fq for fq in wfs),
                 f"query {{domain=blockchain, kind=WF}} → {len(wfs)} workflows (projection as a query)")
    owned = select(model, owner_subdomain="consensus_pos")
    part = select(model, participating_subdomains="consensus_pos")
    ok &= _check(len(owned) > 0 and set(owned) <= set(part),
                 f"query {{owner_subdomain=consensus_pos}} → {len(owned)} owned ⊆ "
                 f"{{participating=consensus_pos}} → {len(part)} used (ownership ⊆ participation)")

    # ownership vs participation are DISTINCT dimensions (the correction): ownership single-valued +
    # immutable-by-derivation (from module_path); participation multi-valued (a list).
    ex = next((m for m in model.values() if m["owner_subdomain"].value), None)
    ok &= _check(ex is not None and not isinstance(ex["owner_subdomain"].value, list)
                 and isinstance(ex["participating_subdomains"].value, list),
                 "owner_subdomain is single-valued (ownership); participating_subdomains is a list "
                 "(participation) — one concept each")
    ok &= _check(all(m["owner_subdomain"].derivation in ("declared:module_path", UNDETERMINED)
                     for m in model.values()),
                 "ownership derived from module_path (declared/immutable), never from graph references")
    pub = select(model, visibility="public")
    print(f"  visibility=public → {len(pub)} (owned artifacts a DIFFERENT subdomain functionally uses)")

    # 4. derivation coverage — domain/kind fully determined; owner_subdomain partial (the signal)
    cov = derivation_coverage(model)
    print("  derivation coverage:", {d: cov[d] for d in DIMENSIONS})
    ok &= _check(cov["domain"]["undetermined"] == 0 and cov["kind"]["undetermined"] == 0,
                 "domain + kind are fully determined (trivially structural)")
    ok &= _check(cov["owner_subdomain"]["determined"] > 150,
                 f"owner_subdomain compiler-emitted for {cov['owner_subdomain']['determined']} artifacts "
                 "(the rest are domain-level shared / federation-level — correctly not subdomain-owned)")

    print(f"\n{'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
