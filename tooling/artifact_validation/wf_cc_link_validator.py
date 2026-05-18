from pgs_compiler.tooling.artifact_validation.wf_cc_link_rules import (
    rule_cc_exists,
    rule_result_status_alignment,
    rule_no_silent_drop,
)


def _extract_cc_allowed_result_status(cc: dict) -> set[str]:
    """
    Authoritative extraction of CC-visible result_status values.

    Contract rule:
    - Capability Contracts must explicitly declare which result_status
      values are exposed to workflows.
    - This declaration lives in:
          core.result_status_contract.allowed
    - Absence means: CC exposes NO branchable result_status values.
    """

    core = cc.get("core", {})
    contract = core.get("result_status_contract")

    if contract is None:
        return set()

    allowed = contract.get("allowed")
    if not isinstance(allowed, list):
        raise ValueError(
            "Invalid capability contract: "
            "core.result_status_contract.allowed must be a list"
        )

    return set(allowed)


def run_wf_cc_link_validation(
    workflows: dict[str, dict],
    capability_contracts: dict[str, dict],
) -> None:
    """
    Compiler Phase: WF-CC Link Validation

    Validates that workflows and capability contracts agree at their interface.

    Enforcement rules:
    - Workflow may only branch on result_status values explicitly exposed
      by the capability contract.
    - Capability contracts are NOT assumed to expose backend semantics
      unless declared.
    - Validation is silent on success and fail-fast on violation.

    This phase performs NO mutation and has NO side effects.
    """

    for wf_code, wf in workflows.items():
        core = wf.get("core", {})
        nodes = core.get("nodes", {})

        for node_code, node in nodes.items():
            if node.get("type") != "CC":
                continue

            cc_code = node.get("code")
            next_map = node.get("next", {})

            # Rule 1 - CC must exist
            rule_cc_exists(wf_code, cc_code, capability_contracts)

            cc = capability_contracts[cc_code]

            # Authoritative CC-visible result_status values
            cc_results = _extract_cc_allowed_result_status(cc)

            # Workflow-declared branches
            wf_branches = set(next_map.keys())

            # Rule 2 - WF branches <= CC exposed result_status
            rule_result_status_alignment(
                wf_code,
                cc_code,
                wf_branches,
                cc_results,
            )

            # Rule 3 - No silent drops (CC exposes results WF ignores)
            rule_no_silent_drop(
                wf_code,
                cc_code,
                wf_branches,
                cc_results,
            )
