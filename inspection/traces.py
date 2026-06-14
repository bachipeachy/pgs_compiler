"""
Trace surface — filesystem listing and trace-id resolution ONLY.

Traces are runtime output. *What happened* belongs to `pgs_runtime examine`;
pi never parses trace content. These helpers enumerate the trace tree
(traces/<domain>/<WF_CODE>/<TRACE_ID>/) and resolve a trace id to its
.jsonl path so the CLI can delegate via subprocess.
"""

from pathlib import Path
from typing import Any

from pgs_compiler.inspection.errors import ProjectionMissing


def list_traces(
    workspace_root: Path,
    domain: str | None = None,
    workflow: str | None = None,
) -> list[dict[str, Any]]:
    """Enumerate trace directories. Listing only — no content is read."""
    traces_root = workspace_root / "traces"
    if not traces_root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for domain_dir in sorted(d for d in traces_root.iterdir() if d.is_dir()):
        if domain is not None and domain_dir.name != domain:
            continue
        for wf_dir in sorted(d for d in domain_dir.iterdir() if d.is_dir()):
            if workflow is not None and wf_dir.name != workflow:
                continue
            for trace_dir in sorted(d for d in wf_dir.iterdir() if d.is_dir()):
                records.append({
                    "domain": domain_dir.name,
                    "workflow": wf_dir.name,
                    "trace_id": trace_dir.name,
                    "path": str(trace_dir.relative_to(workspace_root)),
                })
    return records


def resolve_trace_jsonl(workspace_root: Path, trace_id: str) -> Path:
    """Trace id → its .jsonl event log path. Hard error if absent."""
    matches = [
        workspace_root / r["path"] / f"{trace_id}.jsonl"
        for r in list_traces(workspace_root)
        if r["trace_id"] == trace_id
    ]
    if not matches:
        raise ProjectionMissing(
            f"trace '{trace_id}' not found under {workspace_root / 'traces'}"
        )
    jsonl = matches[0]
    if not jsonl.is_file():
        raise ProjectionMissing(f"trace event log missing: {jsonl}")
    return jsonl
