"""
CT_VALIDATE_CC_NO_CHAINING

Validates CC artifacts contain no orchestration logic.

Enforces: INVARIANT_CC_NO_IMPLICIT_CHAINING_V0
"""

from typing import Any


# Forbidden fields that indicate orchestration logic
FORBIDDEN_FIELDS = [
    "next_step",      # Explicit chaining
    "next",           # State transitions
    "transitions",    # Workflow logic
    "flow",           # Control flow
    "conditional",    # Branching logic
    "loop",           # Iteration control
]


def execute(artifact: dict, compilation_context: dict) -> dict:
    """
    Validate CC contains no orchestration logic.

    Args:
        artifact: CC artifact (normalized)
        compilation_context: Not used (no cross-artifact validation needed)

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

    # RULE 1-6: Check for forbidden fields in frontmatter
    for field in FORBIDDEN_FIELDS:
        if field in frontmatter:
            violations.append({
                "cc_code": cc_code,
                "field": field,
                "value": frontmatter[field],
                "violation": f"CC contains {field} field (orchestration logic)",
                "severity": "CRITICAL",
                "fix": f"Remove {field} field - orchestration belongs in WF, not CC"
            })

    # RULE 1-6: Check for forbidden fields in core section
    core = frontmatter.get("core", {})
    for field in FORBIDDEN_FIELDS:
        if field in core:
            violations.append({
                "cc_code": cc_code,
                "location": "core",
                "field": field,
                "value": core[field],
                "violation": f"CC core contains {field} field (orchestration logic)",
                "severity": "CRITICAL",
                "fix": f"Remove {field} from core - orchestration belongs in WF"
            })

    # RULE 1-6: Check for forbidden fields in pipeline steps
    pipeline = core.get("pipeline", [])
    if isinstance(pipeline, list):
        for idx, step in enumerate(pipeline):
            if isinstance(step, dict):
                for field in FORBIDDEN_FIELDS:
                    if field in step:
                        step_name = step.get("step", f"step_{idx}")
                        violations.append({
                            "cc_code": cc_code,
                            "location": f"pipeline[{idx}]",
                            "step": step_name,
                            "field": field,
                            "value": step[field],
                            "violation": f"Pipeline step contains {field} field (orchestration logic)",
                            "severity": "CRITICAL",
                            "fix": f"Remove {field} from step - each step is atomic capability invocation"
                        })

    return _build_result(violations, 1 if violations else 0)


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
