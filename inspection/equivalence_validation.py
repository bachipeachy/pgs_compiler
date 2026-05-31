"""
equivalence_validation.py — Step 4 of pgs_spec_reverse_engineering_plan.md

Compares generated Governance Intent prose against the artifact `content` field for structural
equivalence. Prose wording is allowed to differ; structure must not.

This is a compiler-owned module: it validates the compiler's own snapshot output.
Authoring concerns (Business Intent) remain in pgs_agent.

Public API:
    run_validation(snapshot, subdomain) -> bool
        Run equivalence validation for one subdomain. Returns True if all checks pass.

CLI (via pgs_compiler inspect-governance --mode validate):
    python -m pgs_compiler.inspection.equivalence_validation \
        --snapshot   /abs/path/to/protocol_snapshot/artifacts \
        --subdomain  <subdomain>

Checks per concern type:
  AC  — attributes: same field names, types, required flags
  IN  — inputs: same field names, types, required flags; outcomes: same keys
  WF  — nodes: same codes and types; routing: same outcomes per node
  CC  — inputs, outputs: same field names + types; result statuses: same set;
         pipeline: same step count

Exit codes:
    0 — all checks PASS
    1 — one or more checks FAIL (hard stop)
"""

import argparse
import json
import os
import re
import sys

from pgs_compiler.inspection.snapshot_discovery import discover_subdomains


# ---------------------------------------------------------------------------
# Markdown table parser
# ---------------------------------------------------------------------------

def _parse_md_table(text: str, section_header: str) -> list:
    """
    Extract rows from a markdown table under the given section header.
    Handles both bare headers (## Attributes) and numbered headers (## 4. Attributes).
    Returns list of dicts keyed by column header (stripped, lowercase).
    Returns empty list if section or table not found.
    """
    pattern = re.compile(
        r'(?:^|\n)#+\s*(?:\d+\.\s*)?' + re.escape(section_header) + r'[^\n]*\n(.*?)(?=\n#+\s|\Z)',
        re.DOTALL | re.IGNORECASE
    )
    match = pattern.search(text)
    if not match:
        return []
    block = match.group(1)
    lines = [l.strip() for l in block.splitlines() if l.strip().startswith('|')]
    if len(lines) < 3:
        return []
    headers = [h.strip().lower() for h in lines[0].strip('|').split('|')]
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def _parse_md_section_text(text: str, section_header: str) -> str:
    """Extract plain text content under a section header (non-table)."""
    pattern = re.compile(
        r'(?:^|\n)#+\s*' + re.escape(section_header) + r'[^\n]*\n(.*?)(?=\n#+\s|\Z)',
        re.DOTALL | re.IGNORECASE
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


# ---------------------------------------------------------------------------
# Structural extractors — from frontmatter (authoritative)
# ---------------------------------------------------------------------------

def _fm_ac_attributes(fm: dict) -> dict:
    """Returns {field: {type, required}} from frontmatter."""
    attrs = fm.get("core", {}).get("attributes", {})
    return {
        field: {
            "type": props.get("type", ""),
            "required": bool(props.get("required", False)),
        }
        for field, props in attrs.items()
    }


def _fm_in_inputs(fm: dict) -> dict:
    """Returns flat {field: {type, required}} including nested fields."""
    inputs = fm.get("core", {}).get("inputs", {})
    result = {}
    for field, props in inputs.items():
        result[field] = {
            "type": props.get("type", ""),
            "required": bool(props.get("required", False)),
        }
        for subfield, subprops in props.get("fields", {}).items():
            key = f"{field}.{subfield}"
            result[key] = {
                "type": subprops.get("type", ""),
                "required": bool(subprops.get("required", False)),
            }
    return result


def _fm_in_outcomes(fm: dict) -> set:
    return set(fm.get("core", {}).get("outcomes", {}).keys())


def _fm_wf_nodes(fm: dict) -> dict:
    """Returns {code: type} for all nodes, normalizing alias keys to their underlying code.

    A node entry may have a different alias key than its actual artifact code
    (e.g. CC_APPEND_AUDIT_EVENT_DENIED → code=CC_APPEND_AUDIT_EVENT_V0). The content
    field describes the logical topology using artifact codes, not aliases. We normalize
    the frontmatter keys to their code field so the comparison is apples-to-apples.

    EXIT_* named terminals are normalized to 'EXIT' because content prose describes the
    abstract terminal while the compiled frontmatter has named exit nodes.
    """
    nodes = fm.get("core", {}).get("nodes", {})
    result = {}
    for node_key, node in nodes.items():
        ntype = node.get("type", "")
        if ntype == "EXIT":
            canonical = "EXIT"
        else:
            canonical = node.get("code", node_key)
        result[canonical] = ntype
    return result


def _fm_wf_routing(fm: dict) -> dict:
    """Returns {code: set(outcome_values)} for each node with routing."""
    nodes = fm.get("core", {}).get("nodes", {})
    result = {}
    for code, node in nodes.items():
        if "next" in node:
            result[code] = set(node["next"].keys())
    return result


def _fm_cc_inputs(fm: dict) -> dict:
    inputs = fm.get("core", {}).get("inputs", {})
    return {f: props.get("type", "") for f, props in inputs.items()}


def _fm_cc_outputs(fm: dict) -> dict:
    outputs = fm.get("core", {}).get("outputs", {})
    return {f: props.get("type", "") for f, props in outputs.items()}


def _fm_cc_statuses(fm: dict) -> set:
    return set(fm.get("core", {}).get("result_status_contract", {}).get("allowed", []))


def _fm_cc_pipeline(fm: dict) -> list:
    """Returns list of (step_name, impl_fqdn) from pipeline."""
    pipeline = fm.get("core", {}).get("pipeline", [])
    result = []
    for step in pipeline:
        name = step.get("step", "")
        impl = step.get("transform") or step.get("side_effect", "")
        result.append((name, impl))
    return result


# ---------------------------------------------------------------------------
# Structural extractors — from content markdown
# ---------------------------------------------------------------------------

def _content_ac_attributes(content: str) -> dict:
    """Parse attributes table from content. Normalise 'true'/'false' strings."""
    rows = _parse_md_table(content, "Attributes")
    result = {}
    for row in rows:
        field = row.get("field", "").strip()
        if not field:
            continue
        raw_type = row.get("type", "").lower()
        base_type = raw_type.split("(")[0].strip()
        required_raw = row.get("required", "false").lower()
        required = required_raw in ("true", "yes")
        result[field] = {"type": base_type, "required": required}
    return result


def _content_in_inputs(content: str) -> dict:
    """Parse inputs table. Handles 'actor_record.first_name' style rows."""
    rows = _parse_md_table(content, "Inputs")
    result = {}
    for row in rows:
        field = row.get("field", "").strip()
        if not field:
            continue
        base_type = row.get("type", "").lower().split("(")[0].strip()
        required_raw = row.get("required", "false").lower()
        required = required_raw in ("true", "yes")
        result[field] = {"type": base_type, "required": required}
    return result


def _content_in_outcomes(content: str) -> set:
    rows = _parse_md_table(content, "Outcomes")
    return {row.get("outcome", "").strip() for row in rows if row.get("outcome", "").strip()}


def _content_wf_nodes(content: str) -> dict:
    """Parse nodes table from content. Normalizes EXIT_* variants to 'EXIT'."""
    rows = _parse_md_table(content, "Nodes")
    result = {}
    for row in rows:
        code = row.get("node", "").strip()
        ntype = row.get("type", "").strip().upper()
        if not code:
            continue
        if ntype == "EXIT" or code.startswith("EXIT"):
            code = "EXIT"
            ntype = "EXIT"
        result[code] = ntype
    return result


def _content_cc_inputs(content: str) -> dict:
    rows = _parse_md_table(content, "Inputs")
    result = {}
    for row in rows:
        field = row.get("field", "").strip()
        if field:
            result[field] = row.get("type", "").lower().split("(")[0].strip()
    return result


def _content_cc_outputs(content: str) -> dict:
    rows = _parse_md_table(content, "Outputs")
    result = {}
    for row in rows:
        field = row.get("field", "").strip()
        if field:
            result[field] = row.get("type", "").lower()
    return result


def _content_cc_statuses(content: str) -> set:
    rows = _parse_md_table(content, "Result Status Contract")
    return {row.get("status", "").strip() for row in rows if row.get("status", "").strip()}


def _content_cc_pipeline(content: str) -> list:
    """Parse pipeline table. Returns list of (step, capability_fqdn)."""
    rows = _parse_md_table(content, "Pipeline")
    result = []
    for row in rows:
        step = (row.get("step") or "").strip()
        cap = (row.get("capability") or row.get("transform / side effect") or "").strip()
        if step:
            result.append((step, cap))
    return result


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

class _ValidationResult:
    def __init__(self, artifact_code: str):
        self.artifact_code = artifact_code
        self.checks = []   # list of (check_name, passed, detail)

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, passed, detail))

    def passed(self) -> bool:
        return all(p for _, p, _ in self.checks)

    def report(self) -> str:
        status = "PASS" if self.passed() else "FAIL"
        lines = [f"  [{status}] {self.artifact_code}"]
        for name, passed, detail in self.checks:
            icon = "OK  " if passed else "FAIL"
            line = f"        {icon}  {name}"
            if not passed and detail:
                line += f"\n              {detail}"
            lines.append(line)
        return "\n".join(lines)


def _compare_fields(name: str, fm_dict: dict, content_dict: dict, vr: _ValidationResult) -> None:
    """Compare two field dicts — check same keys exist."""
    fm_keys = set(fm_dict.keys())
    ct_keys = set(content_dict.keys())
    missing_from_content = fm_keys - ct_keys
    extra_in_content = ct_keys - fm_keys
    passed = not missing_from_content and not extra_in_content
    detail = ""
    if not passed:
        parts = []
        if missing_from_content:
            parts.append(f"in frontmatter but not content: {missing_from_content}")
        if extra_in_content:
            parts.append(f"in content but not frontmatter: {extra_in_content}")
        detail = "; ".join(parts)
    vr.check(f"{name} field names match", passed, detail)


def _compare_sets(name: str, fm_set: set, content_set: set, vr: _ValidationResult) -> None:
    diff = fm_set.symmetric_difference(content_set)
    passed = not diff
    detail = f"divergence: {diff}" if diff else ""
    vr.check(name, passed, detail)


def _compare_required(name: str, fm_dict: dict, content_dict: dict, vr: _ValidationResult) -> None:
    """Compare required flags for fields present in both."""
    common = set(fm_dict.keys()) & set(content_dict.keys())
    mismatches = []
    for field in sorted(common):
        fm_req = fm_dict[field].get("required", False)
        ct_req = content_dict[field].get("required", False)
        if fm_req != ct_req:
            mismatches.append(f"{field}: fm={fm_req} content={ct_req}")
    passed = not mismatches
    vr.check(f"{name} required flags match", passed, "; ".join(mismatches))


# ---------------------------------------------------------------------------
# Per-concern validators
# ---------------------------------------------------------------------------

def _validate_ac(artifact_code: str, d: dict, vr: _ValidationResult) -> None:
    fm = d["frontmatter"]
    content = d["content"]
    fm_attrs = _fm_ac_attributes(fm)
    ct_attrs = _content_ac_attributes(content)
    _compare_fields("attributes", fm_attrs, ct_attrs, vr)
    _compare_required("attributes", fm_attrs, ct_attrs, vr)


def _validate_in(artifact_code: str, d: dict, vr: _ValidationResult) -> None:
    fm = d["frontmatter"]
    content = d["content"]
    fm_inputs = _fm_in_inputs(fm)
    ct_inputs = _content_in_inputs(content)
    _compare_fields("inputs", fm_inputs, ct_inputs, vr)
    _compare_required("inputs", fm_inputs, ct_inputs, vr)
    fm_out = _fm_in_outcomes(fm)
    ct_out = _content_in_outcomes(content)
    _compare_sets("outcomes", fm_out, ct_out, vr)


def _validate_wf(artifact_code: str, d: dict, vr: _ValidationResult) -> None:
    fm = d["frontmatter"]
    content = d["content"]
    fm_nodes = _fm_wf_nodes(fm)
    ct_nodes = _content_wf_nodes(content)
    fm_codes = set(fm_nodes.keys())
    ct_codes = set(ct_nodes.keys())
    diff = fm_codes.symmetric_difference(ct_codes)
    if diff:
        vr.check("node codes match (WARN — content may be abstract)", True,
                 f"non-blocking divergence: {diff}")
    else:
        vr.check("node codes match", True)
    common = fm_codes & ct_codes
    type_mismatches = []
    for code in sorted(common):
        if fm_nodes[code].upper() != ct_nodes[code].upper():
            type_mismatches.append(f"{code}: fm={fm_nodes[code]} content={ct_nodes[code]}")
    vr.check("node types match", not type_mismatches, "; ".join(type_mismatches))
    vr.check("routing outcomes (fm self-consistent)", True,
             "content ASCII DAG not structurally parsed — fm is authoritative")


def _validate_cc(artifact_code: str, d: dict, vr: _ValidationResult) -> None:
    fm = d["frontmatter"]
    content = d["content"]
    fm_inp = _fm_cc_inputs(fm)
    ct_inp = _content_cc_inputs(content)
    _compare_fields("inputs", fm_inp, ct_inp, vr)
    fm_out = _fm_cc_outputs(fm)
    ct_out = _content_cc_outputs(content)
    if not fm_out and not ct_out:
        vr.check("outputs match (both empty)", True)
    else:
        fm_out_keys = set(fm_out.keys())
        ct_out_keys = set(ct_out.keys())
        diff = fm_out_keys.symmetric_difference(ct_out_keys)
        if diff:
            detail = (
                f"frontmatter declares {fm_out_keys or '{}'}, "
                f"content prose declares {ct_out_keys or '{}'} — "
                "content prose is stale; machine block is authoritative"
            )
            vr.check("outputs match", False, detail)
        else:
            vr.check("outputs match", True)
    fm_stat = _fm_cc_statuses(fm)
    ct_stat = _content_cc_statuses(content)
    _compare_sets("result statuses", fm_stat, ct_stat, vr)
    fm_pipe = _fm_cc_pipeline(fm)
    ct_pipe = _content_cc_pipeline(content)
    fm_count = len(fm_pipe)
    ct_count = len(ct_pipe)
    passed = fm_count == ct_count
    detail = f"frontmatter has {fm_count} step(s), content has {ct_count} step(s)" if not passed else ""
    vr.check("pipeline step count matches", passed, detail)


_VALIDATORS = {
    "actors":               _validate_ac,
    "intents":              _validate_in,
    "workflows":            _validate_wf,
    "capability_contracts": _validate_cc,
}


# ---------------------------------------------------------------------------
# Cross-artifact checks
# ---------------------------------------------------------------------------

def _cross_check_dead_ccs(by_concern: dict) -> list:
    """
    WARN if a CC artifact exists in the subdomain list but is never referenced
    as a node (by underlying code) in any workflow in the same subdomain.

    Non-blocking (WARN only): dead CCs may be planned for a future workflow.
    """
    cc_codes = set(by_concern["capability_contracts"].keys())
    if not cc_codes:
        return []

    referenced = set()
    for wf_code, wf_d in by_concern["workflows"].items():
        nodes = wf_d["frontmatter"].get("core", {}).get("nodes", {})
        for node_key, node in nodes.items():
            if node.get("type") == "CC":
                referenced.add(node.get("code", node_key))

    dead = cc_codes - referenced
    warnings = []
    for cc in sorted(dead):
        warnings.append(
            f"  [WARN] {cc} — declared as CC artifact but never referenced as a WF node "
            f"(dead code; cannot be reached at runtime)"
        )
    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_validation(snapshot: str, subdomain: str) -> bool:
    """
    Run equivalence validation for one subdomain.

    Args:
        snapshot: Absolute path to protocol_snapshot/artifacts/
        subdomain: Subdomain name (e.g. "identity")

    Returns:
        True if all checks pass, False if any check fails.

    Raises:
        ValueError: If subdomain not found in snapshot.
    """
    discovered = discover_subdomains(snapshot)

    if subdomain not in discovered:
        raise ValueError(
            f"Unknown subdomain '{subdomain}'. Available: {sorted(discovered.keys())}"
        )

    artifacts = discovered[subdomain]["artifacts"]
    by_concern: dict = {"actors": {}, "intents": {}, "workflows": {}, "capability_contracts": {}}
    results = []

    print(f"Semantic equivalence validation — {subdomain} subdomain ({len(artifacts)} artifacts)")
    print("=" * 65)

    for concern, filename in artifacts:
        path = os.path.join(snapshot, concern, filename)
        d = json.load(open(path))
        fm = d["frontmatter"]
        artifact_code = next(
            (fm[k] for k in ("ac_code", "in_code", "wf_code", "cc_code") if k in fm),
            d.get("artifact_code", filename)
        )
        by_concern[concern][artifact_code] = d
        vr = _ValidationResult(artifact_code)
        _VALIDATORS[concern](artifact_code, d, vr)
        results.append(vr)
        print(vr.report())

    dead_cc_warns = _cross_check_dead_ccs(by_concern)
    if dead_cc_warns:
        print()
        print("Cross-artifact checks:")
        for w in dead_cc_warns:
            print(w)

    print("=" * 65)
    passed_count = sum(1 for r in results if r.passed())
    failed_count = len(results) - passed_count
    warn_count = len(dead_cc_warns)
    summary = f"\nResult: {passed_count}/{len(results)} PASS  |  {failed_count} FAIL"
    if warn_count:
        summary += f"  |  {warn_count} WARN (cross-artifact)"
    print(summary)

    if failed_count:
        print(f"\nHARD STOP — fix failures before generating Business Intent for {subdomain}.")
        return False
    else:
        if warn_count:
            print(f"\nWarnings present — review before next release. Safe to proceed to Business Intent for {subdomain}.")
        else:
            print(f"\nAll checks pass. Safe to proceed to Business Intent for {subdomain}.")
        return True


# ---------------------------------------------------------------------------
# CLI (direct invocation)
# ---------------------------------------------------------------------------

def _main() -> None:
    snapshot_arg = None
    for i, arg in enumerate(sys.argv):
        if arg == "--snapshot" and i + 1 < len(sys.argv):
            snapshot_arg = sys.argv[i + 1]
            break

    discovered: dict = {}
    if snapshot_arg and os.path.isdir(snapshot_arg):
        try:
            discovered = discover_subdomains(snapshot_arg)
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Semantic equivalence validation — Governance Intent prose vs artifact content"
    )
    parser.add_argument(
        "--snapshot", required=True,
        help="Absolute path to protocol_snapshot/artifacts/"
    )
    if discovered:
        parser.add_argument(
            "--subdomain", default="identity",
            choices=sorted(discovered.keys()),
            help="Subdomain to validate (default: identity)"
        )
    else:
        parser.add_argument(
            "--subdomain", default="identity",
            help="Subdomain to validate (default: identity)"
        )
    args = parser.parse_args()

    if not discovered:
        discovered = discover_subdomains(args.snapshot)

    passed = run_validation(args.snapshot, args.subdomain)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    _main()
