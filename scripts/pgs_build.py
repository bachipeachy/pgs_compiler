#!/usr/bin/env python3
"""
pgs build — Snapshot build orchestration entry point.

Pipeline:
  1. sync_protocol_snapshot.sh   (file movement — unchanged)
  2. conformance/runner.py       (correctness — all CT conformance cases)
  3. snapshot_attestation.json   (trust boundary — root hash of per-structure attestations)
  4. snapshot_status.json        (verification contract — written only on full pass)

Usage:
  python pgs_compiler/scripts/pgs_build.py --workspace /abs/path/to/pgs_workspace

Hard gates:
  - Sync script failure → exit 1, no status written
  - Any conformance failure → exit 1, no status written
  - snapshot_status.json is only written when ALL cases pass
  - Missing attestations → warning only (not a hard gate in v0.3.0)
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
    from pgs_runtime.conformance import run as run_conformance
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


def step_attest_snapshot(workspace: Path) -> str | None:
    """
    Aggregate per-structure attestations into a root snapshot_attestation.json.

    Scans trust_snapshot/ for structure_attestation.json files, collects their
    attestation_hash values, computes root_hash = SHA256(sorted hashes), and
    writes trust_snapshot/snapshot_attestation.json.

    Returns root_hash on success, None if no attestations found (warning only).
    """
    import hashlib
    from datetime import datetime, timezone

    print("[pgs build] ── Step 3: snapshot attestation ────────────────────────")

    trust_root = workspace / "trust_snapshot"
    if not trust_root.exists():
        print("[pgs build] WARNING: trust_snapshot/ not found — skipping attestation")
        return None

    attestation_files = sorted(trust_root.rglob("structure_attestation.json"))
    if not attestation_files:
        print("[pgs build] WARNING: no structure_attestation.json files found — skipping attestation")
        return None

    structure_hashes: list[str] = []
    structure_ids: list[str] = []
    has_stub = False

    for att_file in attestation_files:
        try:
            with open(att_file, "r", encoding="utf-8") as f:
                att = json.load(f)
            h = att.get("attestation_hash", "")
            structure_ids.append(att.get("structure_id", str(att_file)))
            if h:
                structure_hashes.append(h)
            if att.get("signing_algorithm") == "STUB":
                has_stub = True
        except Exception as e:
            print(f"[pgs build] WARNING: failed to read {att_file}: {e}")

    if not structure_hashes:
        print("[pgs build] WARNING: no attestation hashes found — skipping snapshot attestation")
        return None

    # Root hash: SHA256 of sorted per-structure attestation hashes (deterministic)
    root_hash = hashlib.sha256(
        b"".join(h.encode("utf-8") for h in sorted(structure_hashes))
    ).hexdigest()

    snapshot_attestation = {
        "snapshot_attestation_version": "V0",
        "root_hash": root_hash,
        "structure_count": len(structure_hashes),
        "structure_ids": sorted(structure_ids),
        "signing_algorithm": "STUB",
        "signature": "STUB_NOT_CRYPTOGRAPHICALLY_SIGNED",
        "public_key_ref": "STUB",
        "attested_at": datetime.now(timezone.utc).isoformat(),
    }

    output_path = trust_root / "snapshot_attestation.json"
    output_path.write_text(json.dumps(snapshot_attestation, indent=2, sort_keys=True) + "\n")

    if has_stub:
        print(f"[pgs build] WARNING: signing_algorithm is STUB — stub attestation only")
    print(f"[pgs build] snapshot_attestation.json written → {output_path}")
    print(f"[pgs build]   structures: {len(structure_hashes)}, root_hash: {root_hash[:16]}...")

    return root_hash


def step_mark_valid(workspace: Path, result) -> None:
    print("[pgs build] ── Step 4: mark snapshot valid ───────────────────────")
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


def step_invalidate_snapshot(workspace: Path) -> None:
    """
    Immediately mark the snapshot INVALID at build start.

    Written before any sync or validation work begins so that if this build
    run fails at any point (sync failure, conformance failure, etc.), the
    snapshot_status.json reflects the failure rather than the previous run's
    result. step_mark_valid overwrites this only on full pass.
    """
    status = {
        "status": "INVALID",
        "reason": "Build in progress or failed — do not consume this snapshot",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    status_file = workspace / "snapshot_status.json"
    status_file.write_text(json.dumps(status, indent=2) + "\n")


def main() -> None:
    args = parse_args()

    workspace = Path(args.workspace)
    if not workspace.is_absolute():
        sys.exit(f"[pgs build] ERROR: --workspace must be an absolute path, got: {args.workspace}")
    if not workspace.exists():
        sys.exit(f"[pgs build] ERROR: workspace not found: {workspace}")

    # Invalidate snapshot before any work — any failure leaves it INVALID.
    # step_mark_valid overwrites this only after all gates pass.
    step_invalidate_snapshot(workspace)

    step_sync(workspace)

    result = step_conformance(workspace)

    if not result.all_passed:
        print(
            f"\n[pgs build] BUILD FAILED — {result.failed} conformance test(s) failed.\n"
            f"            Snapshot is NOT marked valid. Fix the failing CT(s) and rebuild."
        )
        sys.exit(1)

    step_attest_snapshot(workspace)

    step_mark_valid(workspace, result)

    print("\n[pgs build] ✓ Build complete. Snapshot is VALID.\n")


if __name__ == "__main__":
    main()
