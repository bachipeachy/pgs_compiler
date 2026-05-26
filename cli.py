"""
CLI entry point for PGS compiler.

Subcommands:
  build    — compile one or more STRUCTURE artifacts (S1–S9 pipeline)
  inspect  — query evidence_graph.json for a compiled structure

Pipeline: S1 EXTRACT → S2 CANONICALIZE → S3 SEMANTIC_ADDRESSING →
          S4 GOVERN → S5 CONSTRUCT → S6 PROJECT → S7 MATERIALIZE → S8 VERIFY → S9 ATTEST

Each stage is a pure function: State → State.

ARCHITECTURAL INVARIANT:
- Compiler MUST NOT import: execution, runtime, pgs_runtime
- Compiler is PURE: extract, canonicalize, address, govern, construct, project, materialize, verify, attest
- Compiler outputs: JSON artifacts ONLY
"""

import sys
from typing import Any

import click

from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.stages import (
    s1_extract,
    s2_canonicalize,
    s3_semantic_addressing,
    s4_govern,
    s5_construct,
    s6_project,
    s7_materialize,
    s8_verify,
    s9_attest,
)
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.structure_loader import FORBIDDEN_STRUCTURE


def assert_structure_integrity(structure_code: str) -> None:
    """
    Verify build anchor is not using legacy fragmented structure.
    """
    if structure_code in FORBIDDEN_STRUCTURE:
        raise RuntimeError(
            f"LEGACY BUILD ATTEMPTED: '{structure_code}' is forbidden.\n"
            f"The compiler now requires consolidated master artifacts."
        )


@click.group()
def cli() -> None:
    """PGS compiler — topology-native governance compilation."""
    pass


@cli.command()
@click.option(
    "--workspace",
    required=True,
    help="Absolute path to pgs_workspace root",
)
def build(workspace: str) -> None:
    """
    Full build: artifact sync, conformance tests, snapshot validation.

    Delegates to scripts/pgs_build.py:
      1. sync_protocol_snapshot.sh   (file movement)
      2. CT conformance tests        (correctness gate)
      3. snapshot_status.json        (written only on full pass)
    """
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parent / "scripts" / "pgs_build.py"
    if not script.exists():
        click.echo(f"Error: pgs_build.py not found at {script}", err=True)
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, str(script), "--workspace", workspace],
        check=False,
    )
    sys.exit(result.returncode)


@cli.command()
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
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose output (full error context, stage metadata)",
)
def compile(
    structure: tuple,
    all_structures: bool,
    verbose: bool,
) -> None:
    """
    Compile STRUCTURE artifacts through the S1–S8 pipeline.

    Chains 8 pure stages: EXTRACT → CANONICALIZE → SEMANTIC_ADDRESSING →
    GOVERN → CONSTRUCT → PROJECT → MATERIALIZE → VERIFY.
    """
    structures = list(structure)

    if all_structures:
        structures = [
            "STRUCTURE_BUILD_PLATFORM_CONFIG_V0",
            "STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0",
            "STRUCTURE_BUILD_AI_GOVERNANCE_CONFIG_V0",
        ]
    elif not structures:
        structures = ["STRUCTURE_BUILD_PLATFORM_CONFIG_V0"]

    click.echo(f"Starting PGS build for {len(structures)} structure(s)")
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
                _run_compile(struct_code, verbose=verbose)
            success_count += 1
        except CompilerError as e:
            click.echo(f"Build failed for {struct_code}: {e.format(verbose=verbose)}", err=True)
            fail_count += 1
        except Exception as e:
            click.echo(f"Build failed for {struct_code}: {e}", err=True)
            fail_count += 1

    click.echo("=" * 40)
    click.echo(f"Build Summary: {success_count} succeeded, {fail_count} failed")

    if fail_count > 0:
        sys.exit(1)


@cli.command()
@click.option(
    "--structure",
    type=str,
    required=True,
    help="STRUCTURE artifact code (e.g. STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0)",
)
@click.option(
    "--artifact",
    type=str,
    default=None,
    help="FQDN — show artifact identity, events, and causality chain",
)
@click.option(
    "--upstream",
    type=str,
    default=None,
    help="FQDN — walk causality chain upstream from this artifact",
)
@click.option(
    "--family",
    type=str,
    default=None,
    help="EventFamily name (e.g. CONSTRUCTION) — list all events in this family",
)
@click.option(
    "--downstream",
    type=str,
    default=None,
    help="FQDN — walk causality chain downstream from this artifact",
)
def inspect(
    structure: str,
    artifact: str | None,
    upstream: str | None,
    family: str | None,
    downstream: str | None,
) -> None:
    """
    Query evidence_graph.json for a compiled structure.

    Exactly one of --artifact, --upstream, --downstream, or --family is required.
    Reads from the materialized evidence_graph.json — does not recompile.
    """
    # Validate: exactly one query flag required
    flags = [f for f in (artifact, upstream, downstream, family) if f is not None]
    if len(flags) == 0:
        click.echo(
            "Error: provide exactly one of --artifact, --upstream, --downstream, or --family",
            err=True,
        )
        sys.exit(1)
    if len(flags) > 1:
        click.echo(
            "Error: --artifact, --upstream, --downstream, and --family are mutually exclusive",
            err=True,
        )
        sys.exit(1)

    # Resolve evidence_graph.json path
    try:
        evidence_graph_path = _resolve_evidence_graph_path(structure)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Load via consumer contract
    from pgs_compiler.visualization.consumers.evidence_reader import load_evidence_graph
    from pgs_compiler.visualization.consumers.evidence_projection import EvidenceProjection

    try:
        query = load_evidence_graph(evidence_graph_path)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error loading evidence_graph.json: {e}", err=True)
        sys.exit(1)

    projection = EvidenceProjection(query)

    # Dispatch
    if artifact is not None:
        _inspect_artifact(query, projection, artifact)
    elif upstream is not None:
        _inspect_upstream(query, projection, upstream)
    elif downstream is not None:
        _inspect_downstream(query, downstream)
    elif family is not None:
        _inspect_family(query, family)


# ---------------------------------------------------------------------------
# Build pipeline helpers
# ---------------------------------------------------------------------------

def _run_compile(structure: str, verbose: bool) -> None:
    """
    Run PGS compilation pipeline (S1-S8) for a single structure.

    Each stage is a pure function: State -> State.
    Pipeline halts on first stage with errors.
    """
    if not structure.startswith("STRUCTURE_BUILD_"):
        click.echo(f"Invalid STRUCTURE artifact: {structure}", err=True)
        raise ValueError(f"Invalid structure code: {structure}")

    assert_structure_integrity(structure)

    from pgs_compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots

    try:
        structure_config = load_structure_artifact(structure, get_bootstrap_search_roots())
    except Exception as e:
        raise RuntimeError(f"Failed to load STRUCTURE artifact {structure}: {e}") from e

    structure_config["structure_artifact_code"] = structure

    # Derive display label from structure code: STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0 → "blockchain"
    build_scope = structure.removeprefix("STRUCTURE_BUILD_").split("_CONFIG_")[0].lower()

    click.echo(f"PGS Compiling  {build_scope} ..")
    click.echo(f"   STRUCTURE: {structure}")
    click.echo()

    state = State.initial(structure_config)

    stages = [
        ("S1_EXTRACT", s1_extract),
        ("S2_CANONICALIZE", s2_canonicalize),
        ("S3_SEMANTIC_ADDRESSING", s3_semantic_addressing),
        ("S4_GOVERN", s4_govern),
        ("S5_CONSTRUCT", s5_construct),
        ("S6_PROJECT", s6_project),
        ("S7_MATERIALIZE", s7_materialize),
        ("S8_VERIFY", s8_verify),
        ("S9_ATTEST", s9_attest),
    ]

    for stage_name, stage_fn in stages:
        click.echo(f"   {stage_name}...")
        state = stage_fn(state)

        if verbose:
            for key, value in state.stage_metadata.items():
                click.echo(f"      {key}: {value}")

        if state.has_errors:
            click.echo(f"   {stage_name} failed with {len(state.errors)} error(s):", err=True)
            for error in state.errors:
                click.echo(f"      {error.format(verbose=verbose)}", err=True)
            raise RuntimeError(f"PGS build failed at {stage_name} for {structure}")

        if state.warnings:
            click.echo(f"      {len(state.warnings)} warning(s)")
            if verbose:
                for w in state.warnings:
                    click.echo(f"         {w.message}")

    click.echo()
    click.echo(f"   Trace events: {len(state.trace_events)}")
    click.echo(f"   Materialized: {len(state.materialized_paths)} artifacts")
    verified = state.stage_metadata.get("verified", False)
    attested = state.stage_metadata.get("attested", False)
    click.echo(f"   Verified: {verified}")
    click.echo(f"   Attested: {attested}")
    click.echo()
    click.echo(f"PGS build complete for {structure}!")
    click.echo(f"\n{60*'='}\n")


def _get_aggregation_type(structure_code: str) -> str | None:
    """
    Return the aggregation_type declared in a STRUCTURE artifact, or None.

    Aggregation structures (Phase Type B) have an `aggregation_type` field
    and must NOT be routed through _run_compile().
    """
    from pgs_compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots
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
    click.echo(f"Vocabulary Aggregation — {structure_code}")
    click.echo()

    from pgs_compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots
    try:
        aggregate_config = load_structure_artifact(structure_code, get_bootstrap_search_roots())
    except Exception as e:
        raise RuntimeError(f"Failed to load aggregation STRUCTURE {structure_code}: {e}") from e

    click.echo(f"   STRUCTURE: {structure_code}")
    click.echo(f"   Type: VOCABULARY aggregation (Phase Type B)")
    click.echo()

    from pgs_governance.implementation.structure.resolution import paths as path_registry, bootstrap
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
                exists = "Y" if d.exists() else "N (missing)"
                click.echo(f"      [{label}] {d} {exists}")
        click.echo()

    vocab_result = vocab_orchestrator.run()

    if not vocab_result.success:
        for error in vocab_result.errors:
            click.echo(f"   {error}", err=True)
        raise RuntimeError("Vocabulary aggregation failed — ensure all domain builds completed first")

    click.echo(f"   vocabulary_symbols.json -> {vocab_contract.vocabulary_symbols_path}")
    click.echo(f"   vocabulary_semantic_index.json -> {vocab_contract.vocabulary_semantic_index_path}")
    click.echo()
    click.echo("Vocabulary aggregation complete!")
    click.echo(f"\n{60*'='}\n")


# ---------------------------------------------------------------------------
# Inspect helpers
# ---------------------------------------------------------------------------

def _resolve_evidence_graph_path(structure_code: str) -> "Path":
    """
    Resolve the evidence_graph.json path for a given STRUCTURE artifact code.

    Uses the same path resolution contract as S7_MATERIALIZE:
      <evidence_projection_path>/<structure_id>/evidence_graph.json
    """
    from pathlib import Path
    from pgs_compiler.structure_loader import load_structure_artifact, get_bootstrap_search_roots
    from pgs_governance.implementation.structure.resolution.layer_resolver import LayerResolver
    from pgs_compiler.compiler.projections import get_structure_scope

    try:
        structure_config = load_structure_artifact(structure_code, get_bootstrap_search_roots())
    except Exception as e:
        raise RuntimeError(f"Failed to load STRUCTURE artifact {structure_code}: {e}") from e

    structure_config["structure_artifact_code"] = structure_code

    structure_id = get_structure_scope(structure_config)
    if not structure_id:
        raise RuntimeError(f"Unknown structure_id for {structure_code}")

    resolver = LayerResolver()
    try:
        evi_root = resolver.resolve_output_path("evidence_projection_path", "", structure_config)
    except Exception as e:
        raise RuntimeError(f"Failed to resolve evidence_projection_path: {e}") from e

    return Path(evi_root) / structure_id / "evidence_graph.json"


def _inspect_artifact(query: Any, projection: Any, fqdn: str) -> None:
    """
    Display artifact identity, compilation events, and causality chain.

    Output priority:
      1. Artifact identity
      2. Stage/family events for this artifact
      3. Upstream causality chain (root-first)
      4. Materialization lineage
    """
    # 1 — Identity
    click.echo()
    click.echo(click.style("Artifact", bold=True) + f": {click.style(fqdn, fg='cyan')}")
    click.echo(f"Structure: {query.structure_id}")
    click.echo()

    # 2 — Direct events for this artifact
    direct_events = [
        ev for ev in query.by_family("DISCOVERY")
        + query.by_family("TOPOLOGY")
        + query.by_family("CONSTRUCTION")
        + query.by_family("PROJECTION")
        + query.by_family("MATERIALIZATION")
        + query.by_family("VERIFICATION")
        + query.by_family("ADDRESSING")
        + query.by_family("GOVERNANCE")
        if ev.subject_fqdn == fqdn
    ]
    # Deduplicate by event_id (set() won't work — TraceEventDTO has a mutable dict field)
    seen_ids: set[int] = set()
    deduped: list[Any] = []
    for ev in sorted(direct_events, key=lambda e: e.event_id):
        if ev.event_id not in seen_ids:
            seen_ids.add(ev.event_id)
            deduped.append(ev)
    direct_events = deduped

    if direct_events:
        click.echo(click.style(f"Events ({len(direct_events)}):", bold=True))
        for ev in direct_events:
            _print_event_line(ev, indent=2)
        click.echo()
    else:
        click.echo(click.style("Events:", bold=True) + "  (none — FQDN not found in trace)")
        click.echo()

    # 3 — Causality chain
    chain = projection.artifact_provenance(fqdn)
    if chain:
        click.echo(click.style(f"Causality chain ({len(chain)} events, root-first):", bold=True))
        _print_event_chain(chain, highlight_fqdn=fqdn, indent=2)
        click.echo()
    else:
        click.echo(click.style("Causality chain:", bold=True) + "  (no causal ancestors)")
        click.echo()

    # 4 — Materialization
    written = [
        ev for ev in direct_events
        if ev.operation == "artifact_written" and "output_path" in ev.detail
    ]
    if written:
        click.echo(click.style("Materialized to:", bold=True))
        for ev in written:
            click.echo(f"  {ev.detail['output_path']}")
        click.echo()


def _inspect_upstream(query: Any, projection: Any, fqdn: str) -> None:
    """
    Walk and display the causality chain upstream from an artifact.

    Shows causal ancestors root-first, grouped by stage, with indentation.
    """
    click.echo()
    click.echo(click.style("Upstream causality for", bold=True) + f": {click.style(fqdn, fg='cyan')}")
    click.echo(f"Structure: {query.structure_id}")
    click.echo()

    chain = projection.artifact_provenance(fqdn)

    if not chain:
        click.echo("  (no causal ancestors — FQDN not found in trace or causality not wired)")
        return

    click.echo(click.style(f"Causal chain ({len(chain)} events, root-first):", bold=True))
    _print_event_chain_by_stage(chain, highlight_fqdn=fqdn)
    click.echo()


def _inspect_downstream(query: Any, fqdn: str) -> None:
    """
    Walk and display the causality chain downstream from an artifact.

    Finds all seed events where subject_fqdn == fqdn, then BFS-walks forward
    through CAUSALITY edges using query.downstream(), collecting all descendants.
    Output is grouped by stage, sorted by event_id.
    """
    click.echo()
    click.echo(click.style("Downstream causality for", bold=True) + f": {click.style(fqdn, fg='cyan')}")
    click.echo(f"Structure: {query.structure_id}")
    click.echo()

    # Find seed events — events whose subject is this artifact
    seed_events = [
        ev for ev in (
            query.by_family("DISCOVERY")
            + query.by_family("TOPOLOGY")
            + query.by_family("CONSTRUCTION")
            + query.by_family("PROJECTION")
            + query.by_family("MATERIALIZATION")
            + query.by_family("VERIFICATION")
            + query.by_family("ADDRESSING")
            + query.by_family("GOVERNANCE")
        )
        if ev.subject_fqdn == fqdn
    ]
    # Deduplicate seeds by event_id
    seen_ids: set[int] = set()
    seeds: list[Any] = []
    for ev in sorted(seed_events, key=lambda e: e.event_id):
        if ev.event_id not in seen_ids:
            seen_ids.add(ev.event_id)
            seeds.append(ev)

    if not seeds:
        click.echo("  (no events found — FQDN not in trace or causality not wired)")
        return

    # BFS forward through CAUSALITY edges
    visited: set[int] = set()
    frontier: list[Any] = list(seeds)
    all_descendants: list[Any] = []

    for seed in seeds:
        visited.add(seed.event_id)
        all_descendants.append(seed)

    while frontier:
        next_frontier: list[Any] = []
        for ev in frontier:
            children = query.downstream(ev.event_id)
            for child in children:
                if child.event_id not in visited:
                    visited.add(child.event_id)
                    all_descendants.append(child)
                    next_frontier.append(child)
        frontier = next_frontier

    all_descendants.sort(key=lambda e: e.event_id)

    click.echo(
        click.style(f"Downstream events ({len(all_descendants)} total, seed-first):", bold=True)
    )
    _print_event_chain_by_stage(all_descendants, highlight_fqdn=fqdn)
    click.echo()


def _inspect_family(query: Any, family_name: str) -> None:
    """
    List all events in an EventFamily, grouped by stage.
    """
    available = query.families()
    events = query.by_family(family_name)

    click.echo()
    if not events:
        click.echo(
            f"Family '{family_name}' not found. Available families: "
            + ", ".join(available)
        )
        return

    click.echo(
        click.style("Family", bold=True)
        + f": {click.style(family_name, fg='yellow')}  "
        + click.style(f"({len(events)} events)", dim=True)
    )
    click.echo(f"Structure: {query.structure_id}")
    click.echo()

    # Group by stage in first-seen order
    by_stage: dict[str, list[Any]] = {}
    for ev in sorted(events, key=lambda e: e.event_id):
        by_stage.setdefault(ev.stage, []).append(ev)

    for stage, stage_events in by_stage.items():
        click.echo(click.style(f"  {stage}", bold=True) + f"  ({len(stage_events)} events)")
        for ev in stage_events:
            _print_event_line(ev, indent=4)
        click.echo()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _print_event_line(ev: Any, indent: int = 2) -> None:
    """Print a single event as one terminal line."""
    prefix = " " * indent
    op = click.style(ev.operation, fg="green")
    stage_tag = click.style(f"[{ev.stage}/{ev.family}]", dim=True)
    subject = f"  {click.style(ev.subject_fqdn, fg='cyan')}" if ev.subject_fqdn else ""
    click.echo(f"{prefix}#{ev.event_id:<4}  {op}  {stage_tag}{subject}")


def _print_event_chain(events: list[Any], highlight_fqdn: str | None, indent: int = 2) -> None:
    """Print a flat causality chain, root-first, one event per line."""
    prefix = " " * indent
    for ev in events:
        is_subject = ev.subject_fqdn == highlight_fqdn
        op = click.style(ev.operation, fg="green" if not is_subject else "white", bold=is_subject)
        stage_tag = click.style(f"[{ev.stage}]", dim=True)
        family_tag = click.style(f"[{ev.family}]", dim=True)
        subject = (
            f"  {click.style(ev.subject_fqdn, fg='cyan', bold=is_subject)}"
            if ev.subject_fqdn else ""
        )
        marker = click.style(" ◀", fg="yellow") if is_subject else ""
        click.echo(f"{prefix}#{ev.event_id:<4}  {op}  {stage_tag} {family_tag}{subject}{marker}")


def _print_event_chain_by_stage(events: list[Any], highlight_fqdn: str | None = None) -> None:
    """Print a causality chain grouped by stage, with indentation per stage."""
    by_stage: dict[str, list[Any]] = {}
    stage_order: list[str] = []
    for ev in events:
        if ev.stage not in by_stage:
            stage_order.append(ev.stage)
        by_stage.setdefault(ev.stage, []).append(ev)

    for stage in stage_order:
        stage_events = by_stage[stage]
        click.echo(f"  {click.style(stage, bold=True)}  ({len(stage_events)} events)")
        for ev in stage_events:
            is_subject = ev.subject_fqdn == highlight_fqdn
            op = click.style(ev.operation, fg="green", bold=is_subject)
            family_tag = click.style(f"[{ev.family}]", dim=True)
            subject = (
                f"  {click.style(ev.subject_fqdn, fg='cyan', bold=is_subject)}"
                if ev.subject_fqdn else ""
            )
            marker = click.style(" ◀", fg="yellow") if is_subject else ""
            click.echo(f"    #{ev.event_id:<4}  {op}  {family_tag}{subject}{marker}")
        click.echo()


if __name__ == "__main__":
    cli()
