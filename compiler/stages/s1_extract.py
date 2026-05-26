"""
S1 EXTRACT — Discovery + parsing → initial Graph population.

Input: State (initial, with structure_config)
Output: State with Graph populated with nodes (address=-1, ir=None)

Each discovered artifact becomes a Node. References become Edges
with kind=REFERENCES (typed in S2 CANONICALIZE).
"""

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from pgs_compiler.compiler.graph.types import NodeKind, EdgeKind
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.edge import Edge
from pgs_compiler.compiler.graph.graph import GraphBuilder
from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.compiler.atoms.error_codes import ErrorCode
from pgs_compiler.structure_loader import (
    load_structure_artifact,
    get_bootstrap_search_roots,
)

from pgs_governance.implementation.structure.resolution.layer_resolver import LayerResolver


# Machine block pattern: ## Machine\n```yaml\n{yaml}\n```
_MACHINE_BLOCK_PATTERN = re.compile(
    r"^## Machine\s*\n+```yaml\s*\n(?P<machine_yaml>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)

# Artifact type → NodeKind mapping
_TYPE_TO_KIND: dict[str, NodeKind] = {
    "WF": NodeKind.WF,
    "CC": NodeKind.CC,
    "CT": NodeKind.CT,
    "CS": NodeKind.CS,
    "RB": NodeKind.RB,
    "IN": NodeKind.IN,
    "EV": NodeKind.EV,
    "AC": NodeKind.AC,
    "TI": NodeKind.TI,
    "TE": NodeKind.TE,
    "ASSERT": NodeKind.ASSERT,
    "SCHEMA": NodeKind.GOVERNANCE,
    "TEST_DATA": NodeKind.TEST_DATA,
    "GOVERNANCE": NodeKind.GOVERNANCE,
    # Governance sub-types that map to GOVERNANCE node kind
    "CONSTITUTION": NodeKind.GOVERNANCE,
    "INVARIANT": NodeKind.GOVERNANCE,
    "LAYER": NodeKind.GOVERNANCE,
    "STRUCTURE": NodeKind.GOVERNANCE,
    "SURFACE": NodeKind.GOVERNANCE,
    "VOCAB": NodeKind.GOVERNANCE,
}


def s1_extract(state: State) -> State:
    """
    S1 EXTRACT: Discover artifacts and populate Graph with nodes.

    Pure function: State → State.

    Steps:
        1. Load STRUCTURE_DISCOVERY_V0 + build-specific STRUCTURE config
        2. Discover artifact files from declared layers
        3. Parse Machine YAML from each artifact
        4. Derive FQDNs from STRUCTURE_IDENTITY_V0 rules
        5. Create Nodes for each artifact
        6. Extract references and create REFERENCES edges

    Args:
        state: Initial State (from State.initial())

    Returns:
        New State with graph populated (nodes + reference edges)
    """
    state = state.with_stage("S1_EXTRACT")
    errors: list[CompilerError] = []
    warnings: list[CompilerError] = []
    trace: list[TraceEvent] = []

    structure_config = dict(state.structure_config)
    structure_artifact_code = structure_config.get("structure_artifact_code", "")

    if not structure_artifact_code:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message="structure_config missing 'structure_artifact_code'",
            phase="S1_EXTRACT",
        ))

    search_roots = get_bootstrap_search_roots()

    # --- Step 1: Load discovery and build configs ---
    try:
        discovery_master = load_structure_artifact("STRUCTURE_DISCOVERY_V0", search_roots)
        build_config = load_structure_artifact(structure_artifact_code, search_roots)
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=f"Failed to load STRUCTURE artifacts: {e}",
            phase="S1_EXTRACT",
        ))

    discovery_config = discovery_master.get("discovery", {})
    discovery_layers = discovery_config.get("layers", {})
    discovery_rules = discovery_config.get("rules", {})

    artifact_discovery = build_config.get("artifact_discovery", {})
    search_layers = artifact_discovery.get("search_layers", [])
    build_artifact_types = artifact_discovery.get("artifact_types", [])

    if not search_layers:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=f"STRUCTURE {structure_artifact_code} artifact_discovery.search_layers is empty",
            phase="S1_EXTRACT",
        ))

    # --- Step 2: Load identity rules ---
    try:
        identity_master = load_structure_artifact("STRUCTURE_IDENTITY_V0", search_roots)
        identity_rules = (
            identity_master.get("identity", {})
            .get("fqdn", {})
            .get("namespace", {})
            .get("derivation", {})
            .get("rules", [])
        )
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=f"Failed to load STRUCTURE_IDENTITY_V0: {e}",
            phase="S1_EXTRACT",
        ))

    # --- Step 3: Discover artifact files ---
    discovered = _discover_artifacts(
        search_layers, discovery_layers, discovery_rules,
        build_artifact_types, errors
    )

    if not discovered and not errors:
        errors.append(CompilerError(
            code=ErrorCode.E001_NO_ARTIFACTS,
            message="No artifacts found in build scope",
            phase="S1_EXTRACT",
        ))

    if errors:
        return state.with_errors(*errors)

    # --- Step 4: Derive FQDNs ---
    _derive_fqdns(discovered, identity_rules, errors)

    if errors:
        return state.with_errors(*errors)

    trace.append(TraceEvent.create(
        stage="S1_EXTRACT",
        operation="discovery_complete",
        detail={"artifacts_discovered": len(discovered)},
        family=EventFamily.DISCOVERY.value,
    ))

    # --- Step 5: Parse and build graph ---
    builder = GraphBuilder()

    # Build artifact registry for reference validation
    artifact_registry: dict[str, list[str]] = {}
    for artifact in discovered:
        code = artifact["artifact_code"]
        ns = artifact["namespace"]
        if code not in artifact_registry:
            artifact_registry[code] = []
        if ns not in artifact_registry[code]:
            artifact_registry[code].append(ns)

    for artifact in discovered:
        node, refs, parse_errors, parse_warnings = _parse_artifact_to_node(
            artifact, artifact_registry
        )
        errors.extend(parse_errors)
        warnings.extend(parse_warnings)

        if node is not None:
            builder.add_node(node)
            trace.append(TraceEvent.create(
                stage="S1_EXTRACT",
                operation="node_created",
                subject_fqdn=node.fqdn,
                detail={"kind": node.kind.value, "layer_code": node.layer_code},
                family=EventFamily.DISCOVERY.value,
            ))

            # Create REFERENCES edges for each resolved reference
            for ref_fqdn in refs:
                edge = Edge.create(
                    source_fqdn=node.fqdn,
                    target_fqdn=ref_fqdn,
                    kind=EdgeKind.REFERENCES,
                )
                builder.add_edge(edge)

    graph = builder.build()
    state = state.with_graph(graph)

    if errors:
        state = state.with_errors(*errors)
    if warnings:
        state = state.with_warnings(*warnings)
    if trace:
        state = state.with_trace_events(*trace)

    # Record extraction metadata
    state = state.with_metadata("node_count", len(graph.nodes))
    state = state.with_metadata("edge_count", len(graph.edges))

    return state


def _discover_artifacts(
    search_layers: list[str],
    discovery_layers: dict[str, Any],
    discovery_rules: dict[str, Any],
    build_artifact_types: list[str],
    errors: list[CompilerError],
) -> list[dict[str, Any]]:
    """Discover artifact files from declared layers."""
    all_discovered: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()

    artifact_pattern = re.compile(discovery_rules.get("filename_pattern", ""))
    excluded_dirs = discovery_rules.get("excluded_directories", [])

    for layer_code in search_layers:
        layer_config = discovery_layers.get(layer_code)
        if not layer_config:
            errors.append(CompilerError(
                code=ErrorCode.E901_INTERNAL_ERROR,
                message=f"Layer {layer_code} not found in STRUCTURE_DISCOVERY_V0",
                phase="S1_EXTRACT",
            ))
            continue

        if layer_code == "DOMAINS":
            allowed_domains = layer_config.get("allowed_domains", [])
            if not allowed_domains:
                errors.append(CompilerError(
                    code=ErrorCode.E901_INTERNAL_ERROR,
                    message="DOMAINS layer missing allowed_domains declaration",
                    phase="S1_EXTRACT",
                ))
                continue

            for domain_name in allowed_domains:
                _scan_layer(
                    layer_code, layer_config, artifact_pattern,
                    excluded_dirs, all_discovered, seen_paths,
                    errors, domain_name=domain_name,
                )
        else:
            _scan_layer(
                layer_code, layer_config, artifact_pattern,
                excluded_dirs, all_discovered, seen_paths,
                errors, domain_name=None,
            )

    # Apply scope filter
    filtered = [
        a for a in all_discovered
        if a["artifact_type"] in build_artifact_types
    ]

    return sorted(filtered, key=lambda x: (x["artifact_code"], x["source_path"]))


def _scan_layer(
    layer_code: str,
    layer_config: dict[str, Any],
    artifact_pattern: re.Pattern,
    excluded_dirs: list[str],
    artifacts: list[dict[str, Any]],
    seen_paths: set[Path],
    errors: list[CompilerError],
    domain_name: str | None = None,
) -> None:
    """Scan a layer's registry module recursively for artifact files."""
    registry_module = layer_config.get("registry_module", "")
    resolver = LayerResolver()

    if layer_code == "DOMAINS" and domain_name:
        root_path = resolver.resolve_layer_root(layer_code, domain=domain_name)
    else:
        root_path = resolver.resolve_layer_root(layer_code)

    if not root_path.exists():
        errors.append(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=f"Layer {layer_code} registry path does not exist: {root_path}",
            phase="S1_EXTRACT",
        ))
        return

    for md_path in root_path.rglob("*.md"):
        if md_path.resolve() in seen_paths:
            continue
        seen_paths.add(md_path.resolve())

        if any(excl in md_path.parts for excl in excluded_dirs):
            continue

        match = artifact_pattern.match(md_path.name)
        if not match:
            continue

        artifact_type = match.group("type")
        artifact_name = match.group("name")
        version = match.group("version")
        artifact_code = f"{artifact_type}_{artifact_name}_V{version}"

        rel_path = md_path.parent.relative_to(root_path)
        if str(rel_path) == ".":
            full_module_path = registry_module
        else:
            full_module_path = f"{registry_module}.{str(rel_path).replace('/', '.')}"

        entry: dict[str, Any] = {
            "artifact_code": artifact_code,
            "artifact_type": artifact_type,
            "layer_code": layer_code,
            "module_path": full_module_path,
            "source_path": str(md_path),
            "version": version,
        }

        if domain_name:
            entry["domain_name"] = domain_name

        artifacts.append(entry)


def _derive_fqdns(
    discovered: list[dict[str, Any]],
    identity_rules: list[dict[str, Any]],
    errors: list[CompilerError],
) -> None:
    """Derive namespace and FQDN for each discovered artifact."""
    for artifact in discovered:
        module_path = artifact.get("module_path", "")
        layer_code = artifact.get("layer_code")
        domain_name = artifact.get("domain_name")

        if layer_code == "DOMAINS":
            if not domain_name:
                errors.append(CompilerError(
                    code=ErrorCode.E901_INTERNAL_ERROR,
                    message=f"DOMAINS artifact missing domain_name: {artifact['artifact_code']}",
                    phase="S1_EXTRACT",
                ))
                continue
            namespace = f"domains.{domain_name}"
        else:
            namespace = None
            for rule in identity_rules:
                if rule.get("match", "") in module_path:
                    template = rule.get("namespace_template")
                    if template:
                        namespace = template.format(module_path=module_path)
                    else:
                        namespace = rule.get("namespace", "")
                    break

            if not namespace:
                errors.append(CompilerError(
                    code=ErrorCode.E901_INTERNAL_ERROR,
                    message=(
                        f"No namespace rule matched module_path='{module_path}' "
                        f"(artifact_code={artifact['artifact_code']})"
                    ),
                    phase="S1_EXTRACT",
                ))
                continue

        artifact["namespace"] = namespace
        artifact["fqdn"] = f"{namespace}::{artifact['artifact_code']}"


def _parse_artifact_to_node(
    artifact: dict[str, Any],
    artifact_registry: dict[str, list[str]],
) -> tuple[Node | None, list[str], list[CompilerError], list[CompilerError]]:
    """
    Parse a single artifact file into a Node + reference list.

    Returns:
        (node_or_None, reference_fqdns, errors, warnings)
    """
    errors: list[CompilerError] = []
    warnings: list[CompilerError] = []

    fqdn = artifact["fqdn"]
    artifact_code = artifact["artifact_code"]
    source_path = Path(artifact["source_path"])

    # Read source file
    try:
        content_raw = source_path.read_text(encoding="utf-8")
    except Exception as e:
        errors.append(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=f"Failed to read file: {e}",
            phase="S1_EXTRACT",
            fqdn_id=fqdn,
            artifact_code=artifact_code,
        ))
        return None, [], errors, warnings

    # Extract Machine block
    match = _MACHINE_BLOCK_PATTERN.search(content_raw)
    if not match:
        errors.append(CompilerError(
            code=ErrorCode.E101_INVALID_YAML,
            message="No ## Machine block found",
            phase="S1_EXTRACT",
            fqdn_id=fqdn,
            artifact_code=artifact_code,
        ))
        return None, [], errors, warnings

    try:
        frontmatter = yaml.safe_load(match.group("machine_yaml").rstrip())
    except yaml.YAMLError as e:
        errors.append(CompilerError(
            code=ErrorCode.E101_INVALID_YAML,
            message=f"YAML parse error in Machine block: {e}",
            phase="S1_EXTRACT",
            fqdn_id=fqdn,
            artifact_code=artifact_code,
        ))
        return None, [], errors, warnings

    if not isinstance(frontmatter, dict):
        errors.append(CompilerError(
            code=ErrorCode.E101_INVALID_YAML,
            message="Machine block YAML must be a dictionary",
            phase="S1_EXTRACT",
            fqdn_id=fqdn,
            artifact_code=artifact_code,
        ))
        return None, [], errors, warnings

    # Reject deprecated artifacts
    if frontmatter.get("status") == "deprecated":
        warnings.append(CompilerError(
            code=ErrorCode.E005_DEPRECATED_ARTIFACT,
            message=f"Skipping deprecated artifact: {artifact_code}",
            phase="S1_EXTRACT",
            fqdn_id=fqdn,
            artifact_code=artifact_code,
        ))
        return None, [], errors, warnings

    # Compute content hash
    content_hash = hashlib.sha256(content_raw.encode("utf-8")).hexdigest()

    # Determine node kind
    artifact_type = artifact["artifact_type"]
    kind = _TYPE_TO_KIND.get(artifact_type)
    if kind is None:
        errors.append(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=f"Unknown artifact type: {artifact_type}",
            phase="S1_EXTRACT",
            fqdn_id=fqdn,
            artifact_code=artifact_code,
        ))
        return None, [], errors, warnings

    # Extract references
    references, ref_errors = _extract_references(
        frontmatter, fqdn, artifact_code, artifact_registry
    )
    errors.extend(ref_errors)

    # Create Node
    node = Node.create(
        fqdn=fqdn,
        kind=kind,
        namespace=artifact["namespace"],
        artifact_code=artifact_code,
        version=artifact["version"],
        layer_code=artifact["layer_code"],
        content_hash=content_hash,
        frontmatter=frontmatter,
        domain_name=artifact.get("domain_name"),
        metadata={
            "source_path": artifact["source_path"],
            "module_path": artifact.get("module_path", ""),
            "content": content_raw,
            "references": sorted(references),
        },
    )

    return node, references, errors, warnings


def _extract_references(
    frontmatter: dict[str, Any],
    source_fqdn: str,
    artifact_code: str,
    artifact_registry: dict[str, list[str]],
) -> tuple[list[str], list[CompilerError]]:
    """
    Extract FQDN references from artifact frontmatter.

    CONSTITUTIONAL: FQDN-only enforcement — bare codes are rejected.
    """
    references: set[str] = set()
    errors: list[CompilerError] = []

    def validate_ref(ref_value: str) -> str | None:
        if "::" not in ref_value:
            errors.append(CompilerError(
                code=ErrorCode.E104_INVALID_FQDN,
                message=f"Bare code forbidden: '{ref_value}'. Use FQDN (namespace::code)",
                phase="S1_EXTRACT",
                fqdn_id=source_fqdn,
                artifact_code=artifact_code,
            ))
            return None

        # Self-reference filter
        if ref_value == source_fqdn:
            return None

        return ref_value

    # Singular reference fields
    singular_fields = ["vocabulary_id", "governed_by", "structure", "runtime_binding", "transform"]
    # Plural reference fields
    plural_fields = ["transforms", "side_effects"]

    # RB bindings: keys are artifact FQDNs
    core = frontmatter.get("core", {})
    if isinstance(core, dict) and "bindings" in core:
        bindings = core["bindings"]
        if isinstance(bindings, dict):
            for binding_key in bindings.keys():
                resolved = validate_ref(binding_key)
                if resolved:
                    references.add(resolved)

    def scan_recursive(data: Any) -> None:
        if isinstance(data, dict):
            for k, v in data.items():
                if k in singular_fields:
                    if isinstance(v, str):
                        resolved = validate_ref(v)
                        if resolved:
                            references.add(resolved)
                elif k in plural_fields and isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            resolved = validate_ref(item)
                            if resolved:
                                references.add(resolved)
                else:
                    scan_recursive(v)
        elif isinstance(data, list):
            for item in data:
                scan_recursive(item)

    scan_recursive(frontmatter)

    return sorted(references), errors
