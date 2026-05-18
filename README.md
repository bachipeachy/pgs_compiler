
# pgs_compiler

**Compiler pipeline and protocol tooling for Protocol-Governed Systems.**

This repository implements the build pipeline that transforms governed protocol source into compiled execution artifacts. It reads from `pgs_governance` and domain repos, applies multi-phase validation, and produces the immutable `protocol_snapshot/` consumed by the runtime.

> **New to PGS?** This is one of eight repositories in the Protocol-Governed Systems ecosystem.
> For orientation, architecture overview, and end-to-end execution, start at [pgs_workspace](https://github.com/bachipeachy/pgs_workspace).

---

## Responsibility

`pgs_compiler` owns the compiler layer of PGS:

- **Artifact discovery** — locates protocol artifacts via STRUCTURE_BUILD config declarations
- **Parse and validate** — deserializes YAML/JSON artifacts and checks schema conformance
- **Assertion evaluation** — runs invariant checks via registered assertion handlers
- **Materialization** — constructs execution topology, resolves bindings, seals step sequences
- **Snapshot sync** — publishes compiled artifacts to `pgs_workspace/protocol_snapshot/`

---

## Package Layout

```
compiler/           Compiler pipeline (discover → parse → validate → assert → materialize)
  atoms/            Pure functions (YAML parsing, schema validation, error formatting)
  phases/           Composable phase implementations
  schemas/          Typed artifact definitions
  validators/       Validation logic
  visualization/    Graph rendering for compiled artifacts
tooling/            Protocol tooling and supporting utilities
  artifact_validation/
  builder/
  protocol_validation/
  visualization/
  experimental/
scripts/            Operational scripts (build, sync, clean)
```

---

## Compiler Phase Types

| Phase Type | Name | Semantics |
|------------|------|-----------|
| Type A | Per-structure | Each domain structure compiled independently; outputs go to domain repo |
| Type B | Cross-structure aggregation | Runs after all Type A builds; aggregates across domains (e.g., vocabulary) |

---

## Usage

```bash
# Activate workspace venv
source /path/to/pgs_workspace/.venv/bin/activate

# Compile a domain structure (Type A)
python -m pgs_compiler.compiler.cli --structure STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0
python -m pgs_compiler.compiler.cli --structure STRUCTURE_BUILD_AI_GOVERNANCE_CONFIG_V0

# Compile federated aggregates (Type B — run after all Type A)
python -m pgs_compiler.compiler.cli --structure STRUCTURE_BUILD_VOCABULARY_AGGREGATE_V0

# Sync compiled artifacts to workspace snapshot
python pgs_compiler/scripts/pgs_build.py --workspace pgs_workspace

# Clean build artifacts
pgs_compiler/scripts/clean_pycache.sh
pgs_compiler/scripts/clean_outputs_dir.sh
pgs_compiler/scripts/clean_compiled_artifacts.sh
```

---

## Dependencies

| Dependency | Role |
|------------|------|
| `pgs_governance` | Constitutional rules, assertion handlers, structural definitions |
| `click` | CLI surface |
| `pyyaml` | YAML artifact parsing |
| `jsonschema` | Schema validation |

---

## Where this fits

```
pgs_governance  →  invariants + structural definitions
pgs_compiler    →  compile pipeline (THIS REPO)
pgs_transport   →  ingress/egress adapters
pgs_runtime     →  execution engine (reads compiled snapshot)
pgs_capabilities→  CT/CS implementations
pgs_blockchain  →  blockchain domain
pgs_ai_governance → AI governance domain
pgs_workspace   →  entry point + snapshot
```

Install order in bootstrap: `pgs_governance` → `pgs_compiler` (compiler depends on governance).

---

## License

Apache 2.0. See `LICENSE`.
