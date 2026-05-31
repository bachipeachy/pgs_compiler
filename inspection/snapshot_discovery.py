"""
snapshot_discovery.py — dynamic subdomain discovery from protocol_snapshot.

Replaces hardcoded SUBDOMAIN_ARTIFACTS / SUBDOMAIN_TO_DOMAIN / CROSS_SUBDOMAIN_CCS /
SUBDOMAIN_ACTOR_MODE dicts in governance_projection.py and equivalence_validation.py.

CLI:
    python -m pgs_compiler.inspection.snapshot_discovery <snapshot_base>
    → space-separated sorted subdomain names (for use in run_governance_linting.sh)

Module usage:
    from pgs_compiler.inspection.snapshot_discovery import discover_subdomains
    info = discover_subdomains(snapshot_base)
    → dict[subdomain_name] = {
          "domain":     str,                          # e.g. "blockchain"
          "artifacts":  [(concern, filename), ...],   # ordered AC→IN→WF→CC
          "cross_ccs":  {cc_code: owner_subdomain},   # cross-subdomain CC refs
          "actor_mode": "own" | "reference" | "none", # actor section mode
      }

Discovery algorithm:
    1. Scan workflows/*.json → subdomain, domain prefix, wf_code, CC node codes
       (capability WFs with subdomain=None are skipped automatically)
    2. Scan intents/*.json → wf_code → in_filename mapping
    3. Scan capability_contracts/*.json → cc_code → filename index
    4. CC ownership: alphabetically-first subdomain that references a CC in its WF DAG.
       CC_NATIVE_SUBDOMAIN_OVERRIDE handles the few cases where this heuristic is wrong.
    5. ACs assigned via AC_OWNER (AC artifacts have no subdomain field in the snapshot).
    6. actor_mode: "own" if subdomain has ACs, override if in SUBDOMAIN_ACTOR_MODE_OVERRIDE,
       else "reference".
"""

import glob
import json
import os
import sys

# ---------------------------------------------------------------------------
# Residual hardcoding — only what cannot be derived from the snapshot
# ---------------------------------------------------------------------------

# AC artifacts have no subdomain field in the snapshot — explicit owner mapping required.
# Key: filename (as it appears in actors/), Value: owning subdomain.
# When a new AC is added to the snapshot, add its entry here.
AC_OWNER = {
    "blockchain__AC_ENDUSER_V0.json":               "identity",
    "blockchain__AC_SYSTEM_V0.json":                "identity",
    "ai_governance__AC_EMPLOYEE_V0.json":           "ai_licensing",
    "ai_governance__AC_SYSTEM_V0.json":             "ai_licensing",
    "ai_governance__AC_AGENT_V0.json":              "agent_governance",
    "ai_governance__AC_ENTERPRISE_RUNTIME_V0.json": "agent_governance",
    "ai_governance__AC_SYSTEM_GOVERNOR_V0.json":    "agent_governance",
}

# Override actor_mode for subdomains that declare no actors at all.
# Default rule: "own" if AC files assigned, "reference" otherwise.
SUBDOMAIN_ACTOR_MODE_OVERRIDE = {
    "collatz_conjecture": "none",
}

# CC ownership override — for CCs whose conceptual owner differs from the
# alphabetically-first WF-referencing subdomain.
# Example: CC_CHECK_ACTOR_EXISTS_V0 is an identity CC that only appears in
# the consensus_pos WF DAG; without the override the heuristic would assign
# it to consensus_pos.
CC_NATIVE_SUBDOMAIN_OVERRIDE = {
    "CC_CHECK_ACTOR_EXISTS_V0": "identity",
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_subdomains(snapshot_base: str) -> dict:
    """
    Scan protocol_snapshot/artifacts and return a per-subdomain discovery dict.

    Args:
        snapshot_base: absolute path to protocol_snapshot/artifacts/

    Returns:
        dict[subdomain_name] = {
            "domain":     str,                          # e.g. "blockchain"
            "artifacts":  [(concern, filename), ...],   # AC→IN→WF→CC order
            "cross_ccs":  {cc_code: owner_subdomain},   # cross-subdomain CC refs
            "actor_mode": "own" | "reference" | "none",
        }
    """
    wf_dir = os.path.join(snapshot_base, "workflows")
    in_dir = os.path.join(snapshot_base, "intents")
    cc_dir = os.path.join(snapshot_base, "capability_contracts")
    ac_dir = os.path.join(snapshot_base, "actors")

    # ------------------------------------------------------------------
    # Step 1: Scan WF artifacts — build per-subdomain WF info
    # ------------------------------------------------------------------
    sd_info: dict = {}

    for wf_path in sorted(glob.glob(os.path.join(wf_dir, "*.json"))):
        d = json.load(open(wf_path))
        fm = d["frontmatter"]
        subdomain = fm.get("subdomain")
        if not subdomain:
            continue  # capability WFs (subdomain=None) — skip

        filename = os.path.basename(wf_path)
        domain = filename.split("__")[0]  # e.g. "blockchain" from "blockchain__WF_*.json"

        if subdomain not in sd_info:
            sd_info[subdomain] = {
                "domain":   domain,
                "wf_files": [],
                "cc_refs":  set(),
            }

        sd_info[subdomain]["wf_files"].append(filename)

        nodes = fm.get("core", {}).get("nodes", {})
        for node_key, node in nodes.items():
            if node.get("type") == "CC":
                cc_code = node.get("code", node_key)
                sd_info[subdomain]["cc_refs"].add(cc_code)

    # ------------------------------------------------------------------
    # Step 2: Build wf_code → in_filename mapping from IN artifacts
    # ------------------------------------------------------------------
    wf_to_in: dict = {}

    for in_path in sorted(glob.glob(os.path.join(in_dir, "*.json"))):
        filename = os.path.basename(in_path)
        domain_prefix = filename.split("__")[0]
        if "." in domain_prefix:
            continue  # capability IN (dotted domain prefix) — skip
        d = json.load(open(in_path))
        wf_field = d["frontmatter"].get("core", {}).get("workflow", "")
        if "::" in wf_field:
            continue  # FQDN workflow ref → capability IN — skip
        if wf_field:
            wf_to_in[wf_field] = filename

    # ------------------------------------------------------------------
    # Step 3: Build cc_code → filename index from CC artifacts
    # ------------------------------------------------------------------
    cc_code_to_file: dict = {}

    for cc_path in sorted(glob.glob(os.path.join(cc_dir, "*.json"))):
        filename = os.path.basename(cc_path)
        domain_prefix = filename.split("__")[0]
        if "." in domain_prefix:
            continue  # capability CC — skip
        d = json.load(open(cc_path))
        cc_code = d["frontmatter"].get("cc_code", "")
        if cc_code:
            cc_code_to_file[cc_code] = filename

    # ------------------------------------------------------------------
    # Step 4: Determine CC ownership
    # ------------------------------------------------------------------
    cc_owner: dict = {}

    for cc_code in cc_code_to_file:
        if cc_code in CC_NATIVE_SUBDOMAIN_OVERRIDE:
            cc_owner[cc_code] = CC_NATIVE_SUBDOMAIN_OVERRIDE[cc_code]
        else:
            referencing = sorted(
                sd for sd, info in sd_info.items() if cc_code in info["cc_refs"]
            )
            if referencing:
                cc_owner[cc_code] = referencing[0]

    # ------------------------------------------------------------------
    # Step 5: Assign AC files to subdomains via AC_OWNER
    # ------------------------------------------------------------------
    sd_ac_files: dict = {}

    for ac_filename, ac_subdomain in AC_OWNER.items():
        ac_path = os.path.join(ac_dir, ac_filename)
        if not os.path.exists(ac_path):
            continue
        sd_ac_files.setdefault(ac_subdomain, []).append(ac_filename)

    # ------------------------------------------------------------------
    # Step 6: Assemble per-subdomain result
    # ------------------------------------------------------------------
    result: dict = {}

    for subdomain, info in sorted(sd_info.items()):
        domain = info["domain"]
        cc_refs = info["cc_refs"]

        ac_artifacts = [
            ("actors", fname)
            for fname in sorted(sd_ac_files.get(subdomain, []))
        ]

        in_artifacts = []
        for wf_file in sorted(info["wf_files"]):
            d = json.load(open(os.path.join(wf_dir, wf_file)))
            wf_code = d["frontmatter"].get("wf_code", "")
            if wf_code in wf_to_in:
                in_artifacts.append(("intents", wf_to_in[wf_code]))

        wf_artifacts = [("workflows", f) for f in sorted(info["wf_files"])]

        native_cc_artifacts = []
        cross_ccs: dict = {}
        for cc_code in sorted(cc_refs):
            owner = cc_owner.get(cc_code)
            if owner == subdomain:
                filename = cc_code_to_file.get(cc_code)
                if filename:
                    native_cc_artifacts.append(("capability_contracts", filename))
            elif owner:
                cross_ccs[cc_code] = owner

        artifacts = ac_artifacts + in_artifacts + wf_artifacts + native_cc_artifacts

        if subdomain in SUBDOMAIN_ACTOR_MODE_OVERRIDE:
            actor_mode = SUBDOMAIN_ACTOR_MODE_OVERRIDE[subdomain]
        elif ac_artifacts:
            actor_mode = "own"
        else:
            actor_mode = "reference"

        result[subdomain] = {
            "domain":     domain,
            "artifacts":  artifacts,
            "cross_ccs":  cross_ccs,
            "actor_mode": actor_mode,
        }

    return result


# ---------------------------------------------------------------------------
# CLI — outputs space-separated sorted subdomain list for shell integration
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python -m pgs_compiler.inspection.snapshot_discovery <snapshot_base>",
              file=sys.stderr)
        sys.exit(1)
    snapshot_base = sys.argv[1]
    info = discover_subdomains(snapshot_base)
    print(" ".join(sorted(info.keys())))
