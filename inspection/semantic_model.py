"""Semantic Model — the canonical substrate under the semantic projections (the Semantic Dimension Model).

Every protocol artifact is annotated with **semantic dimensions** (facets); the typed graph already
carries semantic **relationships** (contains / binds / governs / routes / references). A semantic
projection then becomes a **query over this model**, not an engineered traversal. Subdomain is one
dimension, never privileged.

**Guardrail — the Knowledge Partition Theorem applied to the model itself.** Every dimension value is
DETERMINISTICALLY DERIVED from the protocol — a *structural fact* or a *governed declaration* — and
carries its **derivation source**. A property that would require inference or judgment is NOT admitted
here (that is a *disposition*, worker-owned, DP4). A value the protocol does not determine is recorded as
`undetermined` (honest), never guessed. Enforced by construction: a `Dimension` cannot exist without a
derivation, and no judgment dimension (e.g. `relevance`) is ever produced.

This is the substrate; refactoring Discovery / Impact to *query* it (rather than embed traversal) is the
next step. v0 carries the dimensions that are cleanly derivable today; the `undetermined` coverage it
reports is itself the signal for which compiler-model enrichments (e.g. first-class subdomain) come next.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Derivation sources — HOW a dimension value was obtained (the guardrail, made explicit).
STRUCT_FQDN = "structural:fqdn"                          # read off the FQDN
STRUCT_NODE = "structural:graph_node"                    # the artifact kind, from the graph
DECLARED_MODULE_PATH = "declared:module_path"            # OWNERSHIP — compiler-emitted from module org
STRUCT_REACHABILITY = "structural:reachability"          # PARTICIPATION — functional reachability over ownership
UNDETERMINED = "undetermined"                            # the protocol does not determine it (never guessed)

# Functional (execution/data) edges — the relationships that carry a real dependency. GOVERNED_BY and
# other governance/evidence edges are excluded: participation is about which subdomains *functionally
# use* an artifact, not which rules govern it.
FUNCTIONAL_EDGES = frozenset({
    "WF_CONTAINS_NODE", "WF_START", "WF_BINDS_RB", "NODE_NEXT",
    "CC_BINDS_CS", "CC_BINDS_CT", "RB_MAPS", "TI_INVOKES_WF",
})

# Ownership vs participation are DIFFERENT dimensions (each dimension = exactly one concept):
#   owner_subdomain          — single-valued, IMMUTABLE, governed protocol ownership (who OWNS it);
#   participating_subdomains — multi-valued, computed, functional reachability (which subdomains USE it).
# Ownership is stable; a consumer in another subdomain changes participation, never ownership.
DIMENSIONS = ("domain", "kind", "owner_subdomain", "participating_subdomains", "visibility")


@dataclass(frozen=True)
class Dimension:
    """A dimension value plus the derivation that produced it. `derivation` is never empty — that is the
    guardrail: no dimension exists without a deterministic source (or an explicit `undetermined`)."""

    value: Any
    derivation: str

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "derivation": self.derivation}


def compute_semantic_model(graph, workspace) -> dict[str, dict[str, Dimension]]:
    """Annotate every graph artifact with its deterministically-derived semantic dimensions."""
    index = workspace.artifact_index.get("artifacts", {})
    owner: dict[str, str | None] = {fq: (index.get(fq) or {}).get("owner_subdomain") for fq in graph.nodes}

    def functional_consumers(fqdn: str) -> set[str]:
        """Transitive artifacts that FUNCTIONALLY reach `fqdn` (its consumers over execution/data edges)."""
        seen: set[str] = set()
        frontier = [fqdn]
        while frontier:
            nxt: list[str] = []
            for x in frontier:
                for e in graph.in_edges(x):
                    if e.kind in FUNCTIONAL_EDGES and e.source not in seen:
                        seen.add(e.source)
                        nxt.append(e.source)
            frontier = nxt
        return seen

    model: dict[str, dict[str, Dimension]] = {}
    for fqdn, kind in graph.nodes.items():
        own = owner.get(fqdn)
        # participation — the subdomains whose artifacts functionally reach this one (+ its own owner).
        part = {owner[c] for c in functional_consumers(fqdn) if owner.get(c)}
        if own:
            part.add(own)
        participating = sorted(part)

        # visibility — public iff a subdomain OTHER than the owner participates; internal if only the
        # owner; undetermined when the artifact has no owner (domain/federation-level, not subdomain-owned).
        if not own:
            visibility = Dimension(None, UNDETERMINED)
        elif set(participating) - {own}:
            visibility = Dimension("public", STRUCT_REACHABILITY)
        else:
            visibility = Dimension("internal", STRUCT_REACHABILITY)

        model[fqdn] = {
            "domain": Dimension(fqdn.split("::", 1)[0] if "::" in fqdn else None, STRUCT_FQDN),
            "kind": Dimension(kind, STRUCT_NODE),
            "owner_subdomain": Dimension(own, DECLARED_MODULE_PATH if own else UNDETERMINED),
            "participating_subdomains": Dimension(participating, STRUCT_REACHABILITY),
            "visibility": visibility,
        }
    return model


def _matches(dim: Dimension | None, wanted: Any) -> bool:
    if dim is None:
        return False
    val = dim.value
    if isinstance(val, list):
        return wanted in val
    return val == wanted


def select(model: dict[str, dict[str, Dimension]], **predicates: Any) -> list[str]:
    """A semantic projection AS A QUERY — the fqdns whose dimensions satisfy every predicate.

    Discovery/Impact/Authority projections are (increasingly) expressible as `select(...)` over this one
    model rather than as bespoke traversals — the point of the Semantic Dimension Model."""
    return sorted(fq for fq, dims in model.items()
                  if all(_matches(dims.get(k), v) for k, v in predicates.items()))


def derivation_coverage(model: dict[str, dict[str, Dimension]]) -> dict[str, dict[str, int]]:
    """Per-dimension: how many artifacts are determined vs undetermined. The `undetermined` counts are
    the feedback signal for which compiler-model enrichment comes next (e.g. first-class subdomain)."""
    cov: dict[str, dict[str, int]] = {d: {"determined": 0, "undetermined": 0} for d in DIMENSIONS}
    for dims in model.values():
        for d in DIMENSIONS:
            dim = dims.get(d)
            key = "undetermined" if (dim is None or dim.derivation == UNDETERMINED) else "determined"
            cov[d][key] += 1
    return cov
