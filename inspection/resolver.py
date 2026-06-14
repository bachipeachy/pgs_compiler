"""
Resolver — FQDN → artifact index entry.

All resolution is lookup against the materialized artifact index. A full
FQDN is required in one-shot mode (scope-relative bare codes belong to the
interactive shell's declared `use` scope). A bare code is a hard error that
names the candidate FQDNs — resolution help, never a guess.
"""

from typing import Any

from pgs_compiler.inspection.errors import AmbiguousCode, UnresolvedFqdn
from pgs_compiler.inspection.loader import Workspace


class Resolver:
    """Lookup surface over the artifact index."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._artifacts: dict[str, dict[str, Any]] = workspace.artifact_index["artifacts"]

    def resolve(self, ref: str) -> tuple[str, dict[str, Any]]:
        """
        Resolve an artifact reference to (fqdn, index entry).

        Raises:
            AmbiguousCode: ref is a bare code — candidates are listed.
            UnresolvedFqdn: ref is unknown to the index.
        """
        if "::" not in ref:
            candidates = sorted(
                fqdn for fqdn in self._artifacts
                if fqdn.split("::", 1)[1] == ref
            )
            if candidates:
                raise AmbiguousCode(ref, candidates)
            raise UnresolvedFqdn(
                f"'{ref}' is not a known artifact code — full FQDN required "
                f"(<domain>::<ARTIFACT_CODE_Vn>)"
            )

        entry = self._artifacts.get(ref)
        if entry is None:
            raise UnresolvedFqdn(f"FQDN not in artifact index: {ref}")
        return ref, entry

    def list(
        self,
        kind: str | None = None,
        domain: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        """All index entries, optionally filtered by kind and/or domain. Sorted."""
        results = []
        for fqdn in sorted(self._artifacts):
            entry = self._artifacts[fqdn]
            if kind is not None and entry["kind"] != kind:
                continue
            if domain is not None and entry["domain"] != domain:
                continue
            results.append((fqdn, entry))
        return results
