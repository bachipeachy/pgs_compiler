"""
Deterministic sorting utilities.

Design:
- Sort by FQDN (primary identity)
- Stable ordering (same input → same order)
- No implicit ordering (dict iteration, set ordering)
- Explicit sort at phase boundaries
"""

from typing import Any, Callable, TypeVar

T = TypeVar("T")


def sort_artifacts_by_fqdn(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Sort artifacts by FQDN (deterministic ordering).

    CRITICAL: Use this at phase boundaries to prevent nondeterminism.

    Args:
        artifacts: List of artifact dicts (must have "fqdn_id" field)

    Returns:
        Sorted list (by fqdn_id lexicographic order)

    Examples:
        >>> artifacts = [
        ...     {"fqdn_id": "pkg_b::CT_FOO_V0", ...},
        ...     {"fqdn_id": "pkg_a::CT_BAR_V0", ...},
        ... ]
        >>> sorted_artifacts = sort_artifacts_by_fqdn(artifacts)
        >>> [a["fqdn_id"] for a in sorted_artifacts]
        ['pkg_a::CT_BAR_V0', 'pkg_b::CT_FOO_V0']
    """
    return sorted(artifacts, key=lambda a: a["fqdn_id"])


def sort_by_fqdn(items: list[T], key_func: Callable[[T], str]) -> list[T]:
    """
    Sort generic items by FQDN key (deterministic ordering).

    More flexible version - works with any type.

    Args:
        items: List of items to sort
        key_func: Function to extract FQDN string from item

    Returns:
        Sorted list (by FQDN lexicographic order)

    Examples:
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class Artifact:
        ...     fqdn: str
        ...     data: dict
        >>> artifacts = [
        ...     Artifact("pkg_b::CT_FOO_V0", {}),
        ...     Artifact("pkg_a::CT_BAR_V0", {}),
        ... ]
        >>> sorted_artifacts = sort_by_fqdn(artifacts, lambda a: a.fqdn)
        >>> [a.fqdn for a in sorted_artifacts]
        ['pkg_a::CT_BAR_V0', 'pkg_b::CT_FOO_V0']
    """
    return sorted(items, key=key_func)


def sort_dict_keys(d: dict[str, Any]) -> dict[str, Any]:
    """
    Sort dictionary by keys (deterministic ordering).

    Use for JSON output to ensure byte-identical outputs.

    Args:
        d: Dictionary to sort

    Returns:
        New dict with keys in lexicographic order

    Examples:
        >>> d = {"z": 1, "a": 2, "m": 3}
        >>> sorted_d = sort_dict_keys(d)
        >>> list(sorted_d.keys())
        ['a', 'm', 'z']
    """
    return dict(sorted(d.items()))


def ensure_deterministic_output(obj: Any) -> Any:
    """
    Recursively sort all collections for deterministic output.

    Use before JSON serialization to guarantee byte-identical outputs.

    Args:
        obj: Object to make deterministic (dict, list, primitive)

    Returns:
        Deterministic version (sorted dicts, sorted lists where applicable)

    Examples:
        >>> obj = {
        ...     "artifacts": [
        ...         {"fqdn_id": "b::CT", "name": "foo"},
        ...         {"fqdn_id": "a::CT", "name": "bar"},
        ...     ],
        ...     "z_field": "last",
        ...     "a_field": "first",
        ... }
        >>> deterministic = ensure_deterministic_output(obj)
        >>> list(deterministic.keys())
        ['a_field', 'artifacts', 'z_field']
    """
    if isinstance(obj, dict):
        # Sort dict keys and recursively process values
        return {k: ensure_deterministic_output(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        # Recursively process list items
        # Don't sort lists (order may be meaningful)
        return [ensure_deterministic_output(item) for item in obj]
    else:
        # Primitives (str, int, bool, None) pass through
        return obj
