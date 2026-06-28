"""Intermediate Protocol Model (IPM) — the Compiler Semantic Interface (CSI) contract.

The IPM is the canonical, ordering-independent *semantic* representation of a compiled protocol,
exchanged between the compiler and independent verification. It is NOT a verification-internal
artifact: it is a first-class compiler product, the inverse-facing twin of the canonical projection.

    Governed Protocol → Forward Projector → Compiler → Semantic Substrate → Reverse Projector → IPM

Two builders produce an IPM, both from compiler outputs alone (never authoring markdown / CRs):
  * `build_forward_ipm`  — the *declared* model, assembled from canonical `frontmatter.core`
                           (the Definitional Layer of the semantic substrate).
  * `reverse_project`    — the *compiled* model, reconstructed from the evidence graph
                           (the Behavioral Layer); see `reverse.py`.

The Semantic Equivalence Oracle (in pgs_change_mgmt) consumes ONLY two IPMs and asserts they are
equivalent axis-by-axis. Behavioral axes (Workflow, …) prove **Semantic Preservation**; definitional
axes (Entities, Lifecycle, …) prove **Compilation Fidelity**. These are orthogonal compiler contracts.

VERSIONING: the IPM is itself a protocol. `IPM_VERSION` is stamped into every model so the oracle and
future protocol kinds (policies, security contracts, event models, …) can evolve without a redesign.

Increment 1 populates the Identity and Workflow axes (structural identity + behavioral reconstruction).
Later increments add CapabilityComposition, Bindings, Routing, Authority (behavioral) and Entities,
Lifecycle, Relationships, Invariants (definitional). The contract below is shaped for that growth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

IPM_VERSION = 1

# Synthetic terminal sentinel in WF `frontmatter.core.nodes`; not a real artifact node and absent
# from the behavioral layer (the evidence graph carries no EXIT node — terminal routing is edge-absence).
_EXIT = "EXIT"


@dataclass(frozen=True, order=True)
class IPMIdentity:
    """A protocol identity: an artifact's FQDN and its kind. The Identity axis is a set of these."""
    fqdn: str
    kind: str


@dataclass(frozen=True, order=True)
class IPMRouting:
    """A non-terminal workflow transition: `source` routes to `target` on outcome `outcome`."""
    source: str
    outcome: str
    target: str


@dataclass(frozen=True)
class IPMWorkflow:
    """A workflow's behavioral topology, normalized for equality across forward/reverse builders."""
    fqdn: str
    start_node: str
    nodes: tuple[IPMIdentity, ...]      # contained nodes (EXIT excluded), sorted
    routing: tuple[IPMRouting, ...]     # non-terminal transitions, sorted


@dataclass(frozen=True, order=True)
class IPMComposition:
    """One capability-composition step inside a CC: which capability it composes, where, of what kind.

    `op` (the operation verb) is intentionally absent: it is preserved only for CS steps, not CT steps
    (CC_BINDS_CT carries no `op`), so it is a Compilation-Fidelity detail in canonical frontmatter, not
    a Semantic-Preservation attribute of the behavioral layer.
    """
    cc: str
    pipeline_index: int
    step: str
    target: str
    kind: str                               # CT | CS


@dataclass(frozen=True, order=True)
class IPMStepRouting:
    """A capability-level disposition: CC step `step` routes outcome `outcome` to `disposition`."""
    cc: str
    step: str
    outcome: str
    disposition: str                        # continue | exit


@dataclass(frozen=True, order=True)
class IPMBinding:
    """A binding edge: WF_BINDS_RB (workflow→runtime binding) or RB_MAPS (binding→side effect)."""
    source: str
    target: str
    relation: str                           # WF_BINDS_RB | RB_MAPS


@dataclass(frozen=True, order=True)
class IPMAuthority:
    """A governance edge: artifact `artifact` is GOVERNED_BY `governed_by`."""
    artifact: str
    governed_by: str


# ---- definitional axes (the Definitional Layer: entity/invariant frontmatter.core) -------------

@dataclass(frozen=True, order=True)
class IPMAttribute:
    """One entity attribute (including the identity field): name, type, and shape."""
    entity: str
    name: str
    type: str
    cardinality: str = ""
    optional: bool = False
    enum: tuple[str, ...] = ()
    item_type: str = ""


@dataclass(frozen=True, order=True)
class IPMLifecycle:
    """An entity's lifecycle state machine."""
    entity: str
    field: str
    initial: str
    stages: tuple[str, ...]
    terminal: str


@dataclass(frozen=True, order=True)
class IPMRelationship:
    """An entity relationship to another entity."""
    entity: str
    name: str
    field: str
    cardinality: str
    target: str


@dataclass(frozen=True, order=True)
class IPMInvariant:
    """A declared invariant — an entity-level constraint or a standalone INVARIANT artifact's rule."""
    owner: str
    invariant_id: str
    constraint: str


@dataclass(frozen=True)
class IntermediateProtocolModel:
    """The CSI contract: a versioned, normalized semantic view of one compiled structure."""
    ipm_version: int
    structure_id: str
    identities: tuple[IPMIdentity, ...]         # sorted, unique
    workflows: tuple[IPMWorkflow, ...]          # sorted by fqdn
    compositions: tuple[IPMComposition, ...]    # sorted
    step_routings: tuple[IPMStepRouting, ...]   # sorted
    bindings: tuple[IPMBinding, ...]            # sorted
    authority: tuple[IPMAuthority, ...]         # sorted
    attributes: tuple[IPMAttribute, ...]        # sorted (definitional)
    lifecycles: tuple[IPMLifecycle, ...]        # sorted (definitional)
    relationships: tuple[IPMRelationship, ...]  # sorted (definitional)
    invariants: tuple[IPMInvariant, ...]        # sorted (definitional)


# ---- forward builder: canonical frontmatter (Definitional Layer) → declared IPM ----------------

def _wf_forward(artifact: dict) -> IPMWorkflow:
    """Normalize one WF canonical artifact's `frontmatter.core` into an IPMWorkflow.

    `core.nodes` is a {code: {fqdn_id, type, next:{outcome: target_code|EXIT}}} map; `core.start_node`
    is a code. Codes are resolved to FQDNs within the workflow; the synthetic EXIT node is dropped and
    `→ EXIT` transitions (terminal) are excluded — both are absent from the behavioral layer.
    """
    core = artifact.get("frontmatter", {}).get("core", {})
    nodes = core.get("nodes", {})
    # A node is a graph node only if it bears an FQDN. Two authoring conventions coexist: code-keyed
    # nodes (every node is an artifact) and label-keyed nodes (abstract `entry`/`exit` markers carry
    # no FQDN). The evidence graph tokenizes only FQDN-bearing nodes, so the round trip is over those:
    # null-FQDN markers and the synthetic EXIT are dropped, and `→` them is a terminal (non-)edge.
    code_to_fqdn = {code: n["fqdn_id"] for code, n in nodes.items()
                    if n.get("type") != _EXIT and n.get("fqdn_id")}

    identities: list[IPMIdentity] = []
    routing: list[IPMRouting] = []
    for code, n in nodes.items():
        src = code_to_fqdn.get(code)
        if src is None:                      # EXIT or an unbound abstract marker — not a graph node
            continue
        identities.append(IPMIdentity(fqdn=src, kind=n.get("type")))
        for outcome, target_code in (n.get("next") or {}).items():
            target = code_to_fqdn.get(target_code)
            if target is None:               # terminal / abstract target — not a behavioral edge
                continue
            routing.append(IPMRouting(source=src, outcome=outcome, target=target))

    return IPMWorkflow(
        fqdn=artifact.get("fqdn_id"),
        start_node=code_to_fqdn.get(core.get("start_node"), ""),   # "" when the start is an unbound marker
        nodes=tuple(sorted(identities)),
        routing=tuple(sorted(routing)),
    )


def build_forward_ipm(structure_id: str, canonical_artifacts: dict[str, dict],
                      members: set[str] | None = None) -> IntermediateProtocolModel:
    """The declared model: assemble an IPM from canonical artifacts' `frontmatter.core`.

    `canonical_artifacts` maps fqdn → canonical artifact dict (a compiler output). `members` is the
    structure's artifact membership from the artifact index (`structure_id ∈ entry.addresses`) — a
    structure aggregates capabilities across namespaces, so membership is authoritative, not namespace.
    Increment 1 reads WF artifacts (Identity + Workflow axes); identity set is the workflow closure
    (every WF + its contained nodes). Later increments fold in entities, bindings, etc.
    """
    def in_structure(a: dict) -> bool:
        if members is not None:
            return a.get("fqdn_id") in members
        return a.get("namespace") == structure_id or str(a.get("fqdn_id", "")).startswith(f"{structure_id}::")

    member_arts = [a for a in canonical_artifacts.values() if in_structure(a)]
    workflows = sorted((_wf_forward(a) for a in member_arts if a.get("artifact_type") == "WF"),
                       key=lambda w: w.fqdn)
    compositions, step_routings = _cc_forward(member_arts)
    bindings = _bindings_forward(member_arts)
    authority = _authority_forward(member_arts)
    # Definitional axes (declared form): the `core` parsed from the authored `## Machine` YAML in
    # `content` — independent of `frontmatter.core` (the compiled form the Reverse Projector reads).
    definitional = [_definitional_from_core(a["fqdn_id"], _machine_core(a.get("content", "")),
                                            a.get("artifact_type"))
                    for a in member_arts if a.get("artifact_type") in ("ENTITY", "INVARIANT")]
    return _assemble(structure_id, workflows, compositions, step_routings, bindings, authority,
                     _merge_definitional(definitional))


# ---- definitional extraction (shared by forward `## Machine` and reverse `frontmatter.core`) -----

_MACHINE_RE = re.compile(r"##\s*Machine\s*\n+```ya?ml\s*\n(.*?)\n```", re.DOTALL)


def _machine_core(content: str) -> dict:
    """Parse the `core:` mapping from an artifact's authored `## Machine` YAML block in `content`."""
    m = _MACHINE_RE.search(content or "")
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return data.get("core", {}) if isinstance(data, dict) else {}


def _definitional_from_core(fqdn: str, core: dict, kind: str) -> tuple[list, list, list, list]:
    """Extract (attributes, lifecycles, relationships, invariants) from a definitional artifact's core.

    The single extraction used by BOTH directions — forward feeds it the authored `## Machine` core,
    reverse feeds it the compiled `frontmatter.core`; equality of the results is Compilation Fidelity.
    """
    attrs: list[IPMAttribute] = []
    lifes: list[IPMLifecycle] = []
    rels: list[IPMRelationship] = []
    invs: list[IPMInvariant] = []
    if kind == "ENTITY":
        ident = core.get("identity") or {}
        if ident.get("field"):
            attrs.append(IPMAttribute(entity=fqdn, name=ident["field"],
                                      type=ident.get("type", ""), cardinality="1"))
        for a in core.get("attributes") or []:
            attrs.append(IPMAttribute(
                entity=fqdn, name=a.get("name"), type=a.get("type", ""),
                cardinality=str(a.get("cardinality", "")), optional=bool(a.get("optional", False)),
                enum=tuple(a.get("enum") or ()), item_type=a.get("item_type", "")))
        lc = core.get("lifecycle") or {}
        if lc:
            lifes.append(IPMLifecycle(entity=fqdn, field=lc.get("field", ""),
                                      initial=lc.get("initial", ""),
                                      stages=tuple(lc.get("stages") or ()), terminal=lc.get("terminal", "")))
        for r in core.get("relationships") or []:
            rels.append(IPMRelationship(entity=fqdn, name=r.get("name", ""), field=r.get("field", ""),
                                        cardinality=str(r.get("cardinality", "")), target=r.get("target", "")))
        for iv in core.get("invariants") or []:
            invs.append(IPMInvariant(owner=fqdn, invariant_id=iv.get("invariant_id", ""),
                                     constraint=iv.get("constraint", "")))
    elif kind == "INVARIANT":
        invs.append(IPMInvariant(owner=fqdn,
                                 invariant_id=core.get("invariant_code") or fqdn.split("::")[-1],
                                 constraint=core.get("rule") or core.get("summary") or ""))
    return attrs, lifes, rels, invs


def _merge_definitional(parts: list[tuple[list, list, list, list]]) -> tuple[list, list, list, list]:
    attrs, lifes, rels, invs = [], [], [], []
    for da, dl, dr, di in parts:
        attrs += da
        lifes += dl
        rels += dr
        invs += di
    return attrs, lifes, rels, invs


def _cc_forward(member_arts: list[dict]) -> tuple[list[IPMComposition], list[IPMStepRouting]]:
    """Capability Composition + capability-level Routing from CC `frontmatter.core.pipeline`."""
    comps: list[IPMComposition] = []
    routings: list[IPMStepRouting] = []
    for a in member_arts:
        if a.get("artifact_type") != "CC":
            continue
        cc = a.get("fqdn_id")
        for idx, step in enumerate(a.get("frontmatter", {}).get("core", {}).get("pipeline", [])):
            target = step.get("transform") or step.get("side_effect")
            if not target:
                continue
            kind = "CT" if step.get("transform") else "CS"
            comps.append(IPMComposition(cc=cc, pipeline_index=idx, step=step.get("step"),
                                        target=target, kind=kind))
            for outcome, disposition in (step.get("on_result") or {}).items():
                routings.append(IPMStepRouting(cc=cc, step=step.get("step"),
                                               outcome=outcome, disposition=disposition))
    return comps, routings


def _bindings_forward(member_arts: list[dict]) -> list[IPMBinding]:
    """WF_BINDS_RB from WF `core.runtime_binding`; RB_MAPS from RB `core.bindings` keys."""
    bindings: list[IPMBinding] = []
    for a in member_arts:
        core = a.get("frontmatter", {}).get("core", {})
        kind = a.get("artifact_type")
        if kind == "WF":
            # The bound RB is declared in the WF's references (and sometimes core.runtime_binding);
            # references is the consistent source across both WF authoring conventions.
            rbs = {r for r in a.get("references", []) if str(r).split("::")[-1].startswith("RB_")}
            rb = core.get("runtime_binding")
            if rb:
                rbs.add(rb)
            for r in rbs:
                bindings.append(IPMBinding(source=a["fqdn_id"], target=r, relation="WF_BINDS_RB"))
        elif kind == "RB":
            for cs in (core.get("bindings") or {}):
                bindings.append(IPMBinding(source=a["fqdn_id"], target=cs, relation="RB_MAPS"))
    return bindings


def _authority_forward(member_arts: list[dict]) -> list[IPMAuthority]:
    """GOVERNED_BY from each artifact's `frontmatter.governed_by` (top-level, else core).

    `governed_by` is scalar on most artifacts but a list on some (TI_, ASSERT_); the compiler emits
    one GOVERNED_BY edge per governor, so a list yields one authority entry per element.

    The Authority axis is governance-by-CONSTITUTION: every GOVERNED_BY edge targets a constitution.
    An ASSERT's `governed_by: INVARIANT_X` is a *conformance binding* (which invariant it checks), a
    distinct relation not carried as GOVERNED_BY — so non-constitution governors are excluded here.
    """
    authority: list[IPMAuthority] = []
    for a in member_arts:
        fm = a.get("frontmatter", {})
        gb = fm.get("governed_by") or fm.get("core", {}).get("governed_by")
        governors = gb if isinstance(gb, list) else ([gb] if gb else [])
        for g in governors:
            if str(g).split("::")[-1].startswith("CONSTITUTION_"):
                authority.append(IPMAuthority(artifact=a["fqdn_id"], governed_by=g))
    return authority


def _assemble(structure_id: str, workflows: list[IPMWorkflow],
              compositions: list[IPMComposition], step_routings: list[IPMStepRouting],
              bindings: list[IPMBinding], authority: list[IPMAuthority],
              definitional: tuple[list, list, list, list]) -> IntermediateProtocolModel:
    """Shared finalization: derive the Identity axis from the workflow closure and freeze the model.

    Identity is the workflow closure (every WF + its contained nodes); composition/binding/authority
    sources and targets are additional artifacts, but the Identity axis stays scoped to the workflow
    closure in this increment — widening it to the full structure membership is a later refinement.
    """
    identities: set[IPMIdentity] = set()
    for w in workflows:
        identities.add(IPMIdentity(fqdn=w.fqdn, kind="WF"))
        identities.update(w.nodes)
    attrs, lifes, rels, invs = definitional
    return IntermediateProtocolModel(
        ipm_version=IPM_VERSION,
        structure_id=structure_id,
        identities=tuple(sorted(identities)),
        workflows=tuple(workflows),
        compositions=tuple(sorted(compositions)),
        step_routings=tuple(sorted(step_routings)),
        bindings=tuple(sorted(bindings)),
        authority=tuple(sorted(authority)),
        attributes=tuple(sorted(attrs)),
        lifecycles=tuple(sorted(lifes)),
        relationships=tuple(sorted(rels)),
        invariants=tuple(sorted(invs)),
    )
