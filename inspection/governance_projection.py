"""
governance_projection.py — Step 3 of pgs_spec_reverse_engineering_plan.md

Reads primary subdomain artifacts from protocol_snapshot and produces one Governance Intent
document per subdomain, containing all artifacts in concern order.

This is a compiler-owned module: it interprets protocol snapshot projections.
Authoring concerns (Business Intent) remain in pgs_agent.

Public API:
    run_projection(snapshot, output, subdomain) -> str
        Run governance projection for one subdomain. Returns output file path.

CLI (via pgs_compiler inspect-governance --mode project):
    python -m pgs_compiler.inspection.governance_projection \
        --snapshot   /abs/path/to/protocol_snapshot/artifacts \
        --output     /abs/path/to/output/dir \
        --subdomain  <subdomain>

Output: governance_intent_<subdomain>_v0.md
"""

import argparse
import json
import os

import yaml

from pgs_compiler.inspection.snapshot_discovery import discover_subdomains


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_artifact(snapshot_base: str, concern: str, filename: str) -> dict:
    path = os.path.join(snapshot_base, concern, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Artifact not found: {path}")
    with open(path) as f:
        return json.load(f)


def _render_table(headers: list, rows: list) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _machine_block(frontmatter: dict) -> str:
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return "\n".join([
        "<!-- MACHINE_BLOCK_BEGIN -->",
        "```yaml",
        yaml_str.rstrip(),
        "```",
        "<!-- MACHINE_BLOCK_END -->",
    ])


def _get_artifact_code(d: dict) -> str:
    fm = d["frontmatter"]
    for key in ("ac_code", "in_code", "wf_code", "cc_code"):
        if key in fm:
            return fm[key]
    return d.get("artifact_code", "UNKNOWN")


# ---------------------------------------------------------------------------
# Concern renderers
# ---------------------------------------------------------------------------

def _render_ac(artifact_code: str, d: dict) -> str:
    fm = d["frontmatter"]
    core = fm.get("core", {})

    lines = [
        f"# Governance Intent — {artifact_code}",
        f"**Artifact Type:** AC (Actor Context)  ",
        f"**Version:** `{fm.get('version', 'v0')}`  ",
        f"**Governed By:** `{fm.get('governed_by', '')}`  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        core.get("summary", ""),
        "",
        "## Description",
        "",
        core.get("description", ""),
        "",
        f"**Actor Type:** `{core.get('type', '')}`  ",
        "",
    ]

    attributes = core.get("attributes", {})
    if attributes:
        lines += ["## Attributes", ""]
        rows = []
        for field, props in attributes.items():
            ftype = props.get("type", "")
            required = "YES" if props.get("required") else "NO"
            default = str(props.get("default", "—"))
            items_type = props["items"].get("type", "") if "items" in props else "—"
            enum_vals = ", ".join(props["enum"]) if "enum" in props else "—"
            rows.append([field, ftype, required, default, items_type, enum_vals])
        lines.append(_render_table(
            ["Field", "Type", "Required", "Default", "Items Type", "Enum Values"],
            rows
        ))
        lines.append("")

    lines += ["---", "", "## Machine Block", "", _machine_block(fm), ""]
    return "\n".join(lines)


def _render_in(artifact_code: str, d: dict) -> str:
    fm = d["frontmatter"]
    core = fm.get("core", {})

    lines = [
        f"# Governance Intent — {artifact_code}",
        f"**Artifact Type:** IN (Intent)  ",
        f"**Version:** `{fm.get('version', 'v0')}`  ",
        f"**Governed By:** `{fm.get('governed_by', '')}`  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        core.get("summary", ""),
        "",
        "## Workflow Binding",
        "",
        f"`{core.get('workflow', '')}`",
        "",
        "## Input Fields",
        "",
    ]

    inputs = core.get("inputs", {})
    rows = []
    for field, props in inputs.items():
        ftype = props.get("type", "")
        required = "YES" if props.get("required") else "NO"
        description = props.get("description", "—")
        rows.append([field, ftype, required, description])
        for subfield, subprops in props.get("fields", {}).items():
            sftype = subprops.get("type", "")
            sfreq = "YES" if subprops.get("required") else "NO"
            sfmt = subprops.get("format", "—")
            rows.append([f"└ {subfield}", sftype, sfreq, f"format: {sfmt}"])
    lines.append(_render_table(["Field", "Type", "Required", "Description / Notes"], rows))
    lines.append("")

    lines += ["## Outcomes", ""]
    outcomes = core.get("outcomes", {})
    rows = [(outcome, props.get("description", "—")) for outcome, props in outcomes.items()]
    lines.append(_render_table(["Outcome", "Description"], rows))
    lines.append("")

    lines += ["---", "", "## Machine Block", "", _machine_block(fm), ""]
    return "\n".join(lines)


def _wf_node_order(nodes: dict, start_node: str) -> list:
    ordered = []
    visited: set = set()
    queue = [start_node]
    while queue:
        code = queue.pop(0)
        if code in visited or code not in nodes:
            continue
        visited.add(code)
        ordered.append(code)
        for target in nodes[code].get("next", {}).values():
            if target not in visited:
                queue.append(target)
    return ordered


def _render_wf(artifact_code: str, d: dict) -> str:
    fm = d["frontmatter"]
    core = fm.get("core", {})
    nodes = core.get("nodes", {})
    start_node = core.get("start_node", "")

    lines = [
        f"# Governance Intent — {artifact_code}",
        f"**Artifact Type:** WF (Workflow)  ",
        f"**Version:** `{fm.get('version', 'v0')}`  ",
        f"**Governed By:** `{fm.get('governed_by', '')}`  ",
        f"**Subdomain:** `{fm.get('subdomain', '')}`  ",
        f"**Runtime Binding:** `{fm.get('runtime_binding', '')}`  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        core.get("summary", ""),
        "",
        f"**Start Node:** `{start_node}`",
        "",
    ]

    admission = core.get("admission")
    if admission:
        lines += ["## Admission", ""]
        requires = admission.get("requires", [])
        lines.append(f"**Requires events:** {', '.join(f'`{e}`' for e in requires)}")
        bindings = admission.get("bindings", {})
        if bindings:
            rows = []
            for event, mapping in bindings.items():
                for target_field, source_field in mapping.items():
                    rows.append([event, target_field, source_field])
            lines.append("")
            lines.append(_render_table(["Event", "Target Field", "Source Field"], rows))
        lines.append("")

    lines += ["## Execution Nodes", ""]
    ordered = _wf_node_order(nodes, start_node)
    rows = []
    for code in ordered:
        node = nodes[code]
        ntype = node.get("type", "")
        routing = node.get("next", {})
        routing_str = ", ".join(f"{k} → {v}" for k, v in routing.items()) if routing else "—"
        rows.append([code, ntype, routing_str])
    lines.append(_render_table(["Node", "Type", "Routing Outcomes"], rows))
    lines.append("")

    lines += ["## Node Inputs (JSONPath Bindings)", ""]
    for code in ordered:
        node = nodes[code]
        node_inputs = node.get("inputs")
        if node_inputs:
            lines.append(f"**{code}:**")
            for k, v in node_inputs.items():
                if isinstance(v, str):
                    lines.append(f"- `{k}` ← `{v}`")
                else:
                    lines.append(f"- `{k}` ← _(inline object)_")
            lines.append("")

    lines += ["---", "", "## Machine Block", "", _machine_block(fm), ""]
    return "\n".join(lines)


def _render_cc(artifact_code: str, d: dict) -> str:
    fm = d["frontmatter"]
    core = fm.get("core", {})

    lines = [
        f"# Governance Intent — {artifact_code}",
        f"**Artifact Type:** CC (Capability Contract)  ",
        f"**Version:** `{fm.get('version', 'v0')}`  ",
        f"**Governed By:** `{fm.get('governed_by', '')}`  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        core.get("summary", ""),
        "",
        "## Inputs",
        "",
    ]

    inputs = core.get("inputs", {})
    if inputs:
        rows = [[f, p.get("type", ""), "YES" if p.get("required") else "NO"]
                for f, p in inputs.items()]
        lines.append(_render_table(["Field", "Type", "Required"], rows))
    else:
        lines.append("_No inputs declared._")
    lines.append("")

    lines += ["## Outputs", ""]
    outputs = core.get("outputs", {})
    if outputs:
        rows = [[f, p.get("type", "")] for f, p in outputs.items()]
        lines.append(_render_table(["Field", "Type"], rows))
    else:
        lines.append("_No outputs declared._")
    lines.append("")

    lines += ["## Result Status Contract", ""]
    rsc = core.get("result_status_contract", {})
    allowed = rsc.get("allowed", [])
    on_input_failure = rsc.get("on_input_failure", "—")
    rows = [[status, "—"] for status in allowed]
    lines.append(_render_table(["Status", "Condition"], rows))
    lines.append(f"\n**On input failure:** `{on_input_failure}`")
    lines.append("")

    lines += ["## Pipeline", ""]
    pipeline = core.get("pipeline", [])
    if pipeline:
        rows = []
        for step in pipeline:
            step_name = step.get("step", "")
            impl = step.get("transform") or step.get("side_effect", "—")
            op = step.get("op", "—")
            store = step.get("store", "—")
            step_outputs = step.get("outputs", {})
            out_str = ", ".join(
                f"`{k}` ← `{v}`" for k, v in step_outputs.items()
            ) if step_outputs else "—"
            result_surface = ", ".join(step.get("result_surface", [])) or "—"
            rows.append([step_name, impl, op, store, out_str, result_surface])
        lines.append(_render_table(
            ["Step", "Transform / Side Effect", "Op", "Store", "Outputs", "Result Surface"],
            rows
        ))
    else:
        lines.append("_No pipeline declared._")
    lines.append("")

    lines += ["---", "", "## Machine Block", "", _machine_block(fm), ""]
    return "\n".join(lines)


_CONCERN_RENDERERS = {
    "actors":               _render_ac,
    "intents":              _render_in,
    "workflows":            _render_wf,
    "capability_contracts": _render_cc,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_projection(snapshot: str, output: str, subdomain: str) -> str:
    """
    Run governance projection for one subdomain.

    Args:
        snapshot: Absolute path to protocol_snapshot/artifacts/
        output: Absolute path to output directory
        subdomain: Subdomain name (e.g. "identity")

    Returns:
        Path to the written governance intent file.

    Raises:
        ValueError: If subdomain not found in snapshot.
        FileNotFoundError: If an expected artifact file is missing.
    """
    discovered = discover_subdomains(snapshot)

    if subdomain not in discovered:
        raise ValueError(
            f"Unknown subdomain '{subdomain}'. Available: {sorted(discovered.keys())}"
        )

    sd = discovered[subdomain]
    artifacts = sd["artifacts"]

    os.makedirs(output, exist_ok=True)

    sections = []
    errors = []

    for concern, filename in artifacts:
        try:
            d = _load_artifact(snapshot, concern, filename)
            artifact_code = _get_artifact_code(d)
            renderer = _CONCERN_RENDERERS[concern]
            sections.append(renderer(artifact_code, d))
            print(f"  OK  {artifact_code}")
        except Exception as e:
            errors.append((filename, str(e)))
            print(f"  ERR {filename}: {e}")

    if errors:
        raise RuntimeError(
            f"Governance projection failed for '{subdomain}': "
            + "; ".join(f"{f}: {m}" for f, m in errors)
        )

    domain = sd["domain"]
    header = "\n".join([
        f"# Governance Intent: {domain} / {subdomain}",
        f"**Domain:** {domain}  ",
        f"**Subdomain:** {subdomain}  ",
        f"**Version:** V0  ",
        f"**Status:** DRAFT  ",
        f"**Artifacts:** {len(sections)}  ",
        "",
        "---",
        "",
    ])
    body = "\n\n---\n\n".join(sections)
    out_path = os.path.join(output, f"governance_intent_{subdomain}_v0.md")
    with open(out_path, "w") as f:
        f.write(header + body)

    return out_path


# ---------------------------------------------------------------------------
# CLI (direct invocation)
# ---------------------------------------------------------------------------

def _main() -> None:
    import sys as _sys

    # Pre-parse --snapshot for dynamic subdomain choices
    snapshot_arg = None
    for i, arg in enumerate(_sys.argv):
        if arg == "--snapshot" and i + 1 < len(_sys.argv):
            snapshot_arg = _sys.argv[i + 1]
            break

    discovered: dict = {}
    if snapshot_arg and os.path.isdir(snapshot_arg):
        try:
            discovered = discover_subdomains(snapshot_arg)
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Extract Governance Intent per-subdomain document from protocol_snapshot"
    )
    parser.add_argument("--snapshot", required=True,
                        help="Absolute path to protocol_snapshot/artifacts/")
    parser.add_argument("--output", required=True,
                        help="Absolute path to output directory")
    if discovered:
        parser.add_argument("--subdomain", required=True,
                            choices=sorted(discovered.keys()),
                            help="Subdomain to project")
    else:
        parser.add_argument("--subdomain", required=True,
                            help="Subdomain to project")
    args = parser.parse_args()

    print(f"Snapshot  : {args.snapshot}")
    print(f"Output    : {args.output}")
    print(f"Subdomain : {args.subdomain}")

    out_path = run_projection(args.snapshot, args.output, args.subdomain)
    print(f"\nDone. Governance Intent written to: {out_path}")


if __name__ == "__main__":
    _main()
