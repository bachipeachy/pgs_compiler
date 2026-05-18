#!/usr/bin/env python3
"""
pgs build — Snapshot build orchestration entry point.

Pipeline:
  1. sync_protocol_snapshot.sh   (file movement — unchanged)
  2. conformance/runner.py       (correctness — all CT conformance cases)
  3. snapshot_status.json        (verification contract — written only on full pass)

Usage:
  python pgs_compiler/scripts/pgs_build.py --workspace /abs/path/to/pgs_workspace

Hard gates:
  - Sync script failure → exit 1, no status written
  - Any conformance failure → exit 1, no status written
  - snapshot_status.json is only written when ALL cases pass
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Sync script lives in the same directory as this file.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_SYNC_SCRIPT = _SCRIPTS_DIR / "sync_protocol_snapshot.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PGS Build — sync snapshot + run conformance + mark valid"
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Absolute path to pgs_workspace root",
    )
    return parser.parse_args()


def step_sync(workspace: Path) -> None:
    if not _SYNC_SCRIPT.exists():
        sys.exit(f"[pgs build] ERROR: sync script not found: {_SYNC_SCRIPT}")
    print("[pgs build] ── Step 1: sync protocol snapshot ──────────────────")
    env = {**os.environ, "PGS_WORKSPACE": str(workspace), "PGS_INVOKED_BY_BUILD": "1"}
    result = subprocess.run(["bash", str(_SYNC_SCRIPT)], env=env)
    if result.returncode != 0:
        sys.exit(f"[pgs build] ERROR: sync_protocol_snapshot.sh failed (exit {result.returncode})")
    print("[pgs build] sync complete\n")


def step_conformance(workspace: Path):
    print("[pgs build] ── Step 2: CT conformance tests ─────────────────────")
    from omnibachi.implementation.conformance.runner import run as run_conformance
    snapshot_root = workspace / "protocol_snapshot"
    result = run_conformance(snapshot_root)

    total = result.artifact_count
    for case in result.cases:
        label = "PASS" if case.passed else "FAIL"
        print(f"  [{label}] {case.fqdn}")
        if case.error:
            for line in case.error.splitlines():
                print(f"         {line}")

    print(f"\n[pgs build] conformance: {result.passed}/{total} passed", end="")
    if result.failed:
        print(f"  ({result.failed} FAILED)")
    else:
        print()

    return result


def step_mark_valid(workspace: Path, result) -> None:
    print("[pgs build] ── Step 3: mark snapshot valid ───────────────────────")
    status = {
        "status": "VALID",
        "conformance_passed": True,
        "artifact_count": result.artifact_count,
        "passed": result.passed,
        "failed": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "snapshot_hash": result.snapshot_hash,
    }
    status_file = workspace / "snapshot_status.json"
    status_file.write_text(json.dumps(status, indent=2) + "\n")
    print(f"[pgs build] snapshot_status.json written → {status_file}")


def main() -> None:
    args = parse_args()

    workspace = Path(args.workspace)
    if not workspace.is_absolute():
        sys.exit(f"[pgs build] ERROR: --workspace must be an absolute path, got: {args.workspace}")
    if not workspace.exists():
        sys.exit(f"[pgs build] ERROR: workspace not found: {workspace}")

    step_sync(workspace)

    result = step_conformance(workspace)

    if not result.all_passed:
        print(
            f"\n[pgs build] BUILD FAILED — {result.failed} conformance test(s) failed.\n"
            f"            Snapshot is NOT marked valid. Fix the failing CT(s) and rebuild."
        )
        sys.exit(1)

    step_mark_valid(workspace, result)

    print("\n[pgs build] ✓ Build complete. Snapshot is VALID.\n")


if __name__ == "__main__":
    main()
