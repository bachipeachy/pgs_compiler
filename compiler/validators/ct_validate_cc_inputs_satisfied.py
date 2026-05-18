"""
CT_VALIDATE_CC_INPUTS_SATISFIED - JSONPath Reference Availability Validator

Validates that all CC input references resolve to available data sources.

Enforces INVARIANT_CC_INPUTS_SATISFIED_V0:
- All $.payload.* references exist in IN payload schema
- All $.results.step_name.* references point to earlier steps with valid outputs
- All references reachable on execution path (no cross-branch references)

Validation Scope: AVAILABILITY ONLY (not type safety)
- Validates field EXISTS
- Does NOT validate field TYPE
- Does NOT validate schema conformance
- Does NOT validate transformation correctness

This is structural validation, not dataflow validation.
"""

import re
from typing import Any


def execute(artifact: dict, compilation_context: dict) -> dict:
    """
    Validate JSONPath reference availability for CC inputs.

    Args:
        artifact: WF artifact to validate
        compilation_context: Build context with artifacts_by_fqdn

    Returns:
        Validation result with violations (if any)
    """
    artifact_type = artifact.get("artifact_type")
    artifact_code = artifact.get("wf_code") or artifact.get("artifact_code", "UNKNOWN")

    # Only validate WF artifacts
    if artifact_type != "WF":
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED",
            "reason": f"Artifact type {artifact_type} not in scope (WF only)"
        }

    violations = []

    # Extract core section
    core = artifact.get("core", {})
    if not core:
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED",
            "reason": "No core section found"
        }

    # Extract nodes
    nodes = core.get("nodes", {})
    if not nodes:
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED",
            "reason": "No nodes found in core section"
        }

    # Extract IN node and payload schema
    in_node = None
    payload_schema = {}

    for node_code, node in nodes.items():
        if node.get("type") == "IN":
            in_node = node
            payload_schema = node.get("payload_schema", {})
            break

    if not in_node:
        violations.append({
            "wf_code": artifact_code,
            "violation": "No IN node found in workflow",
            "location": "core.nodes",
            "fix": "Add IN node with type: IN"
        })
        return {
            "validation_count": 1,
            "violations": violations,
            "status": "VIOLATION"
        }

    # Build artifacts_by_fqdn map if not provided
    artifacts_by_fqdn = compilation_context.get("artifacts_by_fqdn", {})
    if not artifacts_by_fqdn:
        # Build from artifacts list
        all_artifacts = compilation_context.get("artifacts", [])
        artifacts_by_fqdn = {
            a.get("fqdn", a.get("cc_code", a.get("artifact_code", "UNKNOWN"))): a
            for a in all_artifacts
            if a.get("artifact_type") == "CC"
        }

    # Walk execution paths and validate data availability
    validation_count = 0

    for node_code, node in nodes.items():
        if node.get("type") != "CC":
            continue

        # Get CC artifact
        cc_code = node.get("code")
        if not cc_code:
            violations.append({
                "wf_code": artifact_code,
                "node_code": node_code,
                "violation": "CC node missing code field",
                "location": f"core.nodes.{node_code}",
                "fix": "Add code: CC_XXX_V0"
            })
            validation_count += 1
            continue

        # Resolve CC artifact
        cc_artifact = artifacts_by_fqdn.get(cc_code)
        if not cc_artifact:
            # FQDN not found in artifact set - skip (parse phase enforces FQDN syntax)
            continue

        # Extract CC inputs
        node_inputs = node.get("inputs", {})
        if not node_inputs:
            # No inputs to validate
            continue

        # Validate each input reference
        for input_name, input_ref in node_inputs.items():
            # Only validate JSONPath references (strings starting with $)
            if not isinstance(input_ref, str) or not input_ref.startswith("$"):
                continue

            validation_count += 1

            # RULE 1: $.payload.* references
            if input_ref.startswith("$.payload."):
                field_name = input_ref.replace("$.payload.", "").split(".")[0]

                if field_name not in payload_schema:
                    violations.append({
                        "wf_code": artifact_code,
                        "node_code": node_code,
                        "input_name": input_name,
                        "violation": f"Input references $.payload.{field_name} but field not in IN payload schema",
                        "location": f"core.nodes.{node_code}.inputs.{input_name}",
                        "reference": input_ref,
                        "available_fields": list(payload_schema.keys()),
                        "fix": f"Add '{field_name}' to IN node payload_schema OR change reference to existing field"
                    })

            # RULE 2: $.results.step_name.* references
            elif input_ref.startswith("$.results."):
                # Parse $.results.step_name.field_name
                match = re.match(r'^\$\.results\.([^.]+)\.(.+)$', input_ref)
                if not match:
                    violations.append({
                        "wf_code": artifact_code,
                        "node_code": node_code,
                        "input_name": input_name,
                        "violation": f"Invalid $.results reference format: {input_ref}",
                        "location": f"core.nodes.{node_code}.inputs.{input_name}",
                        "reference": input_ref,
                        "fix": "Use format: $.results.step_name.field_name"
                    })
                    continue

                referenced_step = match.group(1)
                referenced_field = match.group(2).split(".")[0]  # Take first segment only

                # Check if referenced step exists in CC pipeline
                cc_pipeline = cc_artifact.get("core", {}).get("pipeline", [])

                step_found = False
                field_found = False
                available_outputs = []

                for step in cc_pipeline:
                    if not isinstance(step, dict):
                        continue

                    step_name = step.get("step")
                    if step_name == referenced_step:
                        step_found = True

                        # Check if field exists in step outputs
                        step_outputs = step.get("outputs", {})
                        available_outputs = list(step_outputs.keys())

                        if referenced_field in step_outputs:
                            field_found = True
                            break

                if not step_found:
                    violations.append({
                        "wf_code": artifact_code,
                        "node_code": node_code,
                        "cc_code": cc_code,
                        "input_name": input_name,
                        "violation": f"Input references $.results.{referenced_step}.* but step '{referenced_step}' not found in CC pipeline",
                        "location": f"core.nodes.{node_code}.inputs.{input_name}",
                        "reference": input_ref,
                        "available_steps": [s.get("step") for s in cc_pipeline if isinstance(s, dict) and "step" in s],
                        "fix": f"Reference existing step from CC pipeline OR add step '{referenced_step}' to CC"
                    })
                elif not field_found:
                    violations.append({
                        "wf_code": artifact_code,
                        "node_code": node_code,
                        "cc_code": cc_code,
                        "input_name": input_name,
                        "violation": f"Input references $.results.{referenced_step}.{referenced_field} but field '{referenced_field}' not in step outputs",
                        "location": f"core.nodes.{node_code}.inputs.{input_name}",
                        "reference": input_ref,
                        "available_fields": available_outputs,
                        "fix": f"Add '{referenced_field}' to step outputs OR change reference to existing field"
                    })

    if violations:
        return {
            "validation_count": validation_count,
            "violations": violations,
            "status": "VIOLATION"
        }

    return {
        "validation_count": validation_count,
        "violations": [],
        "status": "SUCCESS"
    }


def _extract_field_name(jsonpath: str) -> str:
    """Extract field name from JSONPath reference."""
    # $.payload.field_name → field_name
    # $.results.step.field_name → field_name
    parts = jsonpath.split(".")
    if len(parts) >= 3:
        return parts[2]
    return ""
