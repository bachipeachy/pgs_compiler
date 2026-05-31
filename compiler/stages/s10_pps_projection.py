"""
S10 PPS Projection — builds pps_snapshot/index.json from compiled workspace artifacts.

Reads (all read-only):
  - protocol_snapshot/artifacts/  — compiled artifact JSON files
  - vocabulary_snapshot/           — forward.json vocabulary files per domain
  - evidence_snapshot/             — evidence_graph.json files per domain

Emits:
  - pps_snapshot/index.json        — serialized cross-reference index (consumed by pgs_agent)

This stage runs AFTER all Phase Type A and B compilations complete.
It is a post-compilation aggregation step, independent of the S1-S9 State pipeline.

INVARIANT: This module MUST NOT import from pgs_agent or pgs_runtime.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


# Artifact subdirectories under protocol_snapshot/artifacts/
ARTIFACT_DIRS = {
    "workflows":               "protocol_snapshot/artifacts/workflows",
    "capability_contracts":    "protocol_snapshot/artifacts/capability_contracts",
    "capability_transforms":   "protocol_snapshot/artifacts/capability_transforms",
    "capability_side_effects": "protocol_snapshot/artifacts/capability_side_effects",
    "intents":                 "protocol_snapshot/artifacts/intents",
    "runtime_bindings":        "protocol_snapshot/artifacts/runtime_bindings",
    "actors":                  "protocol_snapshot/artifacts/actors",
    "events":                  "protocol_snapshot/artifacts/events",
}

VOCAB_DIR    = "vocabulary_snapshot"
EVIDENCE_DIR = "evidence_snapshot"
PPS_DIR      = "pps_snapshot"


class PPSProjectionBuilder:
    """
    Reads compiled workspace artifacts and emits pps_snapshot/index.json.

    All input paths are read-only. Only pps_snapshot/ is written.
    The index.json format is consumed by pgs_agent PPSLoader.
    """

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root.resolve()

    def build(self) -> dict:
        """
        Build the PPS index and write pps_snapshot/index.json.

        Returns a stats dict describing what was indexed.
        Raises FileNotFoundError if workspace is not compiled.
        """
        self._assert_workspace()

        artifacts = self._load_artifacts()
        vocab = self._load_vocabulary()
        edges = self._load_evidence()

        index = self._build_index(artifacts, vocab, edges)
        self._emit(index)

        return {
            "workflows": len(index["workflows"]),
            "capability_contracts": len(index["capability_contracts"]),
            "capability_transforms": len(index["capability_transforms"]),
            "capability_side_effects": len(index["capability_side_effects"]),
            "intents": len(index["intents"]),
            "runtime_bindings": len(index["runtime_bindings"]),
            "vocab_entries": len(index["vocabulary"]),
            "domains": list(index["domains"].keys()),
            "subdomains": list(index["subdomains"].keys()),
            "output": str(self._root / PPS_DIR / "index.json"),
        }

    # ------------------------------------------------------------------
    # Input loading
    # ------------------------------------------------------------------

    def _assert_workspace(self) -> None:
        snapshot = self._root / "protocol_snapshot"
        if not snapshot.exists():
            raise FileNotFoundError(
                f"protocol_snapshot/ not found at {self._root}. "
                "Run `pgs_compiler compile` for all structures before building PPS."
            )

    def _load_artifacts(self) -> dict[str, dict]:
        """Returns fqdn → raw artifact doc for all artifact types."""
        artifacts: dict[str, dict] = {}
        for _kind, rel_dir in ARTIFACT_DIRS.items():
            dir_path = self._root / rel_dir
            if not dir_path.exists():
                continue
            for f in dir_path.glob("*.json"):
                try:
                    doc = json.loads(f.read_text(encoding="utf-8"))
                    fqdn = doc.get("fqdn_id")
                    if fqdn:
                        artifacts[fqdn] = doc
                except Exception as exc:
                    raise RuntimeError(f"Failed to read artifact {f}: {exc}") from exc
        return artifacts

    def _load_vocabulary(self) -> dict[str, str]:
        """Returns flat dict: hex_address → fqdn. Merges all domain forward.json files."""
        vocab: dict[str, str] = {}
        vocab_root = self._root / VOCAB_DIR
        if not vocab_root.exists():
            return vocab
        for domain_dir in vocab_root.iterdir():
            if not domain_dir.is_dir():
                continue
            forward_file = domain_dir / "forward.json"
            if forward_file.exists():
                try:
                    data = json.loads(forward_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        vocab.update(data)
                except Exception as exc:
                    raise RuntimeError(f"Failed to read vocab {forward_file}: {exc}") from exc
        return vocab

    def _load_evidence(self) -> list[dict]:
        """Returns merged list of evidence edges from all domain evidence_graph.json files."""
        edges: list[dict] = []
        evidence_root = self._root / EVIDENCE_DIR
        if not evidence_root.exists():
            return edges
        for domain_dir in evidence_root.iterdir():
            if not domain_dir.is_dir():
                continue
            graph_file = domain_dir / "evidence_graph.json"
            if graph_file.exists():
                try:
                    data = json.loads(graph_file.read_text(encoding="utf-8"))
                    raw_edges = data.get("edges", [])
                    edges.extend(raw_edges)
                except Exception as exc:
                    raise RuntimeError(f"Failed to read evidence {graph_file}: {exc}") from exc
        return edges

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def _build_index(
        self,
        artifacts: dict[str, dict],
        vocab: dict[str, str],
        edges: list[dict],
    ) -> dict:
        """
        Build the full cross-referenced index as a plain JSON-serializable dict.

        Mirrors the PPSIndex.build() logic in pgs_agent without importing it.
        The output format is the contract between pgs_compiler and pgs_agent.
        """
        workflows: dict[str, dict] = {}
        capability_contracts: dict[str, dict] = {}
        capability_transforms: dict[str, dict] = {}
        capability_side_effects: dict[str, dict] = {}
        intents: dict[str, dict] = {}
        runtime_bindings: dict[str, dict] = {}

        for fqdn, doc in artifacts.items():
            atype = doc.get("artifact_type", "")
            ns = doc.get("namespace", fqdn.split("::")[0] if "::" in fqdn else "")
            fm = doc.get("frontmatter", {})
            code = fqdn.split("::")[-1] if "::" in fqdn else fqdn
            version = fm.get("version", "v0")
            core = fm.get("core", {})

            base: dict = {
                "fqdn": fqdn,
                "namespace": ns,
                "code": code,
                "version": version,
                "raw": doc,
            }

            if atype == "WF":
                nodes = core.get("nodes", {})
                workflows[fqdn] = {
                    **base,
                    "subdomain": fm.get("subdomain", ""),
                    "summary": core.get("summary", ""),
                    "start_node": core.get("start_node", ""),
                    "nodes": nodes,
                    "runtime_binding": fm.get("runtime_binding", ""),
                }

            elif atype == "CC":
                rsc = core.get("result_status_contract", {})
                capability_contracts[fqdn] = {
                    **base,
                    "summary": core.get("summary", ""),
                    "outcomes": rsc.get("allowed", []),
                    "pipeline": core.get("pipeline", []),
                    "inputs": core.get("inputs", {}),
                    "outputs": core.get("outputs", {}),
                }

            elif atype == "CT":
                machine = fm.get("machine", {})
                capability_transforms[fqdn] = {
                    **base,
                    "summary": core.get("summary", fm.get("description", "")),
                    "purity": machine.get("ct_purity", "ct_pure"),
                    "inputs": core.get("inputs", {}),
                    "outputs": core.get("outputs", {}),
                }

            elif atype == "CS":
                capability_side_effects[fqdn] = {
                    **base,
                    "operations": core.get("operations", {}),
                }

            elif atype == "IN":
                intents[fqdn] = base

            elif atype == "RB":
                runtime_bindings[fqdn] = {
                    **base,
                    "bindings": core.get("bindings", {}),
                }

        # ------------------------------------------------------------------
        # Cross-references
        # ------------------------------------------------------------------
        wf_to_ccs: dict[str, list[str]] = {}
        cc_to_ct_cs: dict[str, list[str]] = {}
        cc_outcomes: dict[str, list[str]] = {}
        cc_upstream: dict[str, list[str]] = {}
        cc_downstream: dict[str, list[str]] = {}

        # wf_to_ccs — derived from WF node definitions (type == "CC")
        for wf_fqdn, wf in workflows.items():
            cc_list = []
            for _node_code, node in wf["nodes"].items():
                if node.get("type") == "CC":
                    node_fqdn = node.get("fqdn_id", f"{wf['namespace']}::{_node_code}")
                    cc_list.append(node_fqdn)
            wf_to_ccs[wf_fqdn] = cc_list

        # cc_outcomes — from CC allowed outcomes
        for cc_fqdn, cc in capability_contracts.items():
            cc_outcomes[cc_fqdn] = cc["outcomes"]

        # cc_to_ct_cs — from pipeline transform references
        for cc_fqdn, cc in capability_contracts.items():
            refs = []
            for step in cc["pipeline"]:
                if "transform" in step:
                    refs.append(step["transform"])
            cc_to_ct_cs[cc_fqdn] = refs

        # upstream/downstream — from evidence edges
        for edge in edges:
            kind = edge.get("kind", "")
            src = edge.get("source_fqdn", "")
            tgt = edge.get("target_fqdn", "")
            if not src or not tgt:
                continue

            if kind == "NODE_NEXT":
                cc_downstream.setdefault(src, [])
                if tgt not in cc_downstream[src]:
                    cc_downstream[src].append(tgt)
                cc_upstream.setdefault(tgt, [])
                if src not in cc_upstream[tgt]:
                    cc_upstream[tgt].append(src)

            elif kind == "CC_BINDS_CS":
                cc_to_ct_cs.setdefault(src, [])
                if tgt not in cc_to_ct_cs[src]:
                    cc_to_ct_cs[src].append(tgt)

        # ------------------------------------------------------------------
        # Domain groupings
        # ------------------------------------------------------------------
        domains: dict[str, list[str]] = {}
        all_fqdns = (
            list(workflows)
            + list(capability_contracts)
            + list(capability_transforms)
            + list(capability_side_effects)
            + list(intents)
            + list(runtime_bindings)
        )
        for fqdn in all_fqdns:
            ns = fqdn.split("::")[0] if "::" in fqdn else "unknown"
            domains.setdefault(ns, [])
            if fqdn not in domains[ns]:
                domains[ns].append(fqdn)

        subdomains: dict[str, list[str]] = {}
        for wf_fqdn, wf in workflows.items():
            sd = wf["subdomain"] or "default"
            subdomains.setdefault(sd, [])
            if wf_fqdn not in subdomains[sd]:
                subdomains[sd].append(wf_fqdn)

        # ------------------------------------------------------------------
        # Vocabulary
        # ------------------------------------------------------------------
        vocabulary: dict[str, dict] = {}
        vocab_by_address: dict[str, dict] = {}
        for address, fqdn in vocab.items():
            entry = {"address": address, "fqdn": fqdn}
            vocabulary[fqdn] = entry
            vocab_by_address[address] = entry

        return {
            "version": "1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workflows": workflows,
            "capability_contracts": capability_contracts,
            "capability_transforms": capability_transforms,
            "capability_side_effects": capability_side_effects,
            "intents": intents,
            "runtime_bindings": runtime_bindings,
            "wf_to_ccs": wf_to_ccs,
            "cc_to_ct_cs": cc_to_ct_cs,
            "cc_outcomes": cc_outcomes,
            "cc_upstream": cc_upstream,
            "cc_downstream": cc_downstream,
            "domains": domains,
            "subdomains": subdomains,
            "vocabulary": vocabulary,
            "vocab_by_address": vocab_by_address,
        }

    # ------------------------------------------------------------------
    # Output emission
    # ------------------------------------------------------------------

    def _emit(self, index: dict) -> None:
        """Write pps_snapshot/index.json to the workspace root."""
        pps_dir = self._root / PPS_DIR
        pps_dir.mkdir(parents=True, exist_ok=True)

        out_path = pps_dir / "index.json"
        out_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
