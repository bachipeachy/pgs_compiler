"""
CT_VALIDATE_CC_BINDING

Validates CC pipeline step capability bindings.

Enforces: INVARIANT_CC_CAPABILITY_BINDING_VALID_V0
"""

from typing import Any


def execute(artifact: dict, compilation_context: dict) -> dict:
    """
    Validate CC pipeline step capability bindings.

    Args:
        artifact: CC artifact (normalized)
        compilation_context: Contains artifacts_by_fqdn for FQDN validation

    Returns:
        {
            "validation_count": int,
            "violations": list[dict],
            "status": "PASSED/FAILED"
        }
    """
    violations = []

    # Only validate CC artifacts
    artifact_type = artifact.get("artifact_type")
    if artifact_type != "CC":
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED"
        }

    cc_code = artifact.get("frontmatter", {}).get("cc_code", "UNKNOWN")
    frontmatter = artifact.get("frontmatter", {})
    core = frontmatter.get("core", {})
    pipeline = core.get("pipeline", [])

    if not isinstance(pipeline, list):
        violations.append({
            "cc_code": cc_code,
            "violation": "Pipeline must be a list of steps",
            "severity": "CRITICAL",
            "fix": "Change pipeline to list format"
        })
        return _build_result(violations, 0)

    # Get artifacts_by_fqdn for FQDN validation (optional - may not be available yet)
    artifacts_by_fqdn = compilation_context.get("artifacts_by_fqdn", {})

    # Validate each pipeline step
    for idx, step in enumerate(pipeline):
        if not isinstance(step, dict):
            violations.append({
                "cc_code": cc_code,
                "step_index": idx,
                "violation": f"Pipeline step must be a dict, got {type(step).__name__}",
                "severity": "CRITICAL",
                "fix": "Use dict format for pipeline steps"
            })
            continue

        step_name = step.get("step", f"step_{idx}")

        # RULE 1: Count capability bindings
        has_transform = "transform" in step
        has_side_effect = "side_effect" in step

        binding_count = sum([has_transform, has_side_effect])

        # RULE 1a: Zero bindings
        if binding_count == 0:
            violations.append({
                "cc_code": cc_code,
                "step": step_name,
                "step_index": idx,
                "violation": "Pipeline step has no capability binding (neither transform nor side_effect)",
                "severity": "CRITICAL",
                "fix": "Add either transform (for CT) or side_effect (for CS)"
            })

        # RULE 1b: Dual bindings
        elif binding_count > 1:
            violations.append({
                "cc_code": cc_code,
                "step": step_name,
                "step_index": idx,
                "transform": step.get("transform"),
                "side_effect": step.get("side_effect"),
                "violation": "Pipeline step binds both CT and CS (violates single responsibility)",
                "severity": "CRITICAL",
                "fix": "Split into two steps - one for transform, one for side_effect"
            })

        # RULE 2: Validate FQDN (if artifacts_by_fqdn available)
        if artifacts_by_fqdn:
            if has_transform:
                ct_code = step.get("transform")
                if ct_code and not _fqdn_exists(ct_code, artifacts_by_fqdn):
                    violations.append({
                        "cc_code": cc_code,
                        "step": step_name,
                        "step_index": idx,
                        "ct_code": ct_code,
                        "violation": f"CT not found in compilation graph: {ct_code}",
                        "severity": "CRITICAL",
                        "fix": f"Add {ct_code} artifact or fix transform reference"
                    })

            if has_side_effect:
                cs_code = step.get("side_effect")
                if cs_code and not _fqdn_exists(cs_code, artifacts_by_fqdn):
                    violations.append({
                        "cc_code": cc_code,
                        "step": step_name,
                        "step_index": idx,
                        "cs_code": cs_code,
                        "violation": f"CS not found in compilation graph: {cs_code}",
                        "severity": "CRITICAL",
                        "fix": f"Add {cs_code} artifact or fix side_effect reference"
                    })

    return _build_result(violations, len(pipeline))


def _fqdn_exists(code: str, artifacts_by_fqdn: dict) -> bool:
    """
    Check if FQDN exists in compilation graph.

    Args:
        code: Artifact code (may be short code or FQDN)
        artifacts_by_fqdn: Map of FQDN -> artifact

    Returns:
        True if FQDN exists (exact match or namespace match)
    """
    # Exact match
    if code in artifacts_by_fqdn:
        return True

    # Namespace match (e.g., "CT_FOO_V0" matches "transforms.atoms::CT_FOO_V0")
    for fqdn in artifacts_by_fqdn.keys():
        if fqdn.endswith(f"::{code}"):
            return True

    return False


def _build_result(violations: list[dict], validation_count: int) -> dict:
    """Build validation result."""
    if violations:
        return {
            "validation_count": validation_count,
            "violations": violations,
            "status": "FAILED"
        }

    return {
        "validation_count": validation_count,
        "violations": [],
        "status": "PASSED"
    }
