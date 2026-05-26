"""
CT_VALIDATE_CC_NO_UNUSED_OUTPUTS - Unused Output Detector

Detects CC outputs that are never consumed by downstream nodes.

Enforces INVARIANT_CC_NO_UNUSED_OUTPUTS_V0:
- Tracks all CC outputs produced
- Tracks all CC inputs consumed
- Identifies outputs never referenced
- Emits WARNINGS (not errors)

Detection Scope: Code smell indicator (not hard violation)
- Helps identify incomplete workflows
- Highlights potential optimization opportunities
- Does NOT block builds
"""

import re
from typing import Any, Set, Dict


def execute(artifact: dict, compilation_context: dict) -> dict:
    """
    Detect unused CC outputs in workflow.

    Args:
        artifact: WF artifact to validate
        compilation_context: Build context with artifacts_by_fqdn

    Returns:
        Validation result with warnings (if any)
    """
    artifact_type = artifact.get("artifact_type")
    artifact_code = artifact.get("wf_code") or artifact.get("artifact_code", "UNKNOWN")

    # Only validate WF artifacts
    if artifact_type != "WF":
        return {
            "validation_count": 0,
            "warnings": [],
            "status": "SKIPPED",
            "reason": f"Artifact type {artifact_type} not in scope (WF only)"
        }

    warnings = []

    # Extract core section
    core = artifact.get("core", {})
    if not core:
        return {
            "validation_count": 0,
            "warnings": [],
            "status": "SKIPPED",
            "reason": "No core section found"
        }

    # Extract nodes
    nodes = core.get("nodes", {})
    if not nodes:
        return {
            "validation_count": 0,
            "warnings": [],
            "status": "SKIPPED",
            "reason": "No nodes found in core section"
        }

    # Build artifacts_by_fqdn map if not provided
    artifacts_by_fqdn = compilation_context.get("artifacts_by_fqdn", {})
    if not artifacts_by_fqdn:
        all_artifacts = compilation_context.get("artifacts", [])
        artifacts_by_fqdn = {
            a.get("fqdn_id", a.get("cc_code", a.get("artifact_code", "UNKNOWN"))): a
            for a in all_artifacts
            if a.get("artifact_type") == "CC"
        }

    # Track produced outputs: {step_name: [field1, field2, ...]}
    produced_outputs = {}

    # Track consumed references: {"$.results.step_name.field_name"}
    consumed_refs = set()

    # Pass 1: Collect all outputs from CC nodes
    for node_code, node in nodes.items():
        if node.get("type") != "CC":
            continue

        cc_code = node.get("code")
        if not cc_code:
            continue

        # Resolve CC artifact
        cc_artifact = artifacts_by_fqdn.get(cc_code)
        if not cc_artifact:
            # FQDN not found in artifact set - skip (parse phase enforces FQDN syntax)
            continue

        # Extract pipeline steps
        cc_pipeline = cc_artifact.get("core", {}).get("pipeline", [])

        for step in cc_pipeline:
            if not isinstance(step, dict):
                continue

            step_name = step.get("step")
            if not step_name:
                continue

            # Collect outputs from this step
            step_outputs = step.get("outputs", {})
            if step_outputs:
                if step_name not in produced_outputs:
                    produced_outputs[step_name] = []

                produced_outputs[step_name].extend(step_outputs.keys())

    # Pass 2: Collect all consumed references from WF nodes
    for node_code, node in nodes.items():
        if node.get("type") != "CC":
            continue

        node_inputs = node.get("inputs", {})
        if not node_inputs:
            continue

        # Track consumed references
        for input_ref in node_inputs.values():
            if isinstance(input_ref, str) and input_ref.startswith("$.results."):
                consumed_refs.add(input_ref)

    # Pass 3: Collect consumed references from CC pipeline steps
    for node_code, node in nodes.items():
        if node.get("type") != "CC":
            continue

        cc_code = node.get("code")
        if not cc_code:
            continue

        cc_artifact = artifacts_by_fqdn.get(cc_code)
        if not cc_artifact:
            continue

        cc_pipeline = cc_artifact.get("core", {}).get("pipeline", [])

        for step in cc_pipeline:
            if not isinstance(step, dict):
                continue

            step_inputs = step.get("inputs", {})
            if not step_inputs:
                continue

            # Track consumed references within pipeline
            for input_ref in step_inputs.values():
                if isinstance(input_ref, str) and input_ref.startswith("$.results."):
                    consumed_refs.add(input_ref)

    # Pass 4: Detect unused outputs
    validation_count = 0

    for step_name, fields in produced_outputs.items():
        for field in fields:
            validation_count += 1

            # Check if this output is consumed
            # Match both exact field and nested field references
            # $.results.step.field or $.results.step.field.nested
            is_consumed = False

            for consumed_ref in consumed_refs:
                # Extract step and field from consumed reference
                match = re.match(r'^\$\.results\.([^.]+)\.([^.]+)', consumed_ref)
                if match:
                    consumed_step = match.group(1)
                    consumed_field = match.group(2)

                    if consumed_step == step_name and consumed_field == field:
                        is_consumed = True
                        break

            if not is_consumed:
                warnings.append({
                    "wf_code": artifact_code,
                    "step_name": step_name,
                    "field_name": field,
                    "warning": f"Output '{step_name}.{field}' is produced but never consumed",
                    "severity": "WARNING",
                    "reference": f"$.results.{step_name}.{field}",
                    "suggestion": "Remove unused output OR add consumer OR verify if this is intentional (terminal/debug output)"
                })

    if warnings:
        return {
            "validation_count": validation_count,
            "warnings": warnings,
            "status": "WARNING"
        }

    return {
        "validation_count": validation_count,
        "warnings": [],
        "status": "SUCCESS"
    }
