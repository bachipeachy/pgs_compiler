"""Reverse Projector — the inverse of the Forward (canonical) Projector.

Given a compiled structure's Semantic Substrate, reconstruct the Intermediate Protocol Model (IPM).
This is a *compiler capability*, the mathematical inverse of canonicalization — it is not verification.
It reasons over the compiler's own products and never reads authoring markdown, registry sources, or
Change Requests. That independence is what lets verification be reproducible from the snapshot alone.

    Semantic Substrate
      ├── Definitional Layer : protocol_snapshot/artifacts/**.json  (frontmatter.core)
      └── Behavioral Layer   : evidence_snapshot/<structure>/evidence.json  (dual-form graph)

Increment 1 reconstructs the Behavioral Layer's Workflow topology (and, with the Definitional Layer,
the Identity closure). The evidence graph encodes a workflow as:
  * WF_START        — workflow → its start node
  * WF_CONTAINS_NODE — workflow → each contained node
  * NODE_NEXT       — node → next node, with metadata {condition, wf_fqdn}; scoped by `wf_fqdn`
                      because a node may participate in several workflows. Terminal (→EXIT) outcomes
                      are edge-absent by construction; they are recovered on CC_BINDS `on_result`
                      metadata in a later (CapabilityComposition) increment, not here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .ipm import (
    IntermediateProtocolModel, IPMIdentity, IPMRouting, IPMWorkflow, _assemble,
    IPMComposition, IPMStepRouting, IPMBinding, IPMAuthority,
    _definitional_from_core, _merge_definitional,
)


@dataclass(frozen=True)
class SemanticSubstrate:
    """A loader over a compiled structure's compiler outputs — the substrate the Reverse Projector reads.

    Holds nothing but compiler products: the evidence graph (Behavioral Layer) and the canonical
    artifacts (Definitional Layer). Constructed via `load`; never reaches back into authoring sources.
    """
    structure_id: str
    evidence: dict
    canonical_artifacts: dict[str, dict]
    member_fqdns: frozenset[str]            # structure membership from the artifact index

    @classmethod
    def load(cls, workspace: Path | str, structure_id: str) -> "SemanticSubstrate":
        ws = Path(workspace)
        evidence_path = ws / "evidence_snapshot" / structure_id / "evidence.json"
        evidence = json.loads(evidence_path.read_text())

        # Both canonical trees are compiler outputs: domain artifacts under artifacts/, and the
        # shared governance artifacts (fb.* constitutions/invariants/asserts) under governance/artifacts/.
        # The latter are structure members too (they govern the domain), so both must be loaded.
        artifacts_root = ws / "protocol_snapshot" / "artifacts"
        canonical: dict[str, dict] = {}
        for root in (artifacts_root, ws / "protocol_snapshot" / "governance" / "artifacts"):
            for p in sorted(root.rglob("*.json")):
                try:
                    art = json.loads(p.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                fqdn = art.get("fqdn_id")
                if fqdn:
                    canonical[fqdn] = art

        # Authoritative per-structure membership: the artifact index records which structures each
        # artifact compiled into (a structure aggregates capabilities across namespaces).
        index = json.loads((artifacts_root.parent / "artifact_index" / "index.json").read_text())
        members = frozenset(
            fqdn for fqdn, entry in index.get("artifacts", {}).items()
            if structure_id in entry.get("addresses", {})
        )
        return cls(structure_id=structure_id, evidence=evidence,
                   canonical_artifacts=canonical, member_fqdns=members)


def reverse_project(substrate: SemanticSubstrate) -> IntermediateProtocolModel:
    """Reconstruct the IPM from the substrate (Increment 1: Identity + Workflow axes)."""
    evidence = substrate.evidence
    nodes = evidence.get("nodes", [])
    edges = evidence.get("edges", [])

    kind_of = {n["fqdn"]: n["kind"] for n in nodes}
    wf_fqdns = sorted(fqdn for fqdn, kind in kind_of.items() if kind == "WF")

    contains: dict[str, set[str]] = {wf: set() for wf in wf_fqdns}
    start: dict[str, str] = {}
    routing: dict[str, list[IPMRouting]] = {wf: [] for wf in wf_fqdns}

    for e in edges:
        kind = e.get("kind")
        if kind == "WF_CONTAINS_NODE" and e.get("source_fqdn") in contains:
            contains[e["source_fqdn"]].add(e["target_fqdn"])
        elif kind == "WF_START" and e.get("source_fqdn") in start.keys() | set(wf_fqdns):
            start[e["source_fqdn"]] = e["target_fqdn"]
        elif kind == "NODE_NEXT":
            wf = (e.get("metadata") or {}).get("wf_fqdn")
            if wf in routing:
                routing[wf].append(IPMRouting(
                    source=e["source_fqdn"],
                    outcome=(e.get("metadata") or {}).get("condition"),
                    target=e["target_fqdn"],
                ))

    workflows: list[IPMWorkflow] = []
    for wf in wf_fqdns:
        node_ids = tuple(sorted(IPMIdentity(fqdn=f, kind=kind_of.get(f, "?")) for f in contains[wf]))
        workflows.append(IPMWorkflow(
            fqdn=wf,
            start_node=start.get(wf, ""),
            nodes=node_ids,
            routing=tuple(sorted(routing[wf])),
        ))

    compositions, step_routings = _compositions_reverse(edges)
    bindings = _bindings_reverse(edges)
    authority = _authority_reverse(edges)
    # Definitional axes (compiled form): the Definitional Layer of the substrate — each member
    # entity/invariant's normalized `frontmatter.core`. Same extraction as forward, different source.
    definitional = _merge_definitional([
        _definitional_from_core(fqdn, (art.get("frontmatter") or {}).get("core", {}), art.get("artifact_type"))
        for fqdn in substrate.member_fqdns
        if (art := substrate.canonical_artifacts.get(fqdn)) is not None
        and art.get("artifact_type") in ("ENTITY", "INVARIANT")
    ])
    return _assemble(substrate.structure_id, workflows, compositions, step_routings,
                     bindings, authority, definitional)


def _compositions_reverse(edges: list[dict]) -> tuple[list[IPMComposition], list[IPMStepRouting]]:
    """Capability Composition + capability-level Routing from CC_BINDS_CT / CC_BINDS_CS edges.

    `op` is not reconstructed: CC_BINDS_CT carries none, so it is not a behavioral-layer attribute.
    """
    comps: list[IPMComposition] = []
    routings: list[IPMStepRouting] = []
    for e in edges:
        kind = {"CC_BINDS_CT": "CT", "CC_BINDS_CS": "CS"}.get(e.get("kind"))
        if not kind:
            continue
        md = e.get("metadata") or {}
        cc, step = e["source_fqdn"], md.get("step_id")
        comps.append(IPMComposition(cc=cc, pipeline_index=md.get("pipeline_index"), step=step,
                                    target=e["target_fqdn"], kind=kind))
        for outcome, disposition in (md.get("on_result") or {}).items():
            routings.append(IPMStepRouting(cc=cc, step=step, outcome=outcome, disposition=disposition))
    return comps, routings


def _bindings_reverse(edges: list[dict]) -> list[IPMBinding]:
    """WF_BINDS_RB and RB_MAPS edges → bindings."""
    return [
        IPMBinding(source=e["source_fqdn"], target=e["target_fqdn"], relation=e["kind"])
        for e in edges if e.get("kind") in ("WF_BINDS_RB", "RB_MAPS")
    ]


def _authority_reverse(edges: list[dict]) -> list[IPMAuthority]:
    """GOVERNED_BY edges → authority."""
    return [
        IPMAuthority(artifact=e["source_fqdn"], governed_by=e["target_fqdn"])
        for e in edges if e.get("kind") == "GOVERNED_BY"
    ]
