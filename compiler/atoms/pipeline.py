"""
pipeline.py — Compiler pipeline metadata management.

Defines which fields are transient compiler-operational state and must never
cross the materialization boundary into compiled artifacts or snapshots.

Design principle:
  Compiled artifacts must contain ONLY governable semantic state.
  They must never contain:
    - local filesystem state  (source_path, loader_origin)
    - compiler operational state  (parse_cache, temp_resolution)
    - author workstation state  (filesystem hints, debug fields)
    - build-environment leakage  (absolute paths, host identifiers)

  Transient fields serve the build pipeline internally (e.g., discover → parse)
  and are stripped at the materialization boundary — the formal threshold between
  compiler-operational state and protocol-semantic state.

  As new pipeline-internal fields are introduced, register them here.
  Never use ad hoc .pop() at call sites.
"""

# Fields that are compiler-internal pipeline metadata.
# Present on artifact dicts during build; must not appear in materialized output.
_TRANSIENT_PIPELINE_FIELDS: frozenset[str] = frozenset(
    {
        "source_path",      # Absolute filesystem path set by discover; used by parse to load content
        # Future candidates (register here as needed):
        # "parse_cache",
        # "loader_origin",
        # "compiler_debug",
        # "temp_resolution",
        # "filesystem_hint",
    }
)


def strip_transient_pipeline_fields(artifact: dict) -> dict:
    """
    Return a copy of artifact with all transient compiler pipeline fields removed.

    Call this once, immediately before serializing an artifact to disk.
    The returned dict is a shallow copy — nested structures are not copied.

    Args:
        artifact: Artifact dict as it exists in the compiler pipeline.

    Returns:
        New dict with transient fields stripped. Original is not mutated.
    """
    return {k: v for k, v in artifact.items() if k not in _TRANSIENT_PIPELINE_FIELDS}
