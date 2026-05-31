"""
Snapshot admission control gate.

All CLI subcommands that consume a compiled workspace snapshot
MUST call assert_snapshot_valid() before reading from it.

The admissibility chain:
  Invalid Protocol → No Snapshot → Invalid Snapshot → No Build → Invalid Build → No PPS
"""

import json
import sys
from pathlib import Path


def assert_snapshot_valid(workspace: Path) -> None:
    """
    Hard gate: workspace snapshot must be VALID before any consumer subcommand proceeds.

    Reads snapshot_status.json from the workspace root. Exits 1 with a diagnostic
    message if the file is missing, unreadable, or reports a non-VALID status.

    Args:
        workspace: Absolute path to pgs_workspace root.

    Raises:
        SystemExit(1): If snapshot is absent or not VALID.
    """
    snapshot_status_file = workspace / "snapshot_status.json"

    if not snapshot_status_file.exists():
        print(
            "ERROR: snapshot_status.json not found — snapshot has not been built.\n"
            "       Run 'pgs_compiler build --workspace <path>' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        snapshot_status = json.loads(snapshot_status_file.read_text())
    except Exception as exc:
        print(f"ERROR: Failed to read snapshot_status.json: {exc}", file=sys.stderr)
        sys.exit(1)

    if snapshot_status.get("status") != "VALID":
        print(
            f"ERROR: Snapshot is not VALID (status: {snapshot_status.get('status', 'UNKNOWN')}).\n"
            "       Fix all compile errors and rebuild the snapshot before proceeding.",
            file=sys.stderr,
        )
        sys.exit(1)
