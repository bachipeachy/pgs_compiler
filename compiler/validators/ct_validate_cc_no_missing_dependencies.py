"""
CT_VALIDATE_CC_NO_MISSING_DEPENDENCIES - Dependency Ordering Validator

Validates that all CC dependencies are satisfied before execution.

Enforces INVARIANT_CC_NO_MISSING_DEPENDENCIES_V0:
- No forward references (CC_B references CC_C that appears later)
- No cross-branch references (CC_B references CC_C on different branch)

Validation Scope: ORDERING and REACHABILITY ONLY
- Validates referenced CC appears EARLIER in execution path
- Validates referenced CC is on SAME execution path (not different branch)
- Does NOT validate FQDN syntax (enforced by parse phase)
- Does NOT validate field existence (delegated to INVARIANT_CC_INPUTS_SATISFIED_V0)

Per-path validation to avoid false positives from unreachable branches.
"""

import re
from typing import Any, List, Set, Dict


def execute(artifact: dict, compilation_context: dict) -> dict:
    """
    Validate CC dependency ordering and reachability.

    Args:
        artifact: WF artifact to validate
        compilation_context: Build context

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

    # Extract nodes and start_node
    nodes = core.get("nodes", {})
    start_node_code = core.get("start_node")

    if not nodes:
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED",
            "reason": "No nodes found in core section"
        }

    if not start_node_code:
        violations.append({
            "wf_code": artifact_code,
            "violation": "No start_node defined in workflow",
            "location": "core",
            "fix": "Add start_node: IN_XXX_V0"
        })
        return {
            "validation_count": 1,
            "violations": violations,
            "status": "VIOLATION"
        }

    # Derive all execution paths
    paths = _derive_execution_paths(nodes, start_node_code)

    if not paths:
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED",
            "reason": "No execution paths found (possible cycle or unreachable EXIT)"
        }

    # Validate dependency ordering for each path
    validation_count = 0

    for path_index, path in enumerate(paths):
        executed_ccs = set()  # Track CCs executed so far in THIS path

        for node_code in path:
            node = nodes.get(node_code)
            if not node:
                continue

            if node.get("type") != "CC":
                continue

            # Get node inputs
            node_inputs = node.get("inputs", {})
            if not node_inputs:
                # No inputs to validate
                executed_ccs.add(node_code)
                continue

            # Validate each input reference
            for input_name, input_ref in node_inputs.items():
                # Only validate JSONPath references to $.results.*
                if not isinstance(input_ref, str) or not input_ref.startswith("$.results."):
                    continue

                validation_count += 1

                # Parse $.results.step_name.* (for CC pipeline steps)
                # OR $.results.CC_XXX.* (for WF node-level references - rare but possible)
                match = re.match(r'^\$\.results\.([^.]+)', input_ref)
                if not match:
                    continue

                referenced_step_or_node = match.group(1)

                # Check if this is a node-level reference (CC_XXX_V0 pattern)
                # vs step-level reference (step_name pattern)
                is_node_reference = referenced_step_or_node.startswith("CC_") and "_V" in referenced_step_or_node

                if is_node_reference:
                    # Node-level reference: Check if CC node already executed in THIS path
                    if referenced_step_or_node not in executed_ccs:
                        violations.append({
                            "wf_code": artifact_code,
                            "path_index": path_index,
                            "node_code": node_code,
                            "input_name": input_name,
                            "violation": f"Forward reference: references {referenced_step_or_node} which has not executed yet in this path",
                            "location": f"core.nodes.{node_code}.inputs.{input_name}",
                            "reference": input_ref,
                            "executed_ccs": list(executed_ccs),
                            "fix": f"Reorder nodes so {referenced_step_or_node} appears before {node_code} OR reference earlier node"
                        })
                else:
                    # Step-level reference: This is internal to CC pipeline
                    # CC pipeline steps are linear (no branching), so:
                    # 1. Extract referenced step name
                    # 2. Validate step ordering is handled by INVARIANT_CC_INPUTS_SATISFIED_V0
                    # This invariant only validates NODE-level ordering, not step-level
                    pass

            # Add this CC to executed set for THIS path
            executed_ccs.add(node_code)

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


def _derive_execution_paths(nodes: dict, start_node_code: str) -> List[List[str]]:
    """
    Derive all execution paths from start_node to EXIT.

    Args:
        nodes: WF nodes dictionary
        start_node_code: Starting node code

    Returns:
        List of paths (each path is list of node codes in execution order)
    """
    if start_node_code not in nodes:
        return []

    # BFS to find all paths
    all_paths = []
    queue = [(start_node_code, [start_node_code])]  # (current_node, path_so_far)
    visited_paths = set()  # Track (node, path_tuple) to avoid infinite loops

    max_iterations = 1000  # Safety limit
    iteration = 0

    while queue and iteration < max_iterations:
        iteration += 1
        current_code, path = queue.pop(0)

        # Convert path to tuple for hashable set membership
        path_tuple = tuple(path)
        state_key = (current_code, path_tuple)

        if state_key in visited_paths:
            continue
        visited_paths.add(state_key)

        current_node = nodes.get(current_code)
        if not current_node:
            continue

        # Check if this is EXIT node
        if current_node.get("type") == "EXIT" or current_code == "EXIT":
            all_paths.append(path)
            continue

        # Get next transitions
        next_transitions = current_node.get("next", {})

        if not next_transitions:
            # Terminal node (no next transitions) - treat as path end
            all_paths.append(path)
            continue

        # Explore all branches
        for condition, next_node_code in next_transitions.items():
            if next_node_code == "EXIT":
                # Reached EXIT
                all_paths.append(path + ["EXIT"])
            elif next_node_code in path:
                # Cycle detected - skip to avoid infinite loop
                continue
            else:
                # Add to queue
                new_path = path + [next_node_code]
                queue.append((next_node_code, new_path))

    return all_paths
