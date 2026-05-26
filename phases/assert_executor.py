"""
ASSERT Phase Executor: Constitutional Invariant Enforcement.

Executes all ASSERT artifacts using static handler registry.
Violations cause immediate build failure (no warnings, no bypass).

ARCHITECTURAL INVARIANT:
- NO dynamic imports (importlib forbidden)
- ALL handlers resolved via static HANDLER_REGISTRY
- Handler existence validated at compile time
- Any missing handler = compile failure
"""

from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.atoms import CompilerError, ErrorCode, PhaseStatus, PhaseResult, PhaseMetrics
from pgs_governance.implementation.assertions.handlers import HANDLER_REGISTRY


def execute_assert_phase(
    assert_artifacts: list[dict[str, Any]],
    compilation_context: dict[str, Any]
) -> PhaseResult:
    """
    Execute all ASSERT artifacts in enforcement order.
    Each artifact declares its implementation.module; the handler is resolved
    from the static HANDLER_REGISTRY and invoked with the immutable context.
    """
    all_violations = []
    all_warnings = []
    executed_assertions = []

    for assert_artifact in assert_artifacts:
        # Extract artifact_code (new field name)
        artifact_code = assert_artifact.get("frontmatter", {}).get("artifact_code")

        if not artifact_code:
            raise CompilerError(
                code=ErrorCode.E703_MALFORMED_ASSERT,
                message=f"ASSERT artifact missing 'artifact_code' in frontmatter: {assert_artifact.get('fqdn_id')}",
                phase="ASSERT",
                fqdn_id=assert_artifact.get("fqdn_id")
            )

    # Get build context from compilation_context (STRUCTURE-driven)
    is_domain_build = compilation_context.get("is_domain_build", False)
    layer_category_map = compilation_context.get("layer_category_map", {})

    # Execute all assertions (with scope checking)
    for assert_artifact in assert_artifacts:
        artifact_code = assert_artifact["frontmatter"]["artifact_code"]

        # Scope-aware execution: Check if assertion applies to current build context
        scope = assert_artifact.get("frontmatter", {}).get("scope", {})
        applies_to = scope.get("applies_to", [])

        if applies_to:
            # VALIDATE scope targets (fail hard on invalid)
            valid_scope_targets = {"PLATFORM"} | set(layer_category_map.keys())

            for scope_target in applies_to:
                if scope_target not in valid_scope_targets:
                    raise CompilerError(
                        code=ErrorCode.E703_MALFORMED_ASSERT,
                        message=f"Invalid scope target in assertion: {scope_target}",
                        phase="ASSERT",
                        fqdn_id=assert_artifact["fqdn_id"],
                        context={
                            "assertion": artifact_code,
                            "invalid_target": scope_target,
                            "valid_targets": sorted(valid_scope_targets),
                            "fix": "Update scope.applies_to to use valid layer codes from STRUCTURE_LAYER_AUTHORITY_V0"
                        }
                    )
            # Assertion has scope declaration - check if it applies
            should_execute = False

            for scope_target in applies_to:
                if scope_target == "PLATFORM" and not is_domain_build:
                    # Platform-only assertion, no domain layers present
                    should_execute = True
                    break
                elif scope_target in layer_category_map:
                    # Domain-specific assertion, check if that layer is present
                    should_execute = True
                    break

            if not should_execute:
                # Skip assertion - doesn't apply to this build context
                continue

        # Execute ASSERT using FQDN-driven resolution
        result = _execute_single_assert(assert_artifact, compilation_context)
        executed_assertions.append(artifact_code)

        # Extract violations and warnings from result
        violations = result.get("violations", [])
        warnings = result.get("warnings", [])

        if violations:
            all_violations.extend(violations)
        if warnings:
            all_warnings.extend(warnings)

    # Constitutional enforcement: violations = build failure
    if all_violations:
        raise CompilerError(
            code=ErrorCode.E701_ASSERTION_FAILURE,
            message=f"Assertion violations detected: {len(all_violations)} total",
            phase="ASSERT",
            context={"violations": all_violations}
        )

    return PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={
            "violations": [],
            "warnings": all_warnings,
            "executed_assertions": executed_assertions,
            "assert_count": len(assert_artifacts)
        },
        metrics=PhaseMetrics(items_processed=len(assert_artifacts))
    )


def _execute_single_assert(
    assert_artifact: dict[str, Any],
    context: dict[str, Any]
) -> dict[str, Any]:
    """
    Execute a single ASSERT artifact using static handler registry.

    Pure architecture:
    - Read implementation.module from ASSERT artifact
    - Look up handler in static HANDLER_REGISTRY (no importlib)
    - Execute handler(artifacts, compilation_context)
    - Return result dict with violations

    CRITICAL: Handler must exist in HANDLER_REGISTRY or compile fails.
    No dynamic discovery. No runtime import. Pure, explicit, validated.
    """
    artifact_code = assert_artifact["frontmatter"]["artifact_code"]
    fqdn_id = assert_artifact.get("fqdn_id")

    # Pass current assert artifact to handler (for enforcement level checking)
    context["current_assert_artifact"] = assert_artifact

    readonly_context = MappingProxyType(context)

    # Extract implementation binding
    implementation = assert_artifact["frontmatter"].get("implementation")

    if not implementation:
        raise CompilerError(
            code=ErrorCode.E703_MALFORMED_ASSERT,
            message=f"ASSERT artifact missing 'implementation' field: {artifact_code}",
            phase="ASSERT",
            fqdn_id=fqdn_id
        )

    module_path = implementation.get("module")

    if not module_path:
        raise CompilerError(
            code=ErrorCode.E703_MALFORMED_ASSERT,
            message=f"ASSERT implementation missing 'module': {artifact_code}",
            phase="ASSERT",
            fqdn_id=fqdn_id
        )

    # Validate handler FQDN is fully-qualified (must start with pgs_)
    if not module_path.startswith("pgs_"):
        raise CompilerError(
            code=ErrorCode.E703_MALFORMED_ASSERT,
            message=f"ASSERT handler must be fully-qualified (start with pgs_): {module_path}",
            phase="ASSERT",
            fqdn_id=fqdn_id
        )

    # Static registry lookup (NO importlib, NO dynamic discovery)
    handler_callable = HANDLER_REGISTRY.get(module_path)

    if not handler_callable:
        raise CompilerError(
            code=ErrorCode.E702_UNKNOWN_ASSERT,
            message=f"Handler not found in static registry: {module_path}",
            phase="ASSERT",
            fqdn_id=fqdn_id,
            context={
                "available_handlers": list(HANDLER_REGISTRY.keys()),
                "note": "Handler must be explicitly registered in pgs_governance.registry.handlers.__init__.py"
            }
        )

    # Execute handler
    # Handler signature: execute(artifacts: list[dict], compilation_context: dict) -> dict
    artifacts = readonly_context.get("artifacts", [])

    try:
        result = handler_callable(artifacts, readonly_context)
    except Exception as e:
        raise CompilerError(
            code=ErrorCode.E701_ASSERTION_FAILURE,
            message=f"ASSERT handler execution failed: {artifact_code}",
            phase="ASSERT",
            fqdn_id=fqdn_id,
            context={"error": str(e)}
        )

    return result


# ARCHITECTURAL ENFORCEMENT - Static Handler Registry
#
# All assertion logic lives in:
# - pgs_governance/registry/handlers/assert_*.py
#
# Handler resolution is PURE:
# - ASSERT artifact declares implementation.module (FQDN)
# - Static lookup in HANDLER_REGISTRY (no importlib)
# - No dynamic discovery, no runtime import
# - Missing handler = compile failure
#
# This enforces:
# - Explicit dependency graph (visible in code)
# - Compile-time validation (no runtime surprises)
# - Zero inference (protocol declares, code obeys)
#
# Adding new handler requires:
# 1. Create handler file in pgs_governance/registry/handlers/
# 2. Add explicit import to __init__.py
# 3. Add entry to HANDLER_REGISTRY
# 4. No shortcuts allowed
