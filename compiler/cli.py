"""
CLI entry point for trad-compiler.

Scope: PLATFORM ARTIFACTS ONLY (conventional, non-PGS)

Design:
- Platform scope only
- STRUCTURE-driven (STRUCTURE_BUILD_PLATFORM_CONFIG_V0)
- Conversion boundary: Adapts PGS artifacts to traditional compiler format
- Integrity Guards: Enforces consolidated STRUCTURE usage
- AUTHORITATIVE PIPELINE: DISCOVER -> PARSE -> NORMALIZE -> VALIDATE -> ASSERT -> MATERIALIZE -> CONFORMANCE_GENERATE
- Terminal Phase: CONFORMANCE_GENERATE (Phase 8) - outputs JSON test data
- Execution belongs in pgs_runtime, NOT in compiler

ARCHITECTURAL INVARIANT:
- Compiler MUST NOT import: execution, runtime, omnibachi
- Compiler is PURE: parse, validate, assert, materialize
- Compiler outputs: JSON artifacts ONLY
"""

import sys
from pathlib import Path
from typing import Any, List

import click

from pgs_compiler.compiler.atoms import (
    PhaseStatus,
    CompilerError,
)
from pgs_compiler.compiler.phases import (
    materialize_phase,
    parse_phase,
    validate_phase,
    validate_test_data_phase,
    verify_phase,
    conformance_generate_phase,
)
from pgs_compiler.compiler.phases.discover_structure import discover_structure_phase
from pgs_compiler.compiler.phases.assert_executor import execute_assert_phase
from pgs_compiler.compiler.structure_loader import FORBIDDEN_STRUCTURE


def assert_structure_integrity(structure_code: str) -> None:
    """
    Verify build anchor is not using legacy fragmented structure.
    """
    if structure_code in FORBIDDEN_STRUCTURE:
        raise RuntimeError(
            f"LEGACY BUILD ATTEMPTED: '{structure_code}' is forbidden.\n"
            f"The compiler now requires consolidated master artifacts."
        )


@click.command()
@click.option(
    "--phase",
    "-p",
    type=click.Choice(
        ["discover", "parse", "validate", "assert", "materialize", "conformance", "verify", "all"],
        case_sensitive=False,
    ),
    default="all",
    help="Run specific phase (default: all)",
)
@click.option(
    "--structure",
    type=str,
    multiple=True,
    help="STRUCTURE artifact code(s) (e.g. STRUCTURE_BUILD_PLATFORM_CONFIG_V0)",
)
@click.option(
    "--all-structures",
    is_flag=True,
    help="Compile all standard structures (Platform, Blockchain, AI Governance)",
)
@click.option(
    "--reproducible",
    "-r",
    is_flag=True,
    help="Enable reproducible builds (fixed timestamps, sorted outputs)",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Strict mode (fail on undeclared outputs)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose output (full error context)",
)
@click.option(
    "--skip-verify",
    is_flag=True,
    help="Skip verification phase",
)
def main(
    phase: str,
    structure: tuple,
    all_structures: bool,
    reproducible: bool,
    strict: bool,
    verbose: bool,
    skip_verify: bool,
) -> None:
    """
    Traditional compiler for platform and domain artifacts.
    """
    structures = list(structure)

    if all_structures:
        structures = [
            "STRUCTURE_BUILD_PLATFORM_CONFIG_V0",
            "STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0",
            "STRUCTURE_BUILD_AI_GOVERNANCE_CONFIG_V0",
        ]
    elif not structures:
        # Default to platform if nothing specified
        structures = ["STRUCTURE_BUILD_PLATFORM_CONFIG_V0"]

    click.echo(f"🚀 Starting build for {len(structures)} structure(s)")
    click.echo()

    success_count = 0
    fail_count = 0

    for struct_code in structures:
        try:
            agg_type = _get_aggregation_type(struct_code)
            if agg_type == "VOCABULARY":
                _run_vocabulary_aggregate(struct_code, verbose=verbose)
            elif agg_type:
                raise ValueError(f"Unknown aggregation_type '{agg_type}' in {struct_code}")
            else:
                _run_compile(
                    struct_code,
                    phase=phase,
                    reproducible=reproducible,
                    strict=strict,
                    verbose=verbose,
                    skip_verify=skip_verify
                )
            success_count += 1
        except CompilerError as e:
            click.echo(f"❌ Build failed for {struct_code}: {e.format(verbose=verbose)}", err=True)
            fail_count += 1
        except Exception as e:
            click.echo(f"❌ Build failed for {struct_code}: {e}", err=True)
            fail_count += 1

    click.echo("=" * 40)
    click.echo(f"🏁 Build Summary: {success_count} succeeded, {fail_count} failed")
    
    if fail_count > 0:
        sys.exit(1)


def _run_compile(
    structure: str,
    phase: str,
    reproducible: bool,
    strict: bool,
    verbose: bool,
    skip_verify: bool,
) -> None:
    """Run compilation for a single structure."""
    
    # Validate structure artifact code
    if not structure.startswith("STRUCTURE_BUILD_"):
        click.echo(f"❌ Invalid STRUCTURE artifact: {structure}", err=True)
        click.echo("   Must start with 'STRUCTURE_BUILD_'", err=True)
        raise ValueError(f"Invalid structure code: {structure}")

    # BUILD START ASSERTION: Integrity check
    try:
        assert_structure_integrity(structure)
    except RuntimeError as e:
        click.echo(f"❌ {e}", err=True)
        raise

    # Load STRUCTURE artifact to get configuration
    from pgs_compiler.compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots

    try:
        structure_config = load_structure_artifact(structure, get_bootstrap_search_roots())
    except Exception as e:
        click.echo(f"❌ Failed to load STRUCTURE artifact {structure}: {e}", err=True)
        raise

    phase = phase.lower()

    # Determine build scope from STRUCTURE
    artifact_discovery = structure_config.get("artifact_discovery", {})
    search_layers = artifact_discovery.get("search_layers", [])
    build_scope = "domains" if "DOMAINS" in search_layers else "platform"

    click.echo(f"🔨 Compiling  {build_scope} ..\n")
    click.echo(f"   STRUCTURE: {structure}")
    click.echo(f"   Phase: {phase}")
    click.echo(f"   Output: Federated (layer-specific)")
    click.echo()

    # --- Phase 1: DISCOVER ---
    click.echo("🔍 Phase 1: Discovery...")
    discover_result = discover_structure_phase(structure)
    _report_phase("DISCOVER", discover_result, verbose)

    if discover_result.status == PhaseStatus.FAILED:
        raise RuntimeError(f"Build failed at discovery phase for {structure}")

    discovered_artifacts = discover_result.outputs["discovered_artifacts"]
    skipped_artifacts = discover_result.outputs.get("skipped_artifacts", [])
    layer_category_map = discover_result.outputs.get("layer_category_map", {})
    is_domain_build = discover_result.outputs.get("is_domain_build", False)
    click.echo(f"   ✅ Discovered: {len(discovered_artifacts)} artifacts")
    click.echo()

    if phase == "discover":
        click.echo("✅ Discovery complete (phase isolation mode)")
        return

    # --- Phase 2: PARSE & Phase 3: NORMALIZE ---
    # (Note: Current parse_phase implements both PARSE and NORMALIZE roles)
    click.echo("📖 Phase 2 & 3: Parse & Normalize...")
    parse_result = parse_phase(discovered_artifacts)
    _report_phase("PARSE", parse_result, verbose)

    if parse_result.status == PhaseStatus.FAILED:
        raise RuntimeError(f"Build failed at parse phase for {structure}")

    parsed_artifacts = parse_result.outputs["parsed_artifacts"]
    click.echo(f"   ✅ Parsed & Normalized: {len(parsed_artifacts)} artifacts")
    click.echo()

    if phase == "parse":
        click.echo("✅ Parse & Normalize complete (phase isolation mode)")
        return

    # --- Phase 4: VALIDATE (Schema & CT-IR) ---
    click.echo("✓ Phase 4: Validate...")
    validate_result = validate_phase(parsed_artifacts)
    _report_phase("VALIDATE", validate_result, verbose)

    if validate_result.status == PhaseStatus.FAILED:
        raise RuntimeError(f"Build failed at validation phase for {structure}")

    validated_artifacts = validate_result.outputs["validated_artifacts"]
    click.echo(f"   ✅ Validated: {len(validated_artifacts)} artifacts")
    click.echo()

    if phase == "validate":
        click.echo("✅ Validation complete (phase isolation mode)")
        return

    # --- Phase 5: ASSERT (Constitutional Enforcement) ---
    click.echo("⚖️  Phase 5: Assertion...")

    assert_artifacts = [
        a for a in validated_artifacts
        if a.get("frontmatter", {}).get("artifact_kind") == "ASSERT"
    ]

    # Sort by enforcement order (meta-assertions run first)
    # Meta-assertions have enforcement.order: 1, regular assertions default to 999
    def get_enforcement_order(assert_artifact):
        enforcement = assert_artifact.get("frontmatter", {}).get("enforcement", {})
        return enforcement.get("order", 999)

    assert_artifacts = sorted(assert_artifacts, key=get_enforcement_order)

    # PRE-COMPUTE STRUCTURAL ANALYSIS (Inversion of Control)
    # Compiler builds complete structural context BEFORE registry evaluates rules
    click.echo("   🔧 Pre-computing structural analysis...")

    from pgs_compiler.compiler.validators import (
        ct_validate_wf_execution_graph,
        ct_validate_cc_binding,
        ct_validate_cc_no_chaining,
        ct_validate_cc_no_missing_dependencies,
        ct_validate_cc_no_unused_outputs,
        ct_validate_cc_inputs_satisfied,
        ct_validate_wf_binding_surface,
    )

    # Initialize compilation context with minimal data for validators
    base_context = {
        "artifacts_by_fqdn": {a["fqdn_id"]: a for a in validated_artifacts},
        "structure_config": structure_config,
        "artifacts": validated_artifacts
    }

    # Pre-compute structural results per artifact
    wf_execution_graphs = {}
    cc_bindings = {}
    cc_chaining = {}
    cc_dependencies = {}
    cc_unused_outputs = {}
    cc_inputs_satisfied = {}
    wf_binding_surface = {}

    for artifact in validated_artifacts:
        fqdn = artifact["fqdn_id"]
        artifact_type = artifact.get("artifact_type")

        if artifact_type == "WF":
            wf_execution_graphs[fqdn] = ct_validate_wf_execution_graph.execute(artifact, base_context)
            cc_dependencies[fqdn] = ct_validate_cc_no_missing_dependencies.execute(artifact, base_context)
            wf_binding_surface[fqdn] = ct_validate_wf_binding_surface.execute(artifact, base_context)
            cc_unused_outputs[fqdn] = ct_validate_cc_no_unused_outputs.execute(artifact, base_context)
            cc_inputs_satisfied[fqdn] = ct_validate_cc_inputs_satisfied.execute(artifact, base_context)

        elif artifact_type == "CC":
            cc_bindings[fqdn] = ct_validate_cc_binding.execute(artifact, base_context)
            cc_chaining[fqdn] = ct_validate_cc_no_chaining.execute(artifact, base_context)

    # Build complete, immutable compilation context
    compilation_context = {
        # Core data (read-only)
        "artifacts_by_fqdn": base_context["artifacts_by_fqdn"],
        "structure_config": structure_config,
        "artifacts": validated_artifacts,

        # Layer category information (STRUCTURE-driven)
        "layer_category_map": layer_category_map,
        "is_domain_build": is_domain_build,

        # Structural analysis results (pre-computed, read-only)
        "wf_execution_graphs": wf_execution_graphs,
        "cc_bindings": cc_bindings,
        "cc_chaining": cc_chaining,
        "cc_dependencies": cc_dependencies,
        "cc_unused_outputs": cc_unused_outputs,
        "cc_inputs_satisfied": cc_inputs_satisfied,
        "wf_binding_surface": wf_binding_surface,
    }

    click.echo(f"   ✅ Pre-computed: {len(wf_execution_graphs)} WF graphs, {len(cc_bindings)} CC bindings")

    try:
        assert_result = execute_assert_phase(assert_artifacts, compilation_context)
        _report_phase("ASSERT", assert_result, verbose)
        click.echo(f"   ✅ Assertions: {assert_result.outputs['assert_count']} executed")

        # Display warnings if any (dev mode)
        warnings = assert_result.outputs.get("warnings", [])
        if warnings:
            click.echo(f"   ⚠️  Warnings: {len(warnings)} governance issues (dev mode)")
            for warning in warnings:
                click.echo(f"      - {warning.get('violation') or warning.get('message', 'Unknown warning')}")
                if verbose and "fix" in warning:
                    click.echo(f"        Fix: {warning['fix']}")

        click.echo()
    except CompilerError as e:
        click.echo(f"❌ Assertion failure: {e.message}", err=True)
        if e.context and verbose:
            import json
            click.echo("   Context:", err=True)
            click.echo(json.dumps(e.context, indent=2), err=True)
        raise

    if phase == "assert":
        click.echo("✅ Assertion complete (phase isolation mode)")
        return

    # --- Phase 6: MATERIALIZE ---
    click.echo("💾 Phase 6: Materialize...")
    materialize_result = materialize_phase(validated_artifacts, structure=structure_config)
    _report_phase("MATERIALIZE", materialize_result, verbose)

    if materialize_result.status == PhaseStatus.FAILED:
        raise RuntimeError(f"Build failed at materialization phase for {structure}")

    materialized_paths = materialize_result.outputs["materialized_paths"]
    click.echo(f"   ✅ Materialized: {len(materialized_paths)} artifacts")
    click.echo()

    if phase == "materialize":
        click.echo("✅ Materialization complete (phase isolation mode)")
        return

    # --- Phase 7: VALIDATE TEST_DATA ---
    if phase in ["conformance", "all"]:
        click.echo("🔍 Phase 7: Validate TEST_DATA...")
        validate_td_result = validate_test_data_phase(validated_artifacts)
        _report_phase("VALIDATE_TEST_DATA", validate_td_result, verbose)

        if validate_td_result.status == PhaseStatus.FAILED:
            raise RuntimeError(f"Build failed at TEST_DATA validation phase for {structure}")

        validated_td_count = validate_td_result.outputs["validated_test_data"]
        if validated_td_count > 0:
            click.echo(f"   ✅ Validated: {validated_td_count} TEST_DATA artifacts")
        click.echo()

    # --- Phase 8: CONFORMANCE (TERMINAL COMPILER PHASE) ---
    # Compiler generates conformance test data (JSON artifacts)
    # Execution happens in pgs_runtime, NOT here
    if phase in ["conformance", "all"]:
        click.echo("🔍 Phase 8: Conformance Generate (Terminal Compiler Phase)...")
        conf_gen_result = conformance_generate_phase(validated_artifacts, structure=structure_config)
        _report_phase("CONFORMANCE_GENERATE", conf_gen_result, verbose)

        if conf_gen_result.status == PhaseStatus.FAILED:
            raise RuntimeError(f"Build failed at conformance generation phase for {structure}")

        generated_tests = conf_gen_result.outputs["generated_tests"]
        click.echo(f"   ✅ Generated: {len(generated_tests)} test cases from TEST_DATA")

        if verbose:
            test_data_fqdns = sorted(list(set(t["test_data_source"] for t in generated_tests)))
            for td_fqdn in test_data_fqdns:
                case_count = sum(1 for t in generated_tests if t["test_data_source"] == td_fqdn)
                click.echo(f"      - {td_fqdn} ({case_count} cases)")

        click.echo()
        click.echo("   ℹ️  Conformance test execution belongs in pgs_runtime")
        click.echo()

    # --- Phase 9: VERIFY ---
    if not skip_verify and phase in ["verify", "all"]:
        click.echo("🔎 Phase 9: Verify...")
        verify_result = verify_phase(
            materialized_paths,
            structure_config,
            original_artifacts=validated_artifacts,
            strict=strict,
            check_roundtrip=True,
        )
        _report_phase("VERIFY", verify_result, verbose)

        if verify_result.status == PhaseStatus.FAILED:
            raise RuntimeError(f"Build failed at verification phase for {structure}")

        click.echo("   ✅ Verification passed (including roundtrip)")
        click.echo()

    # Success
    click.echo(f"✅ Build complete for {structure}!")
    click.echo(f"\n{60*'='}\n")


def _get_aggregation_type(structure_code: str) -> str | None:
    """
    Return the aggregation_type declared in a STRUCTURE artifact, or None.

    Aggregation structures (Phase Type B) have an `aggregation_type` field
    and must NOT be routed through _run_compile().
    """
    from pgs_compiler.compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots
    try:
        config = load_structure_artifact(structure_code, get_bootstrap_search_roots())
        return config.get("aggregation_type") or None
    except Exception:
        return None


def _run_vocabulary_aggregate(structure_code: str, verbose: bool) -> None:
    """
    Run the federated vocabulary aggregation phase (Phase Type B).

    Consumes declared output surfaces from all contributing domain structures
    and produces vocabulary_symbols.json and vocabulary_semantic_index.json.
    Requires all Phase Type A builds to have completed first.
    """
    click.echo(f"📚 Vocabulary Aggregation — {structure_code}")
    click.echo()

    from pgs_compiler.compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots
    try:
        aggregate_config = load_structure_artifact(structure_code, get_bootstrap_search_roots())
    except Exception as e:
        raise RuntimeError(f"Failed to load aggregation STRUCTURE {structure_code}: {e}") from e

    click.echo(f"   STRUCTURE: {structure_code}")
    click.echo(f"   Type: VOCABULARY aggregation (Phase Type B)")
    click.echo()

    from pgs_governance.structure.structure.resolution import paths as path_registry, bootstrap
    from pgs_governance.implementation.vocabulary.builder.contract import VocabularyContract
    from pgs_governance.implementation.vocabulary.builder.orchestrator import VocabularyOrchestrator

    bootstrap()

    try:
        vocab_contract = VocabularyContract.from_aggregate_structure(path_registry, aggregate_config)
    except Exception as e:
        raise RuntimeError(f"Failed to build vocabulary contract: {e}") from e

    vocab_logger = (lambda msg: click.echo(f"   [vocab] {msg}")) if verbose else (lambda msg: None)

    vocab_orchestrator = VocabularyOrchestrator(
        contract=vocab_contract,
        read_file=lambda p: p.read_text(encoding="utf-8"),
        write_file=lambda p, c: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(c, encoding="utf-8")),
        logger=vocab_logger,
    )

    if verbose:
        click.echo("   Source directories:")
        for label, dirs in [
            ("capability_transforms", vocab_contract.capability_transforms_dirs),
            ("capability_side_effects", vocab_contract.capability_side_effects_dirs),
            ("capability_contracts", vocab_contract.capability_contracts_dirs),
            ("workflows", vocab_contract.workflows_dirs),
            ("intents", vocab_contract.intents_dirs),
        ]:
            for d in dirs:
                exists = "✓" if d.exists() else "✗ (missing)"
                click.echo(f"      [{label}] {d} {exists}")
        click.echo()

    vocab_result = vocab_orchestrator.run()

    if not vocab_result.success:
        for error in vocab_result.errors:
            click.echo(f"   ❌ {error}", err=True)
        raise RuntimeError(f"Vocabulary aggregation failed — ensure all domain builds completed first")

    click.echo(f"   ✅ vocabulary_symbols.json → {vocab_contract.vocabulary_symbols_path}")
    click.echo(f"   ✅ vocabulary_semantic_index.json → {vocab_contract.vocabulary_semantic_index_path}")
    click.echo()
    click.echo(f"✅ Vocabulary aggregation complete!")
    click.echo(f"\n{60*'='}\n")


def _report_phase(phase_name: str, result: Any, verbose: bool) -> None:
    """Report phase errors if any."""
    if not result.errors:
        return

    click.echo(f"   ⚠️  {len(result.errors)} error(s) in {phase_name} phase:", err=True)

    for error in result.errors:
        click.echo(f"   {error.format(verbose=verbose)}", err=True)


if __name__ == "__main__":
    main()
