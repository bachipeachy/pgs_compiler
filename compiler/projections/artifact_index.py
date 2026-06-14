"""
Artifact index projection — federated query metadata.

Materializes the cross-structure FQDN index consumed by the protocol
inspection surface (pi). Maps every compiled artifact FQDN to its
domain, owning STRUCTURE(s), artifact kind, canonical path, evidence
path, and per-structure vocabulary address.

Emitted by `pgs_compiler.cli build` (scripts/pgs_build.py) after the
snapshot sync step — the only point with the full federated view of
all materialized projections. Written to:

    <workspace>/protocol_snapshot/artifact_index/index.json

Doctrine:
    - Query metadata, distinct from the manifest (build metadata) and
      the vocabulary (semantic metadata). Each gets its own projection.
    - Re-emission only: every fact is read from materialized projections
      (canonical artifacts, vocabulary reverse.json). Zero re-derivation,
      zero inference — kind and FQDN come from declared artifact fields.
    - Deterministic: same snapshot → byte-identical index (sorted keys,
      no timestamps).
    - Fail hard: malformed canonical artifact or unreadable projection
      raises immediately; no partial index is written.
"""

import json
from pathlib import Path
from typing import Any

from pgs_compiler.compiler.projections import (
    ARTIFACT_INDEX_SCHEMA_VERSION,
    COMPILER_VERSION,
    SCOPE_STRUCTURE_MAP,
)

# Canonical artifact trees indexed, relative to the workspace root.
_ARTIFACT_ROOTS = (
    "protocol_snapshot/artifacts",
    "protocol_snapshot/governance/artifacts",
)

_VOCABULARY_ROOT = "vocabulary_snapshot"
_EVIDENCE_ROOT = "evidence_snapshot"

INDEX_RELATIVE_PATH = "protocol_snapshot/artifact_index/index.json"


def build_artifact_index(workspace: Path) -> dict[str, Any]:
    """
    Build the artifact index content from materialized projections.

    Args:
        workspace: Absolute path to the pgs_workspace root.

    Returns:
        Index content dict (JSON-serializable, deterministic ordering).

    Raises:
        FileNotFoundError: required projection tree missing.
        ValueError: canonical artifact missing declared identity fields,
                    or duplicate FQDN across canonical files.
    """
    workspace = Path(workspace)
    if not workspace.is_absolute():
        raise ValueError(f"workspace must be an absolute path, got: {workspace}")

    membership = _load_vocabulary_membership(workspace)

    artifacts: dict[str, dict[str, Any]] = {}
    for root_rel in _ARTIFACT_ROOTS:
        root = workspace / root_rel
        if not root.is_dir():
            raise FileNotFoundError(f"canonical artifact tree not found: {root}")
        for file in sorted(root.rglob("*.json")):
            if file.name == "metadata.json":
                continue
            entry_fqdn, entry = _index_entry(workspace, file, membership)
            if entry_fqdn in artifacts:
                raise ValueError(
                    f"duplicate FQDN '{entry_fqdn}' in canonical snapshot: "
                    f"{artifacts[entry_fqdn]['canonical_path']} and "
                    f"{entry['canonical_path']}"
                )
            artifacts[entry_fqdn] = entry

    if not artifacts:
        raise ValueError(f"no canonical artifacts found under {workspace}")

    return {
        "schema_version": ARTIFACT_INDEX_SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "generated_by": "pgs_compiler.cli build",
        "artifact_count": len(artifacts),
        "structures": dict(sorted(SCOPE_STRUCTURE_MAP.items())),
        "artifacts": dict(sorted(artifacts.items())),
    }


def write_artifact_index(workspace: Path, content: dict[str, Any]) -> Path:
    """
    Write the artifact index atomically to its declared snapshot location.

    Returns the output path.
    """
    workspace = Path(workspace)
    output_path = workspace / INDEX_RELATIVE_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_content = json.dumps(content, indent=2, sort_keys=True) + "\n"
    temp_path = output_path.with_suffix(".tmp")
    temp_path.write_text(json_content, encoding="utf-8")
    temp_path.replace(output_path)
    return output_path


def _load_vocabulary_membership(workspace: Path) -> dict[str, dict[str, str]]:
    """
    Load FQDN → {scope: address} from every vocabulary reverse.json.

    Each structure scope (e.g. blockchain) carries its own address space;
    shared artifacts legitimately appear under multiple scopes.
    """
    vocab_root = workspace / _VOCABULARY_ROOT
    if not vocab_root.is_dir():
        raise FileNotFoundError(f"vocabulary snapshot not found: {vocab_root}")

    membership: dict[str, dict[str, str]] = {}
    scope_dirs = sorted(d for d in vocab_root.iterdir() if d.is_dir())
    if not scope_dirs:
        raise FileNotFoundError(f"no vocabulary scopes found under {vocab_root}")

    for scope_dir in scope_dirs:
        reverse_path = scope_dir / "reverse.json"
        if not reverse_path.is_file():
            raise FileNotFoundError(f"vocabulary reverse.json not found: {reverse_path}")
        reverse = json.loads(reverse_path.read_text(encoding="utf-8"))
        for fqdn, address in reverse.items():
            membership.setdefault(fqdn, {})[scope_dir.name] = address

    return membership


def _index_entry(
    workspace: Path,
    file: Path,
    membership: dict[str, dict[str, str]],
) -> tuple[str, dict[str, Any]]:
    """
    Build one index entry from a materialized canonical artifact file.

    Identity (fqdn_id, artifact_type) is read from declared fields only.
    """
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"canonical artifact root must be a JSON object: {file}")

    fqdn = raw.get("fqdn_id")
    kind = raw.get("artifact_type")
    if not fqdn or "::" not in fqdn:
        raise ValueError(f"canonical artifact missing valid fqdn_id: {file}")
    if not kind:
        raise ValueError(f"canonical artifact missing artifact_type: {file}")

    domain = fqdn.split("::", 1)[0]
    scopes = membership.get(fqdn, {})

    structures = sorted(
        SCOPE_STRUCTURE_MAP[scope] for scope in scopes if scope in SCOPE_STRUCTURE_MAP
    )

    evidence_paths: dict[str, str] = {}
    for scope in sorted(scopes):
        eg_rel = f"{_EVIDENCE_ROOT}/{scope}/evidence_graph.json"
        if (workspace / eg_rel).is_file():
            evidence_paths[scope] = eg_rel

    entry = {
        "domain": domain,
        "kind": kind,
        "structures": structures,
        "canonical_path": file.relative_to(workspace).as_posix(),
        "evidence_paths": evidence_paths,
        "addresses": {scope: scopes[scope] for scope in sorted(scopes)},
    }
    return fqdn, entry
