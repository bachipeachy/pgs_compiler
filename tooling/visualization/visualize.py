#!/usr/bin/env python3
"""
visualize.py — Unified workflow visualization tool

Usage:
    # Single workflow
    python visualize.py --workflow WF_CREATE_WALLET_V0

    # Single workflow with execution trace (red path)
    python visualize.py --workflow WF_CREATE_WALLET_V0 --trace T_12345

    # All segments from registry
    python visualize.py --segments

    # Specific segment
    python visualize.py --segment PS_ACTOR_ONBOARDING
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pgs_governance.structure.structure.resolution import bootstrap, paths

bootstrap()

# If invoked from a different directory (e.g., pgs_sandbox), preserve it as workspace_root

from pgs_governance.structure.structure.loading.protocol_loader import ProtocolLoader
from omnibachi.implementation.execution.machine import build_dag_from_workflow
from pgs_compiler.tooling.visualization.workflow_to_dot import workflow_to_dot
from pgs_compiler.tooling.visualization.segment_to_dot import segment_to_dot
from pgs_compiler.tooling.visualization.dot_renderer import dot_string_to_png


def load_workflow_dag(workflow_code: str, structure_code: str = "fb.topology::STRUCTURE_RUNTIME_EXECUTION_V0"):
    """
    Load workflow spec and build DAG.

    Uses STRUCTURE artifact for path resolution (no module mapping).
    Returns domain extracted from workflow source path for domain-scoped operations.
    """
    from pgs_governance.structure.structure.loading.protocol_loader import load_bootstrap_artifact, resolve_artifact_with_path, resolve_search_roots
    from pgs_governance.structure.structure.resolution.domain_resolver import extract_domain_from_artifact_path

    # Bootstrap STRUCTURE artifact from .md (read-only)
    structure_artifact = load_bootstrap_artifact(structure_code)

    # Get search roots from STRUCTURE
    search_roots = resolve_search_roots(structure_artifact)

    if not search_roots:
        raise FileNotFoundError(
            f"No search roots configured in STRUCTURE {structure_code}. "
            f"Run compiler first."
        )

    # Load workflow artifact WITH source path for domain extraction
    wf_artifact, wf_source_path = resolve_artifact_with_path(workflow_code, search_roots)

    # Extract domain from artifact path
    domain = extract_domain_from_artifact_path(wf_source_path)

    # Load workflow from compiled artifacts (STRUCTURE-driven discovery)
    loader = ProtocolLoader(search_roots)
    spec = loader.load(workflow_code=workflow_code)

    dag = build_dag_from_workflow(spec["workflow_spec"])

    return dag, spec, structure_artifact, domain


def load_trace(trace_path: Path) -> list[dict]:
    """Load JSONL trace file."""
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    events = []
    with trace_path.open() as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    return events


def show_errors(trace_path_or_id: str, structure_code: str = "fb.topology::STRUCTURE_RUNTIME_EXECUTION_V0"):
    """
    Show all errors from a trace file (V0 trace enhancement).

    Args:
        trace_path_or_id: Full path to trace .jsonl file (e.g., from CLI output)
        structure_code: STRUCTURE artifact (unused - kept for signature compatibility)
    """
    trace_path = Path(trace_path_or_id)

    # If given just ID (starts with T_), cannot resolve without domain
    if not trace_path.exists() and trace_path_or_id.startswith("T_"):
        print(f"❌ Trace ID alone insufficient. Provide full path to .jsonl file.", file=sys.stderr)
        print(f"   Example: pgs_domains/domains/DOMAIN/testbed/outputs/traces/T_.../T_....jsonl", file=sys.stderr)
        sys.exit(1)

    if not trace_path.exists():
        print(f"❌ Trace file not found: {trace_path}", file=sys.stderr)
        sys.exit(1)

    # Load trace and filter for ERROR events
    errors = []
    with trace_path.open() as f:
        for line in f:
            if line.strip():
                event = json.loads(line)
                # Check if this is an ERROR event
                if event.get("event_type") == "error":
                    # Extract payload which contains error details
                    payload = event.get("payload", {})
                    if payload.get("component"):
                        errors.append({
                            "timestamp": event.get("timestamp"),
                            "component": payload.get("component"),
                            "error_type": payload.get("error_type"),
                            "message": payload.get("message"),
                            "traceback": payload.get("traceback"),
                            "workflow": payload.get("workflow"),
                            "node_id": payload.get("node_id"),
                        })

    if not errors:
        print("✅ No errors captured in trace")
        return

    print(f"\n❌ {len(errors)} ERROR(S) CAPTURED:\n")
    for err in errors:
        print(f"[{err['timestamp']}]")
        print(f"Component: {err['component']}")
        if err.get('workflow'):
            print(f"Workflow: {err['workflow']}")
        if err.get('node_id'):
            print(f"Node: {err['node_id']}")
        print(f"Error: {err['error_type']}: {err['message']}")
        if err.get('traceback'):
            print(f"\nTraceback:")
            print(err['traceback'])
        print("-" * 80)
        print()


def render_markdown(trace_path_or_id: str, structure_code: str = "fb.topology::STRUCTURE_RUNTIME_EXECUTION_V0"):
    """
    Render trace as Markdown (derived artifact for human readability).

    Args:
        trace_path_or_id: Full path to trace .jsonl file
        structure_code: STRUCTURE artifact (unused - kept for signature compatibility)

    Writes:
        T_xxx.md in same directory as T_xxx.jsonl
    """
    trace_path = Path(trace_path_or_id)

    # Validate path
    if not trace_path.exists() and trace_path_or_id.startswith("T_"):
        print(f"❌ Trace ID alone insufficient. Provide full path to .jsonl file.", file=sys.stderr)
        print(f"   Example: pgs_domains/domains/DOMAIN/testbed/outputs/traces/T_.../T_....jsonl", file=sys.stderr)
        sys.exit(1)

    if not trace_path.exists():
        print(f"❌ Trace file not found: {trace_path}", file=sys.stderr)
        sys.exit(1)

    # Load trace events
    events = []
    with trace_path.open() as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))

    # Extract summary
    exec_start = next((e for e in events if e.get("event_type") == "execution_start"), None)
    exec_complete = next((e for e in events if e.get("event_type") == "workflow_complete"), None)
    violations = [e for e in events if e.get("event_type") == "violation"]
    errors = [e for e in events if e.get("event_type") == "error"]
    node_ends = [e for e in events if e.get("event_type") == "node_end"]

    workflow_code = exec_start.get("payload", {}).get("workflow_code", "UNKNOWN") if exec_start else "UNKNOWN"
    status = exec_complete.get("payload", {}).get("status", "UNKNOWN") if exec_complete else "UNKNOWN"
    duration_ms = exec_complete.get("payload", {}).get("duration_ms", 0) if exec_complete else 0
    exit_reason = exec_complete.get("payload", {}).get("exit_reason_code", "") if exec_complete else ""

    # Determine execution phase
    if violations:
        first_violation = violations[0]
        violation_node = first_violation.get("payload", {}).get("node_id", "")
        if violation_node == "ADMISSION":
            exec_phase = "ADMISSION"
        else:
            exec_phase = "MID-WORKFLOW"
    else:
        exec_phase = "FULL DAG"

    # Count nodes executed (success case)
    nodes_executed = len([n for n in node_ends if n.get("payload", {}).get("status") == "SUCCESS"])

    # Build Markdown
    md = []
    md.append(f"# Execution Trace")
    md.append(f"")
    md.append(f"**Workflow**: `{workflow_code}`")
    md.append(f"**Execution ID**: `{trace_path.stem}`")
    md.append(f"")

    # Summary
    md.append(f"## Summary")
    md.append(f"")
    md.append(f"- **Status**: {status}")
    md.append(f"- **Duration**: {duration_ms} ms")
    # Add execution phase
    if violations:
        md.append(f"- **Failure Phase**: {exec_phase}")
    else:
        md.append(f"- **Execution Phase**: {exec_phase}")
    # Add node count
    if nodes_executed > 0:
        md.append(f"- **Nodes Executed**: {nodes_executed}")
    if exit_reason:
        md.append(f"- **Exit Reason**: {exit_reason}")
    md.append(f"")

    # Failure point — anchor the first violation
    if violations:
        first_violation = violations[0]
        v_payload = first_violation.get("payload", {})
        failure_node = v_payload.get("node_id", "UNKNOWN")
        failure_reason = v_payload.get("constraint") or v_payload.get("message", "")

        # Determine impact based on phase
        if exec_phase == "ADMISSION":
            impact = "Workflow did not enter execution DAG"
        else:
            impact = f"Workflow halted at {failure_node}"

        md.append(f"## 🔴 Failure Point")
        md.append(f"")
        md.append(f"- **Stage**: {failure_node}")
        md.append(f"- **Reason**: {failure_reason}")
        md.append(f"- **Impact**: {impact}")
        md.append(f"")

    # Violations
    if violations:
        md.append(f"## ⚠️ Protocol Violations")
        md.append(f"")
        for v in violations:
            payload = v.get("payload", {})
            md.append(f"### {payload.get('node_id')}")
            md.append(f"")
            md.append(f"- **Code**: `{payload.get('violation_code')}`")
            md.append(f"- **Message**: {payload.get('message')}")
            if payload.get("field"):
                md.append(f"- **Field**: `{payload.get('field')}`")
            if payload.get("constraint"):
                md.append(f"- **Constraint**: {payload.get('constraint')}")
            if payload.get("actual_value") is not None:
                md.append(f"- **Actual**: `{payload.get('actual_value')}`")
            if payload.get("expected_value") is not None:
                md.append(f"- **Expected**: `{payload.get('expected_value')}`")
            md.append(f"")

    # Errors (execution artifacts only)
    if errors:
        md.append(f"## ❌ Error (Execution)")
        md.append(f"")
        for err in errors:
            payload = err.get("payload", {})
            md.append(f"- **Type**: `{payload.get('error_type')}`")
            md.append(f"- **Origin**: `{payload.get('component')}`")
            if payload.get("traceback"):
                md.append(f"")
                md.append(f"```")
                md.append(payload.get("traceback"))
                md.append(f"```")
            md.append(f"")

    # Execution flow
    md.append(f"## Execution Flow")
    md.append(f"")
    flow_num = 0
    for event in events:
        event_type = event.get("event_type")
        payload = event.get("payload", {})

        # Skip node_start (noise - we only care about results)
        if event_type == "node_start":
            continue

        flow_num += 1

        if event_type == "execution_start":
            md.append(f"{flow_num}. START → {payload.get('workflow_code')}")
        elif event_type == "node_end":
            md.append(f"{flow_num}. {payload.get('node_id')} → {payload.get('status')}")
        elif event_type == "capability_dispatch":
            md.append(f"{flow_num}. {payload.get('cc_code')} → SUCCESS")
        elif event_type == "violation":
            md.append(f"{flow_num}. VIOLATION → {payload.get('violation_code')}")
        elif event_type == "error":
            md.append(f"{flow_num}. ERROR → {payload.get('error_type')}")
        elif event_type == "workflow_complete":
            md.append(f"{flow_num}. EXIT → {payload.get('status')}")
        else:
            md.append(f"{flow_num}. {event_type}")

    # Write MD file (same directory as JSONL)
    output_path = trace_path.parent / f"{trace_path.stem}.md"
    output_path.write_text("\n".join(md), encoding="utf-8")

    print(f"✅ Markdown trace: {output_path}")


def show_violations(trace_path_or_id: str, structure_code: str = "fb.topology::STRUCTURE_RUNTIME_EXECUTION_V0"):
    """
    Show all protocol violations from a trace file (V0.5 trace enhancement).

    Args:
        trace_path_or_id: Full path to trace .jsonl file (e.g., from CLI output)
        structure_code: STRUCTURE artifact (unused - kept for signature compatibility)
    """
    trace_path = Path(trace_path_or_id)

    # If given just ID (starts with T_), cannot resolve without domain
    if not trace_path.exists() and trace_path_or_id.startswith("T_"):
        print(f"❌ Trace ID alone insufficient. Provide full path to .jsonl file.", file=sys.stderr)
        print(f"   Example: pgs_domains/domains/DOMAIN/testbed/outputs/traces/T_.../T_....jsonl", file=sys.stderr)
        sys.exit(1)

    if not trace_path.exists():
        print(f"❌ Trace file not found: {trace_path}", file=sys.stderr)
        sys.exit(1)

    # Load trace and filter for VIOLATION events
    violations = []
    with trace_path.open() as f:
        for line in f:
            if line.strip():
                event = json.loads(line)
                # Check if this is a VIOLATION event
                if event.get("event_type") == "violation":
                    # Extract payload which contains violation details
                    payload = event.get("payload", {})
                    if payload.get("node_id"):
                        violations.append({
                            "timestamp": event.get("timestamp"),
                            "node_id": payload.get("node_id"),
                            "violation_code": payload.get("violation_code"),
                            "message": payload.get("message"),
                            "field": payload.get("field"),
                            "constraint": payload.get("constraint"),
                            "actual_value": payload.get("actual_value"),
                            "expected_value": payload.get("expected_value"),
                        })

    if not violations:
        print("✅ No protocol violations")
        return

    print(f"\n⚠️  {len(violations)} PROTOCOL VIOLATION(S):\n")
    for v in violations:
        print(f"[{v['timestamp']}]")
        print(f"Node: {v['node_id']}")
        print(f"Code: {v['violation_code']}")
        if v.get('field'):
            print(f"Field: {v['field']}")
        if v.get('constraint'):
            print(f"Constraint: {v['constraint']}")
        print(f"Message: {v['message']}")
        if v.get('actual_value') is not None:
            print(f"Actual value: {v['actual_value']}")
        if v.get('expected_value') is not None:
            print(f"Expected value: {v['expected_value']}")
        print("-" * 80)
        print()


def visualize_workflow(workflow_code: str, trace_id: str = None, output_dir: Path = None):
    """
    Generate visualization for a single workflow.

    Uses STRUCTURE artifact for path resolution (no module mapping).
    """
    print(f"[viz] Loading {workflow_code}...")
    dag, spec, structure_artifact, domain = load_workflow_dag(workflow_code)

    trace_events = None
    if trace_id:
        # Get trace path from STRUCTURE (sovereignty enforced)
        from pgs_governance.structure.structure.resolution.path_registry import paths

        # Try top-level first (canonical), then frontmatter (compiled artifacts)
        output_config = structure_artifact.get('output_configuration')
        if not output_config:
            output_config = structure_artifact.get('frontmatter', {}).get('output_configuration', {})

        trace_config = output_config.get('trace_output_path')
        if not trace_config:
            raise ValueError(f"STRUCTURE missing output_configuration.trace_output_path (needed for trace visualization)")

        # Use canonical resolution (same as workflow_gateway and CLI)
        # Pass domain for domain-scoped path resolution
        trace_base_dir = paths.resolve_output_path('trace_output_path', structure_artifact, domain=domain)
        trace_dir = trace_base_dir / trace_id
        trace_path = trace_dir / f"{trace_id}.jsonl"

        print(f"[viz] Loading trace {trace_id}...")
        trace_events = load_trace(trace_path)
        print(f"[viz] Loaded {len(trace_events)} events")

    dot_content = workflow_to_dot(dag, trace_events)

    # Determine output path
    if trace_id and not output_dir:
        # Trace visualization goes with trace output (from STRUCTURE)
        png_path = trace_dir / f"{trace_id}.png"
    else:
        # Static workflow visualization goes to authoring (via STRUCTURE)
        if not output_dir:
            from pgs_governance.structure.structure.loading.protocol_loader import load_bootstrap_artifact
            structure = load_bootstrap_artifact("fb.constitution::STRUCTURE_BUILD_PLATFORM_CONFIG_V0")
            output_dir = paths.resolve_output_path("visualization_artifacts_path", structure)
        output_dir.mkdir(parents=True, exist_ok=True)
        png_path = output_dir / f"{workflow_code}.png"

    try:
        dot_string_to_png(dot_content, png_path)
        print(f"[viz] PNG: {png_path}")

        # Also generate Markdown view when trace_id provided (V0.6 trace enhancement)
        if trace_id:
            render_markdown(str(trace_path))
    except RuntimeError as e:
        print(f"[viz] PNG failed: {e}", file=sys.stderr)


def visualize_workflow_with_trace_to_path(workflow_code: str, trace_id: str, png_path: Path):
    """
    Generate workflow visualization with trace overlay to specific path (for CLI).

    Uses STRUCTURE artifact for path resolution (no module mapping).
    """
    dag, _, structure_artifact, domain = load_workflow_dag(workflow_code)

    # Get trace path from STRUCTURE (sovereignty enforced)
    # Use resolve_output_path() for coordinate normalization
    from pgs_governance.structure.structure.resolution.path_registry import paths

    # Try top-level first (canonical), then frontmatter (compiled artifacts)
    output_config = structure_artifact.get('output_configuration')
    if not output_config:
        output_config = structure_artifact.get('frontmatter', {}).get('output_configuration', {})

    trace_config = output_config.get('trace_output_path')
    if not trace_config:
        raise ValueError(f"STRUCTURE missing output_configuration.trace_output_path")

    # Resolve via paths.resolve_output_path() to handle coordinate normalization
    trace_base_dir = paths.resolve_output_path('trace_output_path', output_config=structure_artifact.get('output_configuration', {}), domain=domain)
    trace_dir = trace_base_dir / trace_id
    trace_path = trace_dir / f"{trace_id}.jsonl"

    trace_events = load_trace(trace_path)

    dot_content = workflow_to_dot(dag, trace_events)
    dot_string_to_png(dot_content, png_path)


def load_segments() -> list[dict]:
    """Load process segment definitions from registry registry."""
    registry_path = paths.governance.registry_blockchain() / "process_segments_v0.md"

    if not registry_path.exists():
        print(f"[viz] Registry not found: {registry_path}", file=sys.stderr)
        sys.exit(1)

    md_text = registry_path.read_text(encoding="utf-8")

    from pgs_compiler.tooling.builder.structure_tree import parse_machine_block
    machine_block = parse_machine_block(md_text)
    segments = machine_block.get("segments", [])

    if not segments:
        print("[viz] No segments defined in registry", file=sys.stderr)
        sys.exit(1)

    return segments


def visualize_segment(segment: dict, output_dir: Path) -> bool:
    """Generate visualization for a single segment."""
    segment_id = segment["segment_id"]
    display_name = segment.get("display_name", segment_id)
    workflows = segment.get("workflows", [])

    if not workflows:
        print(f"[viz] Skipping {display_name}: no workflows defined")
        return False

    print(f"[viz] Generating segment: {display_name}")
    print(f"[viz]   Workflows: {', '.join(workflows)}")

    dags = {}
    for wf_code in workflows:
        dag, spec, _, _ = load_workflow_dag(wf_code)
        dags[wf_code] = {
            "dag": dag,
            "workflow_spec": spec["workflow_spec"],
        }

    dot_content = segment_to_dot(
        segment_id=segment_id,
        display_name=display_name,
        dags=dags,
        color=segment.get("color", "#4A90E2"),
        layout=segment.get("layout", "horizontal"),
    )

    png_path = output_dir / f"{segment_id}.png"

    try:
        dot_string_to_png(dot_content, png_path)
        print(f"[viz]   PNG: {png_path}")
    except RuntimeError as e:
        print(f"[viz]   PNG failed: {e}", file=sys.stderr)

    return True


def main():
    parser = argparse.ArgumentParser(description="Workflow visualization tool")
    parser.add_argument("--workflow", help="Workflow code (e.g., WF_CREATE_WALLET_V0)")
    parser.add_argument("--trace", help="Trace ID to overlay execution path or show errors from")
    parser.add_argument("--errors", action="store_true", help="Show errors from trace (requires --trace)")
    parser.add_argument("--violations", action="store_true", help="Show protocol violations from trace (requires --trace)")
    parser.add_argument("--format", choices=["md"], help="Output format: md=Markdown (requires --trace)")
    parser.add_argument("--segments", action="store_true", help="Generate all segment visualizations")
    parser.add_argument("--segment", help="Generate specific segment visualization")
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    args = parser.parse_args()

    if args.errors:
        if not args.trace:
            print("❌ --errors requires --trace <trace_id>", file=sys.stderr)
            sys.exit(1)
        show_errors(args.trace)

    elif args.violations:
        if not args.trace:
            print("❌ --violations requires --trace <trace_id>", file=sys.stderr)
            sys.exit(1)
        show_violations(args.trace)

    elif args.format:
        if not args.trace:
            print("❌ --format requires --trace <trace_path>", file=sys.stderr)
            sys.exit(1)
        if args.format == "md":
            render_markdown(args.trace)
        else:
            print(f"❌ Unsupported format: {args.format}", file=sys.stderr)
            sys.exit(1)

    elif args.workflow:
        visualize_workflow(args.workflow, args.trace, args.output_dir)

    elif args.segments or args.segment:
        if not args.output_dir:
            from pgs_governance.structure.structure.loading.protocol_loader import load_bootstrap_artifact
            structure = load_bootstrap_artifact("fb.constitution::STRUCTURE_BUILD_PLATFORM_CONFIG_V0")
            output_dir = paths.resolve_output_path("testbed_results_path", structure)
        else:
            output_dir = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        segments = load_segments()

        if args.segment:
            segments = [s for s in segments if s["segment_id"] == args.segment]
            if not segments:
                print(f"[viz] Segment not found: {args.segment}", file=sys.stderr)
                sys.exit(1)

        generated = sum(1 for s in segments if visualize_segment(s, output_dir))
        print(f"[viz] Generated {generated} segment(s)")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
