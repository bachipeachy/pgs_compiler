"""
CT_VALIDATE_WF_EXECUTION_GRAPH

Validates WF execution graph structure (DAG-based).

Enforces: INVARIANT_WF_EXECUTION_PATH_VALID_V0
"""

from typing import Any


def execute(artifact: dict, compilation_context: dict) -> dict:
    """
    Validate WF execution graph structure.

    Args:
        artifact: WF artifact (normalized)
        compilation_context: Contains artifacts_by_fqdn for CC resolution

    Returns:
        {
            "validation_count": int,
            "violations": list[dict],
            "status": "PASSED/FAILED"
        }
    """
    violations = []

    # Only validate WF artifacts
    artifact_type = artifact.get("artifact_type")
    if artifact_type != "WF":
        return {
            "validation_count": 0,
            "violations": [],
            "status": "SKIPPED"
        }

    wf_code = artifact.get("frontmatter", {}).get("wf_code", "UNKNOWN")
    frontmatter = artifact.get("frontmatter", {})
    core = frontmatter.get("core", {})

    # Extract graph structure
    start_node = core.get("start_node")
    nodes = core.get("nodes", {})

    if not start_node:
        violations.append({
            "wf_code": wf_code,
            "violation": "Missing start_node field",
            "severity": "CRITICAL",
            "fix": "Add start_node field to core section"
        })
        return _build_result(violations, 1)

    if not nodes:
        violations.append({
            "wf_code": wf_code,
            "violation": "Missing nodes field",
            "severity": "CRITICAL",
            "fix": "Add nodes field to core section"
        })
        return _build_result(violations, 1)

    # RULE 1: Validate start_node exists and is type IN or TI
    # Domain workflows start with IN (Intent), transport workflows start with TI (Transport Ingress)
    if start_node not in nodes:
        violations.append({
            "wf_code": wf_code,
            "violation": f"Invalid start_node: {start_node} not found in nodes",
            "severity": "CRITICAL",
            "fix": f"Add {start_node} to nodes or fix start_node reference"
        })
    else:
        start_node_def = nodes[start_node]
        node_type = start_node_def.get("type")
        if node_type not in ("IN", "TI"):
            violations.append({
                "wf_code": wf_code,
                "node": start_node,
                "violation": f"start_node has type={node_type}, expected type=IN or TI",
                "severity": "CRITICAL",
                "fix": f"Change {start_node} type to IN/TI or use different start_node"
            })

    # RULE 2: Check all nodes are reachable from start_node
    if start_node in nodes:
        reachable = _find_reachable_nodes(start_node, nodes)
        all_nodes = set(nodes.keys())
        unreachable = all_nodes - reachable

        for node_id in unreachable:
            violations.append({
                "wf_code": wf_code,
                "node": node_id,
                "violation": "Unreachable node (not reachable from start_node)",
                "severity": "CRITICAL",
                "fix": f"Either connect {node_id} to graph or remove it"
            })

    # RULE 3: Detect cycles (DAG constraint)
    cycle = _detect_cycle(nodes)
    if cycle:
        cycle_str = " → ".join(cycle)
        violations.append({
            "wf_code": wf_code,
            "violation": f"Cycle detected: {cycle_str}",
            "severity": "CRITICAL",
            "fix": "Remove cycle-causing edge to make graph acyclic (DAG)"
        })

    # RULE 4: Validate all next references point to existing nodes
    for node_id, node_def in nodes.items():
        next_map = node_def.get("next", {})
        if isinstance(next_map, dict):
            for condition, target in next_map.items():
                if target not in nodes:
                    violations.append({
                        "wf_code": wf_code,
                        "node": node_id,
                        "violation": f"Invalid next reference: {target} (condition={condition})",
                        "severity": "CRITICAL",
                        "fix": f"Add {target} to nodes or fix next reference"
                    })

    # RULE 5: EXIT nodes must be terminal (no outbound edges)
    for node_id, node_def in nodes.items():
        node_type = node_def.get("type")
        if node_type == "EXIT":
            next_map = node_def.get("next")
            if next_map:
                violations.append({
                    "wf_code": wf_code,
                    "node": node_id,
                    "violation": "EXIT node has outbound edges (next field present)",
                    "severity": "CRITICAL",
                    "fix": f"Remove next field from {node_id} (EXIT must be terminal)"
                })

    # RULE 6: Validate CC nodes reference existing CC artifacts
    # (FQDN syntax enforced by parse phase - this validator checks graph structure only)
    artifacts_by_fqdn = compilation_context.get("artifacts_by_fqdn", {})

    for node_id, node_def in nodes.items():
        node_type = node_def.get("type")
        if node_type == "CC":
            cc_code = node_def.get("code")
            if not cc_code:
                violations.append({
                    "wf_code": wf_code,
                    "node": node_id,
                    "violation": "CC node missing 'code' field",
                    "severity": "CRITICAL",
                    "fix": f"Add code field to {node_id} (CC artifact code)"
                })
            elif cc_code not in artifacts_by_fqdn:
                # Try to find with namespace prefix
                found = any(
                    fqdn.endswith(f"::{cc_code}")
                    for fqdn in artifacts_by_fqdn.keys()
                )
                if not found:
                    violations.append({
                        "wf_code": wf_code,
                        "node": node_id,
                        "cc_code": cc_code,
                        "violation": f"CC not found in compilation graph: {cc_code}",
                        "severity": "CRITICAL",
                        "fix": f"Add {cc_code} artifact or fix code reference"
                    })

    return _build_result(violations, len(nodes))


def _find_reachable_nodes(start_node: str, nodes: dict) -> set:
    """
    Find all nodes reachable from start_node via BFS.

    Args:
        start_node: Starting node ID
        nodes: nodes map

    Returns:
        Set of reachable node IDs
    """
    reachable = set()
    queue = [start_node]

    while queue:
        node_id = queue.pop(0)
        if node_id in reachable:
            continue

        reachable.add(node_id)

        if node_id not in nodes:
            continue

        node_def = nodes[node_id]
        next_map = node_def.get("next", {})

        if isinstance(next_map, dict):
            for target in next_map.values():
                if target not in reachable:
                    queue.append(target)

    return reachable


def _detect_cycle(nodes: dict) -> list[str] | None:
    """
    Detect cycle in graph using DFS with recursion stack.

    Args:
        nodes: nodes map

    Returns:
        List of node IDs forming cycle, or None if no cycle
    """
    visited = set()
    rec_stack = set()
    parent = {}

    def dfs(node_id: str, path: list[str]) -> list[str] | None:
        """DFS with cycle detection."""
        visited.add(node_id)
        rec_stack.add(node_id)

        if node_id not in nodes:
            rec_stack.remove(node_id)
            return None

        node_def = nodes[node_id]
        next_map = node_def.get("next", {})

        if isinstance(next_map, dict):
            for target in next_map.values():
                if target in rec_stack:
                    # Cycle found - reconstruct cycle path
                    cycle_start_idx = path.index(target)
                    return path[cycle_start_idx:] + [target]

                if target not in visited:
                    cycle = dfs(target, path + [target])
                    if cycle:
                        return cycle

        rec_stack.remove(node_id)
        return None

    # Try DFS from each unvisited node
    for node_id in nodes.keys():
        if node_id not in visited:
            cycle = dfs(node_id, [node_id])
            if cycle:
                return cycle

    return None


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
