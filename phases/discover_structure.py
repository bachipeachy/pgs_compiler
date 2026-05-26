"""
STRUCTURE-driven discovery phase.

Discovers artifacts using STRUCTURE_DISCOVERY_V0 artifact configuration.

Design:
- Simplified registry definitions (one entry per layer)
- Recursive scanning for all sub-registries
- Filtering by build scope (artifact_types)
- DEPRECATED filtering (pre-cleaning)
- Minimal metadata capture (deferred namespace/FQDN computation)
"""

import re
from pathlib import Path
from typing import Any

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    PhaseResult,
    PhaseStatus,
    sort_artifacts_by_fqdn,
)
from pgs_compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots
from pgs_governance.implementation.structure.resolution.layer_resolver import LayerResolver



def discover_structure_phase(
    structure_artifact_code: str,
    structure_search_roots: list[Path] | None = None,
) -> PhaseResult:
    """
    Discover artifacts using consolidated STRUCTURE_DISCOVERY_V0 configuration.

    CONSTITUTIONAL: Uses bootstrap search roots if structure_search_roots not provided.
    """
    errors: list[CompilerError] = []
    all_discovered: list[dict[str, Any]] = []
    layer_category_map: dict[str, str] = {}
    is_domain_build: bool = False

    # Bootstrap: Use minimal hardcoded path if not provided
    if structure_search_roots is None:
        structure_search_roots = get_bootstrap_search_roots()

    # Step 1: Load STRUCTURE_DISCOVERY_V0 (Master discovery config)
    discovery_master = load_structure_artifact("STRUCTURE_DISCOVERY_V0", structure_search_roots)
    discovery_config = discovery_master.get("discovery", {})
    discovery_layers = discovery_config.get("layers", {})
    discovery_rules = discovery_config.get("rules", {})

    # Step 2: Load build-specific STRUCTURE
    build_config = load_structure_artifact(structure_artifact_code, structure_search_roots)
    artifact_discovery = build_config.get("artifact_discovery", {})
    search_layers = artifact_discovery.get("search_layers", [])
    build_artifact_types = artifact_discovery.get("artifact_types", [])

    if not search_layers:
        raise RuntimeError(
            f"STRUCTURE {structure_artifact_code} artifact_discovery.search_layers is empty"
        )

    # Step 2.5: Build layer_category_map from STRUCTURE_DISCOVERY_V0
    layer_category_map = {}
    for layer_code, layer_def in discovery_layers.items():
        layer_category_map[layer_code] = layer_def.get("layer_category", "platform")

    is_domain_build = any(
        layer_category_map.get(layer_code) == "domain"
        for layer_code in search_layers
    )

    # Step 3: Scan each layer using master discovery rules
    seen_paths: set[Path] = set()
    artifact_pattern = re.compile(discovery_rules.get("filename_pattern", ""))
    excluded_dirs = discovery_rules.get("excluded_directories", [])

    for layer_to_search in search_layers:
        registry_config = discovery_layers.get(layer_to_search)
        if not registry_config:
            errors.append(
                CompilerError(
                    code=ErrorCode.E901_INTERNAL_ERROR,
                    message=f"Layer {layer_to_search} not found in STRUCTURE_DISCOVERY_V0",
                    phase="DISCOVER",
                )
            )
            continue

        # DOMAINS layer requires per-domain iteration
        if layer_to_search == "DOMAINS":
            allowed_domains = registry_config.get("allowed_domains", [])

            # CONSTITUTIONAL CHECK: Fail hard if allowed_domains not declared
            if not allowed_domains:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E901_INTERNAL_ERROR,
                        message=f"STRUCTURE violation: DOMAINS layer missing allowed_domains declaration",
                        phase="DISCOVER",
                    )
                )
                continue

            # Iterate over STRUCTURE-declared domains (NO filesystem scanning)
            for domain_name in allowed_domains:
                _scan_layer_registry(
                    layer_to_search,
                    registry_config,
                    artifact_pattern,
                    excluded_dirs,
                    all_discovered,
                    seen_paths,
                    errors,
                    domain_name=domain_name  # Pass domain context
                )
        else:
            # Platform layer discovery (existing code)
            _scan_layer_registry(
                layer_to_search,
                registry_config,
                artifact_pattern,
                excluded_dirs,
                all_discovered,
                seen_paths,
                errors,
                domain_name=None  # Platform-only discovery
            )

    # Step 4: Apply scope filter
    artifacts = []
    skipped = []
    for a in all_discovered:
        # Must be in build config artifact_types
        if a["artifact_type"] not in build_artifact_types:
            skipped.append({**a, "reason": f"Type '{a['artifact_type']}' not in build scope"})
            continue

        artifacts.append(a)

    # Sort artifacts by artifact_code + source_path (deterministic ordering)
    artifacts_sorted = sorted(artifacts, key=lambda x: (x["artifact_code"], x["source_path"]))
    skipped_sorted = sorted(skipped, key=lambda x: (x["artifact_code"], x["source_path"]))

    # Check if any artifacts found
    if not artifacts and not errors:
        errors.append(
            CompilerError(
                code=ErrorCode.E001_NO_ARTIFACTS,
                message="No artifacts found in build scope",
                phase="DISCOVER",
            )
        )

    # Build result
    if errors:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={
                "discovered_artifacts": artifacts_sorted,
                "skipped_artifacts": skipped_sorted,
                "layer_category_map": layer_category_map,
                "is_domain_build": is_domain_build
            },
            errors=tuple(errors),
        )
    else:
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={
                "discovered_artifacts": artifacts_sorted,
                "skipped_artifacts": skipped_sorted,
                "layer_category_map": layer_category_map,
                "is_domain_build": is_domain_build
            },
            errors=tuple(),
        )


def _scan_layer_registry(
    layer_id: str,
    registry_config: dict[str, Any],
    artifact_pattern: re.Pattern,
    excluded_dirs: list[str],
    artifacts: list[dict[str, Any]],
    seen_paths: set[Path],
    errors: list[CompilerError],
    domain_name: str | None = None,
) -> None:
    """Scan a layer's registry module recursively."""
    registry_module = registry_config.get("registry_module")

    # Use LayerResolver to get the physical path for this layer
    # This supports both local layers and peer repo layers via STRUCTURE
    resolver = LayerResolver()

    # Resolve layer root from STRUCTURE_LAYER_AUTHORITY_V0
    # LayerResolver returns the full path to the registry module
    # (physical_location.target + module_root), so we use it directly
    if layer_id == "DOMAINS" and domain_name:
        root_path = resolver.resolve_layer_root(layer_id, domain=domain_name)
    else:
        root_path = resolver.resolve_layer_root(layer_id)

    # FAIL HARD if path doesn't exist (no defensive coding)
    if not root_path.exists():
        raise CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=f"Layer {layer_id} registry path does not exist: {root_path}",
            phase="DISCOVER",
            context={
                "layer": layer_id,
                "expected_path": str(root_path),
                "fix": "Check STRUCTURE_LAYER_AUTHORITY_V0 physical_location configuration"
            }
        )

    # Recursive scan for artifacts
    for md_path in root_path.rglob("*.md"):
        # De-duplication check
        if md_path.resolve() in seen_paths:
            continue
        seen_paths.add(md_path.resolve())

        # Skip excluded directories
        if any(excl in md_path.parts for excl in excluded_dirs):
            continue

        match = artifact_pattern.match(md_path.name)
        if not match:
            continue

        artifact_type = match.group("type")
        artifact_name = match.group("name")
        version = match.group("version")

        artifact_code = f"{artifact_type}_{artifact_name}_V{version}"

        # Identify relative module path for namespace derivation in next phase
        rel_path = md_path.parent.relative_to(root_path)
        if str(rel_path) == ".":
            full_module_path = registry_module
        else:
            full_module_path = f"{registry_module}.{str(rel_path).replace('/', '.')}"

        artifact_metadata = {
            "artifact_code": artifact_code,
            "artifact_type": artifact_type,
            "layer_code": layer_id,
            "module_path": full_module_path,
            "source_path": str(md_path),
            "version": version,
            "namespace": "TBD",  # Deferred to PARSE phase
            "fqdn_id": f"TBD::{artifact_code}"  # Deferred to PARSE phase
        }

        # Capture domain context for DOMAINS layer
        if domain_name:
            artifact_metadata["domain_name"] = domain_name

        artifacts.append(artifact_metadata)
