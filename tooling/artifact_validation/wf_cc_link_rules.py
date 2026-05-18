from pgs_compiler.tooling.artifact_validation.errors import (
    MissingCapabilityContract,
    UnknownResultStatus,
    UnhandledCapabilityOutcome,
)


def rule_cc_exists(wf_code: str, cc_code: str, cc_index: dict):
    if cc_code not in cc_index:
        raise MissingCapabilityContract(
            f"Workflow {wf_code} references unknown capability contract {cc_code}"
        )


def rule_result_status_alignment(
    wf_code: str,
    cc_code: str,
    wf_branches: set[str],
    cc_results: set[str],
):
    unknown = wf_branches - cc_results
    if unknown:
        raise UnknownResultStatus(
            f"Workflow {wf_code} references result_status {sorted(unknown)} "
            f"not declared by capability {cc_code}"
        )


def rule_no_silent_drop(
    wf_code: str,
    cc_code: str,
    wf_branches: set[str],
    cc_results: set[str],
):
    dropped = cc_results - wf_branches
    if dropped:
        raise UnhandledCapabilityOutcome(
            f"Workflow {wf_code} does not handle result_status {sorted(dropped)} "
            f"from capability {cc_code}"
        )
