"""
Evidence reader — loads evidence_graph.json and returns an EvidenceQuery.

ISOLATION INVARIANT: This module MUST NOT import from compiler internals.
The evidence_graph.json schema is the only contract.

Public API:
    load_evidence_graph(path) -> EvidenceQuery
        Load and deserialize evidence_graph.json from the given path.
        Raises FileNotFoundError if the file is missing.
        Raises ValueError if the file is not valid JSON or fails schema checks.
"""

import json
from pathlib import Path

from .evidence_query import EvidenceQuery

_REQUIRED_TOP_LEVEL_KEYS = frozenset({
    "structure_id",
    "compiler_version",
    "evidence_graph_hash",
    "event_count",
    "edge_count",
    "events",
    "edges",
    "families",
})

_REQUIRED_EVENT_KEYS = frozenset({
    "event_id",
    "stage",
    "operation",
    "family",
    "subject_fqdn",
    "subject_token",
    "parent_event_id",
})

_REQUIRED_EDGE_KEYS = frozenset({
    "source_event_id",
    "target_event_id",
    "kind",
})


def load_evidence_graph(path: Path | str) -> EvidenceQuery:
    """
    Load evidence_graph.json from path and return a ready EvidenceQuery.

    Args:
        path: Path to evidence_graph.json (string or Path object).

    Returns:
        EvidenceQuery over the deserialized graph.

    Raises:
        FileNotFoundError: File does not exist at path.
        ValueError: File content is invalid JSON or fails structural validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"evidence_graph.json not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"evidence_graph.json is not valid JSON: {path}\n{exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"evidence_graph.json root must be a JSON object: {path}")

    _validate_structure(raw, path)
    return EvidenceQuery(raw)


# --- Internal validation ---

def _validate_structure(raw: dict, path: Path) -> None:
    """Lightweight structural validation — required keys and array types only."""
    missing = _REQUIRED_TOP_LEVEL_KEYS - raw.keys()
    if missing:
        raise ValueError(
            f"evidence_graph.json missing required keys {sorted(missing)}: {path}"
        )

    if not isinstance(raw["events"], list):
        raise ValueError(f"evidence_graph.json 'events' must be an array: {path}")
    if not isinstance(raw["edges"], list):
        raise ValueError(f"evidence_graph.json 'edges' must be an array: {path}")
    if not isinstance(raw["families"], dict):
        raise ValueError(f"evidence_graph.json 'families' must be an object: {path}")

    for i, event in enumerate(raw["events"]):
        if not isinstance(event, dict):
            raise ValueError(
                f"evidence_graph.json events[{i}] must be an object: {path}"
            )
        missing_ev = _REQUIRED_EVENT_KEYS - event.keys()
        if missing_ev:
            raise ValueError(
                f"evidence_graph.json events[{i}] missing keys "
                f"{sorted(missing_ev)}: {path}"
            )

    for i, edge in enumerate(raw["edges"]):
        if not isinstance(edge, dict):
            raise ValueError(
                f"evidence_graph.json edges[{i}] must be an object: {path}"
            )
        missing_ed = _REQUIRED_EDGE_KEYS - edge.keys()
        if missing_ed:
            raise ValueError(
                f"evidence_graph.json edges[{i}] missing keys "
                f"{sorted(missing_ed)}: {path}"
            )
