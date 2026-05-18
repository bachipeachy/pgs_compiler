"""
STRUCTURE artifact loader for compiler.

Bootstrap mechanism for loading STRUCTURE artifacts without PGS dependencies.

Design:
- No imports from pgs_governance, pgs_structure, etc.
- Direct filesystem reads
- YAML parsing only
- Fail hard on missing artifacts
- FORBIDDEN_STRUCTURE guard to prevent legacy drift
"""

import re
import yaml
from pathlib import Path
from typing import Any


# BOOTSTRAP: Minimal hardcoded anchor — governance package location only.
# All federation boundary structures/ directories are derived from it.
def get_bootstrap_search_roots() -> list[Path]:
    """
    Return bootstrap search roots for STRUCTURE artifacts.

    CONSTITUTIONAL: The only hardcoded element is pgs_governance package location.
    All FB_*/structures/ paths are derived from registry/ under that package.
    Used to load STRUCTURE_DISCOVERY_V0, STRUCTURE_IDENTITY_V0, and any build config.
    After bootstrap, all paths come from STRUCTURE.

    Resolves relative to the installed pgs_governance package location,
    not cwd — so the compiler works from any directory.
    """
    import pgs_governance
    governance_pkg = Path(pgs_governance.__file__).parent
    registry = governance_pkg / "registry"
    return sorted(
        fb_dir / "structures"
        for fb_dir in registry.iterdir()
        if fb_dir.is_dir() and fb_dir.name.startswith("FB_") and (fb_dir / "structures").exists()
    )


# CRITICAL: Prevent usage of fragmented/deprecated STRUCTURE artifacts
# Use STRUCTURE_DISCOVERY_V0 and STRUCTURE_IDENTITY_V0 instead.
FORBIDDEN_STRUCTURE = {
    "STRUCTURE_REGISTRY_LOCATION_GOVERNANCE_V0",
    "STRUCTURE_REGISTRY_LOCATION_DOMAINS_V0",
    "STRUCTURE_REGISTRY_LOCATION_REUSABLE_TRANSFORMS_V0",
    "STRUCTURE_REGISTRY_LOCATION_REUSABLE_SIDE_EFFECTS_V0",
    "STRUCTURE_FQDN_TREE_V0",
    "STRUCTURE_ARTIFACT_IDENTITY_V0",
}


def extract_yaml_from_machine_section(content: str) -> str:
    """
    Extract YAML from ## Machine section.

    CONSTITUTIONAL: Machine block is the ONLY format. No fallback to frontmatter.
    """
    machine_pattern = re.compile(
        r"##\s+Machine\s*\n+```yaml\s*\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE
    )
    match = machine_pattern.search(content)

    if not match:
        raise ValueError(
            "No ## Machine section found.\n"
            "Expected format:\n"
            "## Machine\n"
            "```yaml\n"
            "...\n"
            "```"
        )

    return match.group(1)


def load_structure_artifact(artifact_code: str, search_roots: list[Path] = None) -> dict[str, Any]:
    """
    Load STRUCTURE artifact from filesystem with HARD FAIL GUARD for legacy artifacts.

    CONSTITUTIONAL: search_roots MUST be provided explicitly. No fallback defaults.
    """
    # GUARD: Block access to deprecated/fragmented artifacts
    if artifact_code in FORBIDDEN_STRUCTURE:
        raise RuntimeError(
            f"PROTOCOL VIOLATION: Access to legacy STRUCTURE artifact '{artifact_code}' is forbidden.\n"
            f"Please use consolidated STRUCTURE_DISCOVERY_V0 or STRUCTURE_IDENTITY_V0 instead."
        )

    # CONSTITUTIONAL: Fail hard if search_roots not provided
    if search_roots is None:
        raise RuntimeError(
            f"CONSTITUTIONAL VIOLATION: load_structure_artifact() requires explicit search_roots.\n"
            f"No fallback defaults allowed. Artifact: {artifact_code}"
        )

    # Search for artifact file
    artifact_path = None
    for root in search_roots:
        candidate = root / f"{artifact_code}.md"
        if candidate.exists():
            artifact_path = candidate
            break

    if artifact_path is None:
        raise FileNotFoundError(
            f"STRUCTURE artifact not found: {artifact_code}\n"
            f"Searched: {[str(r) for r in search_roots]}"
        )

    # Read and parse
    content = artifact_path.read_text(encoding="utf-8")
    yaml_content = extract_yaml_from_machine_section(content)
    parsed = yaml.safe_load(yaml_content)

    if not isinstance(parsed, dict):
        raise ValueError(f"STRUCTURE artifact must be YAML dict: {artifact_code}")

    return parsed
