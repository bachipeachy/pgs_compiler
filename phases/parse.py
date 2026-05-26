"""
Parse phase: Extract frontmatter + content from markdown artifacts.

Consolidated Identity (FQDN) Resolution based on STRUCTURE_IDENTITY_V0.

Design:
- Compute FQDN namespace using STRUCTURE_IDENTITY_V0 (derivation logic)
- Split frontmatter (YAML) from content
- Normalize references to FQDN (Single Source of Truth: STRUCTURE_IDENTITY_V0 rules)
- Ambiguity detection (Short name must resolve to exactly one FQDN)
- Local-scope precedence for resolution
- SELF-REFERENCE FILTERING (Prevents artificial circular dependencies)
"""

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    PhaseResult,
    PhaseStatus,
    parse_fqdn,
    sort_artifacts_by_fqdn,
)
from pgs_compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots


# Machine block pattern: ## Machine\n```yaml\n{yaml}\n```
MACHINE_BLOCK_PATTERN = re.compile(
    r"^## Machine\s*\n+```yaml\s*\n(?P<machine_yaml>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def extract_machine_block(content: str) -> tuple[dict | None, str]:
    """
    Extract Machine YAML block from PGS artifact.

    Returns:
        (frontmatter_dict, error_message)
        - frontmatter_dict: Parsed YAML from Machine block (None if failed)
        - error_message: Error description (empty string if success)

    CONSTITUTIONAL: Machine block is the ONLY source of metadata.
    Everything outside ## Machine is documentation only.
    """
    match = MACHINE_BLOCK_PATTERN.search(content)

    if not match:
        return None, "No ## Machine block found (expected: ## Machine\\n```yaml\\n...\\n```)"

    machine_yaml_text = match.group("machine_yaml").rstrip()

    try:
        frontmatter = yaml.safe_load(machine_yaml_text)
    except yaml.YAMLError as e:
        return None, f"YAML parse error in Machine block: {e}"

    if not isinstance(frontmatter, dict):
        return None, "Machine block YAML must be a dictionary"

    return frontmatter, ""


def parse_phase(
    discovered_artifacts: list[dict[str, Any]],
    required_fields: list[str] | None = None,
) -> PhaseResult:
    """
    Parse markdown artifacts and resolve identities.
    """
    required_fields = required_fields or []
    errors: list[CompilerError] = []
    parsed_artifacts: list[dict[str, Any]] = []

    try:
        # Step 1: Load STRUCTURE_IDENTITY_V0 (Master identity config)
        identity_master = load_structure_artifact("STRUCTURE_IDENTITY_V0", get_bootstrap_search_roots())
        identity_rules = identity_master.get("identity", {}).get("fqdn", {}).get("namespace", {}).get("derivation", {}).get("rules", [])
    except Exception as e:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={},
            errors=(CompilerError(
                code=ErrorCode.E901_INTERNAL_ERROR,
                message=f"Failed to load STRUCTURE_IDENTITY_V0: {e}",
                phase="PARSE",
            ),),
        )

    # Step 2: Compute actual Namespaces/FQDNs for all discovered artifacts
    # This was deferred from discovery phase
    for artifact in discovered_artifacts:
        module_path = artifact.get("module_path", "")
        layer_code = artifact.get("layer_code")
        domain_name = artifact.get("domain_name")

        # Domain federation: DOMAINS layer requires domain-specific namespace
        if layer_code == "DOMAINS":
            if not domain_name:
                raise CompilerError(
                    code=ErrorCode.E901_INTERNAL_ERROR,
                    message="DOMAINS artifact missing domain_name metadata",
                    phase="PARSE",
                    artifact_code=artifact.get("artifact_code"),
                    context={"module_path": module_path}
                )
            namespace = f"domains.{domain_name}"
        else:
            # Apply derivation rules from STRUCTURE_IDENTITY_V0
            namespace = None
            for rule in identity_rules:
                if rule.get("match", "") in module_path:
                    # Support namespace_template for dynamic derivation (e.g., pgs_capabilities)
                    template = rule.get("namespace_template")
                    if template:
                        namespace = template.format(module_path=module_path)
                    else:
                        namespace = rule.get("namespace", "")
                    break

            # CONSTITUTIONAL: Fail hard if namespace cannot be derived
            if not namespace:
                raise CompilerError(
                    code=ErrorCode.E901_INTERNAL_ERROR,
                    message=(
                        f"No namespace rule matched module_path='{module_path}' "
                        f"(artifact_code={artifact.get('artifact_code')}). "
                        f"Add a matching rule to STRUCTURE_IDENTITY_V0."
                    ),
                    phase="PARSE",
                    artifact_code=artifact.get("artifact_code"),
                    context={
                        "module_path": module_path,
                        "layer_code": layer_code,
                        "domain_name": domain_name,
                        "identity_rules": identity_rules
                    }
                )

        artifact["namespace"] = namespace
        artifact["fqdn_id"] = f"{namespace}::{artifact['artifact_code']}"

    # Step 3: Build global artifact registry for reference resolution (ambiguity detection)
    artifact_registry: dict[str, list[str]] = {}
    for artifact in discovered_artifacts:
        code = artifact["artifact_code"]
        ns = artifact["namespace"]
        if code not in artifact_registry:
            artifact_registry[code] = []
        if ns not in artifact_registry[code]:
            artifact_registry[code].append(ns)

    # Step 4: Parse files and resolve references
    for artifact in discovered_artifacts:
        fqdn_id = artifact["fqdn_id"]
        artifact_code = artifact["artifact_code"]
        source_path = Path(artifact["source_path"])
        namespace = artifact["namespace"]

        try:
            content_raw = source_path.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(
                CompilerError(
                    code=ErrorCode.E901_INTERNAL_ERROR,
                    message=f"Failed to read file: {e}",
                    phase="PARSE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    source_path=source_path,
                )
            )
            continue

        # CONSTITUTIONAL: Extract Machine block (single source of truth)
        frontmatter, error_msg = extract_machine_block(content_raw)

        if frontmatter is None:
            errors.append(
                CompilerError(
                    code=ErrorCode.E101_INVALID_YAML,
                    message=error_msg,
                    phase="PARSE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    source_path=source_path,
                )
            )
            continue

        # Content is everything (documentation only, not used in compilation)
        content_text = content_raw

        # FAIL HARD on deprecated artifacts
        status = frontmatter.get("status")
        if status == "deprecated":
            deprecated_reason = frontmatter.get("deprecated_reason", "No reason provided")
            errors.append(
                CompilerError(
                    code=ErrorCode.E001_NO_ARTIFACTS,  # Using E001 for deprecated
                    message=f"Deprecated artifact discovered: {artifact_code}",
                    phase="PARSE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    source_path=source_path,
                    context={"reason": deprecated_reason}
                )
            )
            continue

        # Required field validation
        for field in required_fields:
            if field not in frontmatter:
                errors.append(
                    CompilerError(
                        code=ErrorCode.E102_MISSING_FIELD,
                        message=f"Missing required field: {field}",
                        phase="PARSE",
                        fqdn_id=fqdn_id,
                        artifact_code=artifact_code,
                        source_path=source_path,
                    )
                )

        content_hash = hashlib.sha256(content_raw.encode("utf-8")).hexdigest()

        # Resolve References (Consolidated logic)
        references, ref_errors = _resolve_all_references(
            frontmatter, namespace, artifact_registry, fqdn_id, artifact_code, source_path
        )
        errors.extend(ref_errors)

        parsed_artifacts.append({
            **artifact,
            "frontmatter": frontmatter,
            "content": content_text,
            "references": references,
            "content_hash": content_hash,
        })

    parsed_artifacts_sorted = sort_artifacts_by_fqdn(parsed_artifacts)

    if errors:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={"parsed_artifacts": parsed_artifacts_sorted},
            errors=tuple(errors),
        )
    else:
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={"parsed_artifacts": parsed_artifacts_sorted},
            errors=tuple(),
        )


def _resolve_all_references(
    frontmatter: dict[str, Any],
    source_namespace: str,
    artifact_registry: dict[str, list[str]],
    fqdn_id: str,
    artifact_code: str,
    source_path: Path,
) -> tuple[list[str], list[CompilerError]]:
    """
    Extract FQDN references from artifact frontmatter.

    CONSTITUTIONAL: FQDN-only enforcement (INVARIANT_FQDN_ONLY_REFERENCES_V0)
    - All references MUST use FQDN format (namespace::code)
    - Bare codes are REJECTED (no auto-resolution, no inference, no fallback)
    - Parser must reject, not repair
    """
    references: set[str] = set()
    errors: list[CompilerError] = []

    def resolve_ref(ref_value: str) -> str | None:
        """
        Strict FQDN-only validation.

        CONSTITUTIONAL: Zero inference, zero guessing, zero fallback.
        Bare codes are protocol violations - reject immediately.
        """
        # STRICT: FQDN ONLY
        if "::" not in ref_value:
            errors.append(
                CompilerError(
                    code=ErrorCode.E104_INVALID_FQDN,
                    message=f"Bare code forbidden: '{ref_value}'. Use FQDN (namespace::code)",
                    phase="PARSE",
                    fqdn_id=fqdn_id,
                    artifact_code=artifact_code,
                    source_path=source_path,
                    context={
                        "bare_code": ref_value,
                        "fix": "Update source artifact to use FQDN format",
                        "examples": [
                            f"capability_transforms::{ref_value}" if ref_value.startswith("CT_") else None,
                            f"capability_side_effects::{ref_value}" if ref_value.startswith("CS_") else None,
                            f"governance.layers::{ref_value}" if ref_value.startswith("STRUCTURE_") else None,
                            f"domains.blockchain::{ref_value}" if ref_value.startswith("CT_") or ref_value.startswith("CS_") else None,
                        ]
                    }
                )
            )
            return None

        # SELF-REFERENCE FILTER: Don't include self as dependency
        if ref_value == fqdn_id:
            return None

        return ref_value

    # Explicit artifact reference fields (declared, not inferred)
    fields_to_scan = ["vocabulary_id", "governed_by", "structure", "runtime_binding", "transform"]

    # Plural artifact reference fields
    fields_to_scan_plural = ["transforms", "side_effects"]

    # Special case: Extract RB bindings BEFORE recursive scan
    # RB artifacts have core.bindings where keys are CS/CT artifact codes
    core = frontmatter.get("core", {})
    if isinstance(core, dict) and "bindings" in core:
        bindings = core["bindings"]
        if isinstance(bindings, dict):
            for binding_key in bindings.keys():
                resolved = resolve_ref(binding_key)
                if resolved: references.add(resolved)

    def scan_recursive(data: Any):
        if isinstance(data, dict):
            for k, v in data.items():
                # Scan explicit singular reference fields
                if k in fields_to_scan:
                    if isinstance(v, str):
                        resolved = resolve_ref(v)
                        if resolved: references.add(resolved)
                # Scan explicit plural reference fields
                elif k in fields_to_scan_plural and isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            resolved = resolve_ref(item)
                            if resolved: references.add(resolved)
                else:
                    scan_recursive(v)
        elif isinstance(data, list):
            for item in data:
                scan_recursive(item)

    scan_recursive(frontmatter)

    return sorted(list(references)), errors
