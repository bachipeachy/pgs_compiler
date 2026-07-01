"""Impact Projection — the second Semantic Projection (SPP · DP5), proving the projection LAYER.

Discovery Projection answers *"what exists in the neighbourhood of a transformation"*; Impact Projection
answers *"what depends on this artifact"* — the blast radius of changing it. It is a second INSTANCE of
the Semantic Projection Protocol: same Projection Identity, same determinism, same Projection Closure,
built by REUSING `semantic_projection.build_projection` — not by copying it. That reuse is the proof that
"semantic projection" is a layer, not a one-off feature.

Two properties Discovery could not have (SPP.11c) hold here, because the subject artifact ALREADY EXISTS
and so do its consumers:
  * a real consumer graph — impact is a fact about the *current* snapshot, not a future change;
  * a working **Public Semantic Surface** — the cross-boundary consumers ARE the artifact's published
    contract (who depends on it across a boundary), so a change there is contract-affecting. (v0
    realizes "boundary" at the domain level, which is in the FQDN; subdomain-level awaits first-class
    subdomain in the graph — the recurring compiler-model gap.)

Per the Knowledge Partition Theorem it acquires and presents evidence, never interprets it: it reports
WHO is impacted; whether that impact MATTERS to a given change is the worker's judgment.
"""

from __future__ import annotations

from typing import Any

from pgs_compiler.inspection.semantic_projection import build_projection, snapshot_fingerprint

INCLUSION_CONSUMER = "consumer"   # included because it (transitively) references the subject


def _domain_of(fqdn: str) -> str:
    return fqdn.split("::", 1)[0] if "::" in fqdn else ""


def compute_impact_projection(graph, target: str) -> dict[str, Any]:
    """Compute the Impact Projection for `target` over `graph`. Pure and deterministic."""
    target_domain = _domain_of(target)
    closure = graph.refs(target, transitive=True)   # transitive consumers, each with kind + depth

    # EXISTING (positive evidence) — the blast radius; every node carries inclusion provenance + depth
    impacted = [
        {"fqdn": r["fqdn"], "kind": r["kind"], "depth": r["depth"],
         "included_because": INCLUSION_CONSUMER}
        for r in sorted(closure, key=lambda r: (r["depth"], r["fqdn"]))
    ]
    direct = sorted(r["fqdn"] for r in closure if r["depth"] == 1)

    # PUBLIC SEMANTIC SURFACE — consumers across the subject's boundary (v0: cross-domain). This is the
    # artifact's published contract: who depends on it from outside, so changing it is contract-affecting.
    public_surface = sorted(r["fqdn"] for r in closure if _domain_of(r["fqdn"]) != target_domain)

    by_kind: dict[str, int] = {}
    for r in closure:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1

    evidence = {
        "impacted": impacted,
        "direct": direct,
        "public_surface": public_surface,
        "by_kind": dict(sorted(by_kind.items())),
    }
    return build_projection(
        projection_type="impact",
        source_snapshot_id=snapshot_fingerprint(graph),
        subject=target,
        bounds={"realization": "transitive consumer closure", "public_boundary": "domain"},
        evidence=evidence,
    )
