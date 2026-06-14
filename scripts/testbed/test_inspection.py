#!/usr/bin/env python3
"""
Inspection library testbed — store join, lifecycle, behavior logic, traces, CI gates.

Self-contained: fixtures are built in temp directories; pi itself stays
write-free (only the fixtures write, and only under tmp).

Run: python scripts/testbed/test_inspection.py
"""

import json
import sys
import tempfile
from pathlib import Path

from click.testing import CliRunner

from pgs_compiler.compiler.projections.store_index import build_store_index
from pgs_compiler.inspection import behavior_logic
from pgs_compiler.inspection.cli import pi
from pgs_compiler.inspection.loader import classify_lifecycle, parse_header_fields
from pgs_compiler.inspection.traces import list_traces, resolve_trace_jsonl

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def test_parse_header_fields() -> None:
    content = (
        "# WF_X_V0\n\n## Header (Mandatory)\n\n"
        "- **Artifact Code:** WF_X_V0\n"
        "- **Status:** canonical\n"
        "- **Supersedes:** NONE\n"
    )
    fields = parse_header_fields(content)
    check("parse_header_fields_status", fields.get("Status") == "canonical")
    check("parse_header_fields_supersedes", fields.get("Supersedes") == "NONE")


def test_classify_lifecycle() -> None:
    check("lifecycle_canonical_active", classify_lifecycle("canonical") == "ACTIVE")
    check("lifecycle_retired", classify_lifecycle("Retired") == "RETIRED")
    check("lifecycle_draft_unknown", classify_lifecycle("draft") == "UNKNOWN")
    check("lifecycle_none_unknown", classify_lifecycle(None) == "UNKNOWN")


def _write(root: Path, relative: str, payload: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_store_index_join() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write(ws, "protocol_snapshot/artifacts/structures/d__STRUCTURE_D_STORAGE_V0.json", {
            "fqdn_id": "d::STRUCTURE_D_STORAGE_V0",
            "frontmatter": {"core": {
                "domain": "d",
                "entity_stores": {
                    "ACTOR": {"path": "d/identity/actors.json", "description": "actors"},
                },
            }},
        })
        _write(ws, "protocol_snapshot/artifacts/runtime_bindings/d__RB_X_V0.json", {
            "fqdn_id": "d::RB_X_V0",
            "frontmatter": {"core": {"bindings": {
                "cse::CS_REG_V0": {"policy": {"path": "{{module_data_root}}/d/identity/actors.json"}},
                "cse::CS_MAIL_V0": {"policy": {"enabled": True}},
            }}},
        })
        _write(ws, "evidence_snapshot/d/evidence.json", {
            "nodes": [], "event_catalog": [],
            "edges": [
                {"kind": "WF_BINDS_RB", "source_fqdn": "d::WF_X_V0", "target_fqdn": "d::RB_X_V0", "metadata": {}},
                {"kind": "WF_CONTAINS_NODE", "source_fqdn": "d::WF_X_V0", "target_fqdn": "d::CC_PERSIST_V0", "metadata": {}},
                {"kind": "CC_BINDS_CS", "source_fqdn": "d::CC_PERSIST_V0", "target_fqdn": "cse::CS_REG_V0", "metadata": {}},
            ],
        })
        index = build_store_index(ws)
        entry = index["stores"]["d::ACTOR"]
        declaration = entry["declarations"][0]
        check("store_join_count", index["store_count"] == 1)
        check("store_join_owner", declaration["declared_by"] == "d::STRUCTURE_D_STORAGE_V0")
        bindings = declaration["bindings"]
        check("store_join_rb", len(bindings) == 1 and bindings[0]["rb"] == "d::RB_X_V0")
        check("store_join_wf", bindings[0]["workflows"] == ["d::WF_X_V0"])
        check("store_join_cc", bindings[0]["consumer_ccs"] == ["d::CC_PERSIST_V0"])
        check("store_join_deterministic", build_store_index(ws) == index)


_BEHAVIOR_LOGIC_GRAPH = {
    "wf_id": "WF_X_V0",
    "entry": "IN_X_V0",
    "nodes": [
        {"id": "IN_X_V0", "type": "IN"},
        {"id": "CC_A_V0", "type": "CC"},
    ],
    "edges": [
        {"from": "IN_X_V0", "to": "CC_A_V0", "condition": "ACK"},
        {"from": "IN_X_V0", "to": "EXIT", "condition": "NACK"},
        {"from": "CC_A_V0", "to": "EXIT_SUCCESS", "condition": "SUCCESS"},
    ],
    "execution_paths": [],
}


def test_behavior_logic_execution_tree() -> None:
    tree = behavior_logic.execution_tree(_BEHAVIOR_LOGIC_GRAPH)
    check("behavior_logic_tree_root", tree["fqdn"] == "IN_X_V0" and tree["kind"] == "IN")
    conditions = sorted(c["edge_kind"] for c in tree["children"])
    check("behavior_logic_tree_routes", conditions == ["ACK", "NACK"])
    ack = next(c for c in tree["children"] if c["edge_kind"] == "ACK")
    check("behavior_logic_tree_leaf", ack["children"][0]["fqdn"] == "EXIT_SUCCESS")


def test_behavior_logic_renderers() -> None:
    mermaid = behavior_logic.to_mermaid(_BEHAVIOR_LOGIC_GRAPH)
    dot = behavior_logic.to_dot(_BEHAVIOR_LOGIC_GRAPH)
    check("behavior_logic_mermaid_edges", "IN_X_V0 -->|ACK| CC_A_V0" in mermaid)
    check("behavior_logic_mermaid_terminal", 'EXIT(["EXIT"])' in mermaid)
    check("behavior_logic_dot_edge", '"CC_A_V0" -> "EXIT_SUCCESS" [label="SUCCESS"];' in dot)
    check("behavior_logic_render_deterministic",
          mermaid == behavior_logic.to_mermaid(_BEHAVIOR_LOGIC_GRAPH) and dot == behavior_logic.to_dot(_BEHAVIOR_LOGIC_GRAPH))


def test_trace_resolution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        trace_dir = ws / "traces" / "d" / "WF_X_V0" / "TR123"
        trace_dir.mkdir(parents=True)
        (trace_dir / "TR123.jsonl").write_text("{}\n")
        records = list_traces(ws)
        check("trace_list", len(records) == 1 and records[0]["trace_id"] == "TR123")
        check("trace_resolve", resolve_trace_jsonl(ws, "TR123").name == "TR123.jsonl")
        try:
            resolve_trace_jsonl(ws, "MISSING")
            check("trace_missing_fails_hard", False)
        except Exception:
            check("trace_missing_fails_hard", True)


def test_strict_exit_codes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write(ws, "snapshot_status.json", {"status": "VALID", "snapshot_hash": "abc"})
        _write(ws, "conformance_results.json", {
            "schema_version": "v0", "artifact_count": 2, "passed": 1, "failed": 1,
            "all_passed": False,
            "cases": [
                {"fqdn": "d::CT_OK_V0", "passed": True, "error": None},
                {"fqdn": "d::CT_BAD_V0", "passed": False, "error": "boom"},
            ],
        })
        runner = CliRunner()
        plain = runner.invoke(pi, ["--workspace", str(ws), "snapshot", "violations"])
        strict = runner.invoke(pi, ["--workspace", str(ws), "snapshot", "violations", "--strict"])
        gate = runner.invoke(pi, ["--workspace", str(ws), "validate", "--strict"])
        check("violations_plain_exit0", plain.exit_code == 0, f"got {plain.exit_code}")
        check("violations_strict_exit1", strict.exit_code == 1, f"got {strict.exit_code}")
        check("validate_strict_exit1", gate.exit_code == 1, f"got {gate.exit_code}")
        check("violations_named", "d::CT_BAD_V0" in plain.output)

        _write(ws, "conformance_results.json", {
            "schema_version": "v0", "artifact_count": 1, "passed": 1, "failed": 0,
            "all_passed": True,
            "cases": [{"fqdn": "d::CT_OK_V0", "passed": True, "error": None}],
        })
        green = runner.invoke(pi, ["--workspace", str(ws), "validate", "--strict"])
        check("validate_strict_green_exit0", green.exit_code == 0, f"got {green.exit_code}")


def main() -> None:
    for test in (
        test_parse_header_fields,
        test_classify_lifecycle,
        test_store_index_join,
        test_behavior_logic_execution_tree,
        test_behavior_logic_renderers,
        test_trace_resolution,
        test_strict_exit_codes,
    ):
        test()
    print(f"\nPASSED: {PASS}/{PASS + FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
