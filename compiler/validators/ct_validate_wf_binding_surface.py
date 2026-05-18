"""
CT_VALIDATE_WF_BINDING_SURFACE - WF-Level Binding Surface Validator

Validates that all WF node input bindings reference only declared sources:
  - $.payload.<field>         → field must exist in IN node payload_schema
  - $.results.<NODE>.<field>  → NODE must be a CC node in this WF,
                                 field must exist in that CC's core.outputs
  - <literal>                 → always valid (constant value)

Enforces INVARIANT_BINDING_SURFACE_CLOSED_V0:
  - No unknown IN fields
  - No unknown WF nodes
  - No unknown CC output fields
  - No raw DSL leaking through (any $ prefix not matching the above is rejected)

Validation Scope: WF-level structural surface (not CC-internal pipeline)
- Validates binding TARGETS exist
- Does NOT validate types
- Does NOT validate CC-internal pipeline references (cc_inputs_satisfied handles that)
"""

import re


def execute(artifact: dict, compilation_context: dict) -> dict:
    """
    Validate WF-level binding surface against declared sources.

    Args:
        artifact: WF artifact (normalized, with frontmatter.core.nodes)
        compilation_context: Build context with artifacts_by_fqdn

    Returns:
        {
            "validation_count": int,
            "violations": list[dict],
            "status": "PASSED/VIOLATION/SKIPPED"
        }
    """
    artifact_type = artifact.get("artifact_type")
    if artifact_type != "WF":
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED",
            "reason": f"Artifact type {artifact_type} not in scope (WF only)"
        }

    wf_code = artifact.get("wf_code") or artifact.get("artifact_code", "UNKNOWN")
    frontmatter = artifact.get("frontmatter", {})
    core = frontmatter.get("core", {})

    if not core:
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED",
            "reason": "No core section found"
        }

    nodes = core.get("nodes", {})
    if not nodes:
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED",
            "reason": "No nodes found"
        }

    artifacts_by_fqdn = compilation_context.get("artifacts_by_fqdn", {})

    # Resolve IN node payload schema from the IN artifact's core.inputs
    # The WF's IN node carries only a code reference — the declared fields
    # live on the separate IN artifact under core.inputs.
    payload_schema = {}
    for node_spec in nodes.values():
        if node_spec.get("type") == "IN":
            in_code = node_spec.get("code", "")
            in_artifact = _resolve_artifact(in_code, artifacts_by_fqdn)
            if in_artifact:
                in_core = (
                    in_artifact.get("frontmatter", {}).get("core", {})
                    or in_artifact.get("core", {})
                )
                payload_schema = in_core.get("inputs", {})
            break

    # Build WF CC node map: node_id → cc_code (the CC artifact code for that node)
    wf_cc_nodes = {}
    for node_id, node_spec in nodes.items():
        if node_spec.get("type") == "CC":
            wf_cc_nodes[node_id] = node_spec.get("code", "")

    violations = []
    validation_count = 0

    for node_id, node_spec in nodes.items():
        if node_spec.get("type") != "CC":
            continue

        node_inputs = node_spec.get("inputs", {})
        if not node_inputs:
            continue

        for param_name, ref in node_inputs.items():
            if not isinstance(ref, str):
                # Non-string literal (int, bool) — always valid
                continue

            if not ref.startswith("$"):
                # String literal constant — always valid
                continue

            validation_count += 1

            if ref.startswith("$.payload."):
                # WF boundary: must exist in IN payload_schema
                field = ref[len("$.payload."):].split(".")[0]
                if field not in payload_schema:
                    violations.append({
                        "wf_code": wf_code,
                        "node": node_id,
                        "param": param_name,
                        "violation": (
                            f"Binding '$.payload.{field}' references unknown IN field"
                        ),
                        "location": f"core.nodes.{node_id}.inputs.{param_name}",
                        "reference": ref,
                        "available_fields": sorted(payload_schema.keys()),
                        "fix": (
                            f"Add '{field}' to IN node payload_schema "
                            f"OR correct the binding reference"
                        )
                    })

            elif ref.startswith("$.results."):
                # WF inter-node reference: $.results.SOURCE_NODE.field
                match = re.match(r'^\$\.results\.([^.]+)\.(.+)$', ref)
                if not match:
                    violations.append({
                        "wf_code": wf_code,
                        "node": node_id,
                        "param": param_name,
                        "violation": f"Malformed $.results reference: '{ref}'",
                        "location": f"core.nodes.{node_id}.inputs.{param_name}",
                        "reference": ref,
                        "fix": "Use format: $.results.<WF_NODE_ID>.<output_field>"
                    })
                    continue

                source_node_id = match.group(1)
                output_field = match.group(2).split(".")[0]

                # SOURCE_NODE must be a CC node in this WF
                if source_node_id not in wf_cc_nodes:
                    violations.append({
                        "wf_code": wf_code,
                        "node": node_id,
                        "param": param_name,
                        "violation": (
                            f"Binding references unknown WF node '{source_node_id}'"
                        ),
                        "location": f"core.nodes.{node_id}.inputs.{param_name}",
                        "reference": ref,
                        "available_nodes": sorted(wf_cc_nodes.keys()),
                        "fix": (
                            f"Use an existing CC node ID OR add '{source_node_id}' "
                            f"as a CC node to the WF"
                        )
                    })
                    continue

                # Resolve source CC artifact and check output field
                source_cc_code = wf_cc_nodes[source_node_id]
                source_cc = _resolve_artifact(source_cc_code, artifacts_by_fqdn)

                if source_cc is None:
                    # CC artifact not in build graph — parse/validate phase catches this
                    continue

                cc_outputs = source_cc.get("frontmatter", {}).get("core", {}).get("outputs", {})
                if not cc_outputs:
                    cc_outputs = source_cc.get("core", {}).get("outputs", {})

                if output_field not in cc_outputs:
                    violations.append({
                        "wf_code": wf_code,
                        "node": node_id,
                        "param": param_name,
                        "source_node": source_node_id,
                        "source_cc": source_cc_code,
                        "violation": (
                            f"Binding references unknown output field '{output_field}' "
                            f"on '{source_node_id}' (CC: {source_cc_code})"
                        ),
                        "location": f"core.nodes.{node_id}.inputs.{param_name}",
                        "reference": ref,
                        "available_outputs": sorted(cc_outputs.keys()),
                        "fix": (
                            f"Add '{output_field}' to {source_cc_code} core.outputs "
                            f"OR correct the binding reference"
                        )
                    })

            else:
                # Unknown $ prefix — not a recognized binding grammar
                violations.append({
                    "wf_code": wf_code,
                    "node": node_id,
                    "param": param_name,
                    "violation": f"Unrecognized binding reference grammar: '{ref}'",
                    "location": f"core.nodes.{node_id}.inputs.{param_name}",
                    "reference": ref,
                    "fix": (
                        "Use only: $.payload.<field>, $.results.<NODE>.<field>, "
                        "or a literal constant"
                    )
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
        "status": "PASSED"
    }


def _resolve_artifact(cc_code: str, artifacts_by_fqdn: dict) -> dict | None:
    """
    Resolve a CC artifact from the compiled artifact map.

    Tries:
      1. Direct key match (if cc_code is already an FQDN)
      2. Suffix match (namespace::cc_code)

    Args:
        cc_code: CC artifact code (short name or FQDN)
        artifacts_by_fqdn: Compiled artifact map keyed by FQDN

    Returns:
        Artifact dict or None if not found
    """
    if cc_code in artifacts_by_fqdn:
        return artifacts_by_fqdn[cc_code]

    # Try FQDN suffix match (e.g. "ai_governance::CC_RESOLVE_LICENSE_TIER_V0")
    for fqdn, artifact in artifacts_by_fqdn.items():
        if fqdn.endswith(f"::{cc_code}"):
            return artifact

    return None