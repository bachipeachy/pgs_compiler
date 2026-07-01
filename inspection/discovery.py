"""Discovery Projection — the first Semantic Projection (SPP · DP1).

A **Governed Semantic Neighborhood** over the compiled protocol graph, computed for a declared
transformation scope. The PLATFORM acquires evidence deterministically; it never *disposes* of it
(`RELEVANT` / `EXCLUDED` / `NEW` are the worker's judgments, not the projection's). The vocabulary
here describes the **evidence**, not traversal semantics.

Protocol (the abstraction, not an algorithm):

    Discovery Projection : Transformation Scope → Governed Semantic Neighborhood

The *realization* of the neighborhood is a compiler concern — v0 realizes it as the scope roots plus
their one-hop typed neighbours within the domain. The protocol governs the abstraction, so the
realization may evolve (typed / authority-aware expansion) without changing the contract. Likewise
the roots are derived from the *declared transformation scope*; v0's realization of that scope is a
set of concept tokens (upstream: the CR's business vocabulary / system beliefs / governance scope).

**First-class evidence types** (negative and structural evidence are peers of positive evidence):

    existing               positive — neighbourhood nodes that exist, each with inclusion provenance
    absent                 negative — declared concepts that resolve to zero artifacts
    structural             structural observations — only what the edge model supports *reliably*
                           (orphans, dangling references). Producer/consumer analysis for events is
                           deliberately NOT emitted: the current evidence graph materializes no
                           producer→event edge (every EV has zero in-edges), so a "missing producer"
                           signal would flag every event — a false positive. It returns once the
                           graph models event production; the platform never emits an unreliable claim.
    relationships          typed edges among neighbourhood nodes
    authority              governance artifacts in the neighbourhood (a view over `existing`)
    supporting_artifacts   assertions / test data backing the neighbourhood (a view over `existing`)

**Invariants**
  * *Determinism* — same snapshot + same scope ⇒ identical `projection_id`.
  * *Projection Closure* — every `existing` node carries a non-empty `included_because` reason;
    nothing appears "because traversal happened."
  * *Graph-supported claims only* — a semantic projection shall emit only claims the protocol graph
    supports. It never reproduces an unverified inference (see the dropped event producer-analysis):
    the graph is the authority, not the author's intuition. A claim the graph cannot support is a
    finding *about the graph* (feed it back into the compiler's model), not a claim to invent.

Terminology: *Governed* Semantic Neighborhood names the protocol (what the compiler must produce);
a *Computed* Semantic Neighborhood is the product (this deterministic artifact) — governance and
implementation kept cleanly separate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Discovery Projection is an INSTANCE of the shared Semantic Projection Protocol (SPP · DP5) — it reuses
# the contract (identity, determinism, snapshot fingerprint) rather than defining its own.
from pgs_compiler.inspection.semantic_projection import (
    build_projection, sha256_of, snapshot_fingerprint)

# Inclusion provenance — WHY a node is in the neighbourhood (Projection Closure).
INCLUSION_ROOT = "root"              # matched the declared transformation scope directly
INCLUSION_DEPENDENCY = "dependency"  # a root depends on it (outgoing edge)
INCLUSION_REFERENCE = "reference"    # it references a root (incoming edge)


@dataclass(frozen=True)
class TransformationScope:
    """The declared scope a Discovery Projection is computed for.

    `concept_tokens` is v0's realization of "declared transformation scope" — upstream these are
    derived from the CR's *structured* declarations (business vocabulary + governance scope). They
    seed roots AND define the absence frontier (a concept_token matching zero artifacts is negative
    evidence).

    `root_only_tokens` are noisier concepts named in the CR's *prose* (system-belief targets like a
    validator registry or slot processing). They seed roots too — but never contribute to `absent`,
    because prose harvest would otherwise manufacture false gaps. Keeping the derivation in the caller
    lets the *scope source* evolve without touching the projection."""

    domain: str
    concept_tokens: tuple[str, ...]
    subdomain: str | None = None
    root_only_tokens: tuple[str, ...] = ()
    excluded_tokens: tuple[str, ...] = ()   # CR-DECLARED out-of-scope concepts (S1 §12) — trimmed
    #                                         deterministically (a declaration, never a relevance judgment)


# Structural scaffolding kinds — never domain concepts, safe to trim from the evidence floor
# (test fixtures and compiler assertions are not part of the semantic neighborhood).
SCAFFOLDING_KINDS = frozenset({"TEST_DATA", "ASSERT"})


def _code(fqdn: str) -> str:
    return fqdn.split("::", 1)[1] if "::" in fqdn else fqdn


def _domain_of(fqdn: str) -> str:
    return fqdn.split("::", 1)[0] if "::" in fqdn else ""


def compute_discovery_projection(graph, scope: TransformationScope) -> dict[str, Any]:
    """Compute the Discovery Projection for `scope` over `graph`. Pure and deterministic."""
    domain = scope.domain
    tokens = [t.upper() for t in scope.concept_tokens]
    root_only = [t.upper() for t in scope.root_only_tokens if t.upper() not in set(tokens)]

    def in_domain(fqdn: str) -> bool:
        return _domain_of(fqdn) == domain

    def _hits(token: str, segments: set[str]) -> bool:
        # whole-segment match (with plural tolerance) — so 'ONCE' no longer matches 'NONCE' and
        # 'CHAIN' no longer matches 'BLOCKCHAIN'. A concept is a code segment, not an arbitrary infix.
        return token in segments or (token + "S") in segments

    # ── roots: in-domain nodes whose code carries a declared concept as a WHOLE SEGMENT ─────────
    # `concept_tokens` also define the absence frontier (matched_tokens); `root_only_tokens` seed
    # roots but never touch matched_tokens, so belief-prose concepts cannot manufacture false gaps.
    roots: dict[str, str] = {}
    matched_tokens: set[str] = set()
    for fqdn in graph.nodes:
        if not in_domain(fqdn):
            continue
        segments = set(_code(fqdn).upper().split("_"))
        for t in tokens:
            if _hits(t, segments):
                roots[fqdn] = INCLUSION_ROOT
                matched_tokens.add(t)
        if fqdn not in roots:
            for t in root_only:
                if _hits(t, segments):
                    roots[fqdn] = INCLUSION_ROOT
                    break

    # ── neighbourhood: roots + one-hop typed neighbours within the domain (v0 realization) ──
    included: dict[str, str] = dict(roots)   # fqdn → inclusion reason (Projection Closure)
    for r in sorted(roots):
        for d in graph.deps(r):
            fqdn = d["fqdn"]
            if in_domain(fqdn) and fqdn not in included:
                included[fqdn] = INCLUSION_DEPENDENCY
        for rf in graph.refs(r):
            fqdn = rf["fqdn"]
            if in_domain(fqdn) and fqdn not in included:
                included[fqdn] = INCLUSION_REFERENCE

    # ── DP1.3 Deterministic Evidence Floor Stabilization — trim only what is STRUCTURAL scaffolding
    # or CR-DECLARED out of scope. This is NEVER a relevance judgment (that is the worker's, via
    # disposition): meaning cannot be pre-computed from structure. Trimmed nodes are recorded in
    # `excluded` with a reason — nothing is silently dropped (the Projection-Closure discipline).
    excluded_toks = [t.upper() for t in scope.excluded_tokens]
    excluded: list[dict[str, str]] = []
    kept: dict[str, str] = {}
    for fqdn, why in included.items():
        if graph.node_kind(fqdn) in SCAFFOLDING_KINDS:
            excluded.append({"fqdn": fqdn, "reason": "scaffolding"})
        elif excluded_toks and any(
                _hits(t, set(_code(fqdn).upper().split("_"))) for t in excluded_toks):
            excluded.append({"fqdn": fqdn, "reason": "declared_out_of_scope"})
        else:
            kept[fqdn] = why
    included = kept
    excluded.sort(key=lambda e: e["fqdn"])

    nodes = set(included)

    # ── EXISTING (positive evidence) — every node carries its inclusion provenance ──────────
    existing = [
        {"fqdn": fqdn, "kind": graph.node_kind(fqdn), "included_because": included[fqdn]}
        for fqdn in sorted(nodes)
    ]

    # ── ABSENT (negative evidence) — declared concepts that resolve to zero artifacts ───────
    absent = [{"concept": t, "matches": 0} for t in sorted(set(tokens) - matched_tokens)]

    # ── STRUCTURAL observations — only what the edge model supports RELIABLY ─────────────────
    # Deliberately conservative: an orphan (no edges at all) and a dangling reference (edge to a
    # non-existent node) are unambiguous. Producer/consumer analysis for events is NOT emitted —
    # the graph materializes no producer→event edge, so it cannot be derived without false positives.
    orphans: list[str] = []
    dangling_references: list[dict[str, str]] = []
    for fqdn in sorted(nodes):
        ins = graph.in_edges(fqdn)
        outs = graph.out_edges(fqdn)
        if not ins and not outs:
            orphans.append(fqdn)
        for e in outs:
            if e.target not in graph.nodes:
                dangling_references.append({"source": fqdn, "kind": e.kind, "target": e.target})
    dangling_references.sort(key=lambda d: (d["source"], d["kind"], d["target"]))

    # ── RELATIONSHIPS — typed edges among neighbourhood nodes ───────────────────────────────
    rel_set = {
        (e.source, e.kind, e.target)
        for fqdn in nodes for e in graph.out_edges(fqdn) if e.target in nodes
    }
    relationships = [{"source": s, "kind": k, "target": t} for s, k, t in sorted(rel_set)]

    # ── AUTHORITY / SUPPORTING — classifications (views over `existing`) ─────────────────────
    authority = sorted(fqdn for fqdn in nodes if graph.node_kind(fqdn) == "GOVERNANCE")
    supporting_artifacts = sorted(
        fqdn for fqdn in nodes if graph.node_kind(fqdn) in ("ASSERT", "TEST_DATA"))

    evidence = {
        "existing": existing,
        "absent": absent,
        "structural": {
            "orphans": orphans,
            "dangling_references": dangling_references,
        },
        "relationships": relationships,
        "authority": authority,
        "supporting_artifacts": supporting_artifacts,
        # DP1.3 — what the platform deterministically trimmed and WHY (scaffolding / CR-declared
        # out-of-scope). Never a relevance judgment; recorded, never silently dropped.
        "excluded": excluded,
    }

    return build_projection(
        projection_type="discovery",
        source_snapshot_id=snapshot_fingerprint(graph),
        subject=f"{domain}/{scope.subdomain}" if scope.subdomain else domain,
        bounds={"realization": "roots+1hop-within-domain, minus scaffolding + declared-out-of-scope",
                "domain": domain, "roots": sorted(roots)},
        evidence=evidence,
    )
