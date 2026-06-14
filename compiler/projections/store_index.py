"""
Store index projection — storage-ownership query metadata (§7.3).

Materializes the join the snapshot already declares in three places:

    storage STRUCTURE artifacts  →  entity_stores (store name → data path)
    RB artifacts                 →  core.bindings (CS → policy path)
    evidence graph               →  WF_BINDS_RB, WF_CONTAINS_NODE, CC_BINDS_CS

into: store → owning structure, declared path, binding surface
(RB + CS + workflows + consumer CCs). Emitted by `pgs_compiler.cli build`
alongside the artifact index (same query-metadata projection family):

    <workspace>/protocol_snapshot/artifact_index/stores.json

Doctrine: re-emission of declared facts only; deterministic; fail hard.
"""

import json
from pathlib import Path
from typing import Any

from pgs_compiler.compiler.projections import (
    ARTIFACT_INDEX_SCHEMA_VERSION,
    COMPILER_VERSION,
)

_STRUCTURES_DIR = "protocol_snapshot/artifacts/structures"
_RB_DIR = "protocol_snapshot/artifacts/runtime_bindings"
_EVIDENCE_ROOT = "evidence_snapshot"
_DATA_ROOT_TEMPLATE = "{{module_data_root}}/"

STORE_INDEX_RELATIVE_PATH = "protocol_snapshot/artifact_index/stores.json"


def build_store_index(workspace: Path) -> dict[str, Any]:
    """
    Build the store-ownership index from materialized projections.

    Returns the index content dict (JSON-serializable, deterministic).
    """
    workspace = Path(workspace)
    if not workspace.is_absolute():
        raise ValueError(f"workspace must be an absolute path, got: {workspace}")

    stores = _load_declared_stores(workspace)
    rb_paths = _load_rb_store_paths(workspace)
    wf_binds_rb, wf_contains, cc_binds_cs = _load_evidence_edges(workspace)

    def bindings_for(path: str) -> list[dict[str, Any]]:
        bindings: list[dict[str, Any]] = []
        for (rb_fqdn, cs_fqdn), declared_path in sorted(rb_paths.items()):
            if declared_path != path:
                continue
            workflows = sorted(
                wf for wf, rbs in wf_binds_rb.items() if rb_fqdn in rbs
            )
            consumer_ccs = sorted({
                cc
                for wf in workflows
                for cc in wf_contains.get(wf, set())
                if cs_fqdn in cc_binds_cs.get(cc, set())
            })
            bindings.append({
                "rb": rb_fqdn,
                "cs": cs_fqdn,
                "workflows": workflows,
                "consumer_ccs": consumer_ccs,
            })
        return bindings

    indexed: dict[str, dict[str, Any]] = {}
    for store_key, store in stores.items():
        indexed[store_key] = {
            "store": store["store"],
            "domain": store["domain"],
            "declarations": [
                {**declaration, "bindings": bindings_for(declaration["path"])}
                for declaration in store["declarations"]
            ],
        }

    if not indexed:
        raise ValueError(f"no entity_stores declared in any storage STRUCTURE under {workspace}")

    return {
        "schema_version": ARTIFACT_INDEX_SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "generated_by": "pgs_compiler.cli build",
        "store_count": len(indexed),
        "stores": dict(sorted(indexed.items())),
    }


def write_store_index(workspace: Path, content: dict[str, Any]) -> Path:
    """Write the store index atomically to its declared snapshot location."""
    workspace = Path(workspace)
    output_path = workspace / STORE_INDEX_RELATIVE_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_content = json.dumps(content, indent=2, sort_keys=True) + "\n"
    temp_path = output_path.with_suffix(".tmp")
    temp_path.write_text(json_content, encoding="utf-8")
    temp_path.replace(output_path)
    return output_path


def _load_declared_stores(workspace: Path) -> dict[str, dict[str, Any]]:
    """
    Stores declared via core.entity_stores in storage STRUCTURE artifacts.

    Keyed '<domain>::<STORE_NAME>'. A store name may be declared by more
    than one storage STRUCTURE in a domain — with the same path (shared
    store) or different paths (per-subdomain stores sharing a name). The
    index records each declaration as the protocol states it; no merging,
    no policing.
    """
    structures_dir = workspace / _STRUCTURES_DIR
    if not structures_dir.is_dir():
        raise FileNotFoundError(f"structures tree not found: {structures_dir}")

    stores: dict[str, dict[str, Any]] = {}
    for file in sorted(structures_dir.glob("*.json")):
        raw = json.loads(file.read_text(encoding="utf-8"))
        core = raw.get("frontmatter", {}).get("core", {})
        entity_stores = core.get("entity_stores")
        if not entity_stores:
            continue  # not a storage declaration
        fqdn = raw.get("fqdn_id")
        domain = core.get("domain")
        if not fqdn or not domain:
            raise ValueError(f"storage STRUCTURE missing fqdn_id or core.domain: {file}")
        for store_name in sorted(entity_stores):
            declared = entity_stores[store_name]
            key = f"{domain}::{store_name}"
            entry = stores.setdefault(
                key, {"store": store_name, "domain": domain, "declarations": []}
            )
            entry["declarations"].append({
                "path": declared.get("path", ""),
                "description": declared.get("description", ""),
                "declared_by": fqdn,
            })
    for entry in stores.values():
        entry["declarations"].sort(key=lambda d: (d["path"], d["declared_by"]))
    return stores


def _load_rb_store_paths(workspace: Path) -> dict[tuple[str, str], str]:
    """(RB fqdn, CS fqdn) → declared data path (template prefix stripped)."""
    rb_dir = workspace / _RB_DIR
    if not rb_dir.is_dir():
        raise FileNotFoundError(f"runtime_bindings tree not found: {rb_dir}")

    paths: dict[tuple[str, str], str] = {}
    for file in sorted(rb_dir.glob("*.json")):
        raw = json.loads(file.read_text(encoding="utf-8"))
        rb_fqdn = raw.get("fqdn_id")
        if not rb_fqdn:
            raise ValueError(f"RB artifact missing fqdn_id: {file}")
        bindings = raw.get("frontmatter", {}).get("core", {}).get("bindings", {})
        for cs_fqdn in sorted(bindings):
            policy = bindings[cs_fqdn].get("policy", {}) or {}
            declared_path = policy.get("path")
            if not declared_path:
                continue
            if declared_path.startswith(_DATA_ROOT_TEMPLATE):
                declared_path = declared_path[len(_DATA_ROOT_TEMPLATE):]
            paths[(rb_fqdn, cs_fqdn)] = declared_path
    return paths


def _load_evidence_edges(
    workspace: Path,
) -> tuple[dict[str, set], dict[str, set], dict[str, set]]:
    """WF→RBs, WF→member CCs, CC→bound CSs — from all scopes' evidence.json."""
    evidence_root = workspace / _EVIDENCE_ROOT
    if not evidence_root.is_dir():
        raise FileNotFoundError(f"evidence snapshot not found: {evidence_root}")

    wf_binds_rb: dict[str, set] = {}
    wf_contains: dict[str, set] = {}
    cc_binds_cs: dict[str, set] = {}

    scope_dirs = sorted(d for d in evidence_root.iterdir() if d.is_dir())
    if not scope_dirs:
        raise FileNotFoundError(f"no evidence scopes found under {evidence_root}")

    for scope_dir in scope_dirs:
        evidence_path = scope_dir / "evidence.json"
        if not evidence_path.is_file():
            raise FileNotFoundError(f"evidence.json missing: {evidence_path}")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        for edge in evidence["edges"]:
            kind = edge["kind"]
            if kind == "WF_BINDS_RB":
                wf_binds_rb.setdefault(edge["source_fqdn"], set()).add(edge["target_fqdn"])
            elif kind == "WF_CONTAINS_NODE":
                wf_contains.setdefault(edge["source_fqdn"], set()).add(edge["target_fqdn"])
            elif kind == "CC_BINDS_CS":
                cc_binds_cs.setdefault(edge["source_fqdn"], set()).add(edge["target_fqdn"])

    return wf_binds_rb, wf_contains, cc_binds_cs
