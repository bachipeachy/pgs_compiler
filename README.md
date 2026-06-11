# pgs_compiler

**Topology-native governance compiler for Protocol-Governed Systems.**

The compiler translates protocol declarations into sealed, verifiable execution snapshots.  
It does not execute behavior. It does not contain runtime logic. It does not interpret intent.

Behavior is declared in protocol, compiled into snapshots, executed by runtime, and observed via traces.

> **New to PGS?** This is one of the repositories in the Protocol-Governed Systems ecosystem.
> For orientation, architecture overview, and end-to-end execution, start at [pgs_workspace](https://github.com/bachipeachy/pgs_workspace).

---

## What this component is (and is not)

**This is:**
- A multi-stage compilation pipeline (S1–S9)
- A governance enforcement layer (invariant checking at compile time)
- A snapshot producer (canonical, tokenized, vocabulary, evidence, dispatch, handlers)
- A conformance test runner for CT implementations

**This is not:**
- A runtime engine
- A workflow interpreter
- A code generator for application logic
- A schema validator (schema correctness is a governance concern, not a compiler concern)

All behavior is validated and sealed before execution begins. The runtime only consumes what this compiler produces.

---

## Inputs → Outputs

**Inputs:**
```
protocol source artifacts (*.md with YAML frontmatter)
├── WF_  workflows
├── CC_  capability contracts
├── CT_  capability transforms
├── CS_  capability side effects
├── RB_  runtime bindings
├── IN_  intents
├── EV_  events
├── AC_  actors
└── TE_  transport egress
```

**Outputs (written to workspace snapshot dirs):**
```
canonical_snapshot/<domain>/       ← full compiled artifact graph (JSON)
tokenized_snapshot/<domain>/       ← integer-addressed execution substrate
  ├── dispatch.json                   ← per-WF routing + CC pipeline steps
  ├── handlers.json                   ← CT-IR + CS handler refs + RB policy
  └── metadata.json                   ← projection hash for trust verification
vocabulary_snapshot/<domain>/      ← FQDN ↔ address mappings (forward/reverse)
evidence_snapshot/<domain>/        ← semantic causality graph
trust_snapshot/<domain>/           ← cryptographic attestation (STUB in v0)
```

---

## CLI surface

```bash
# Phase A — per-structure compilation (run in order)
python -m pgs_compiler.cli compile --structure STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0
python -m pgs_compiler.cli compile --structure STRUCTURE_BUILD_AI_GOVERNANCE_CONFIG_V0

# Phase B — cross-structure aggregation (run after all Phase A)
python -m pgs_compiler.cli compile --structure STRUCTURE_BUILD_VOCABULARY_AGGREGATE_V0

# Full build — compile + sync + conformance + attestation + snapshot validation
python -m pgs_compiler.cli build --workspace /abs/path/to/pgs_workspace

# Inspect compiled evidence without recompiling
python -m pgs_compiler.cli inspect --structure STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0 \
  --artifact blockchain::WF_REGISTER_ACTOR_UNVERIFIED_V0
python -m pgs_compiler.cli inspect --structure STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0 \
  --upstream blockchain::CC_GENERATE_ACTOR_ID_V0
```

---

## How compilation works

The compiler runs a 9-stage pipeline against the protocol source:

| Stage | Name | What it does |
|-------|------|--------------|
| S1 | Extract | Parses YAML frontmatter from source artifacts; builds initial graph |
| S2 | Canonicalize | Resolves local node keys to FQDNs; builds WF topology edges |
| S3 | Semantic Addressing | Assigns deterministic integer addresses to every node and edge |
| S4 | Govern | Enforces constitutional invariants; validates governance boundaries |
| S5 | Construct | Builds CT-IR, CS-IR, CC projection; produces executable intermediate representations |
| S6 | Project | Emits canonical, tokenized, vocabulary, evidence, dispatch, and handlers projections |
| S7 | Materialize | Writes projection files to disk; generates workflow visualizations |
| S8 | Verify | Checks output completeness, schema conformance, and CT conformance tests |
| S9 | Attest | Computes and writes trust attestation for each structure and the full snapshot |

Stages run in order. Each stage transforms an immutable `State` object — no stage mutates prior stage output.

---

## Two-phase build architecture

**Phase A — per-structure compilation**

Each `STRUCTURE_BUILD_*_CONFIG_V0` artifact describes one domain's artifact scope, governance boundaries, and output configuration. Phase A compiles that domain in isolation.

**Phase B — cross-structure aggregation**

`STRUCTURE_BUILD_VOCABULARY_AGGREGATE_V0` runs after all Phase A structures complete. It aggregates per-domain address spaces into a federated vocabulary. Cross-domain references are resolved only at this phase.

The `build` command runs both phases in the correct order automatically.

---

## What makes this compiler different

**1. Governance as a first-class compilation concern**

Invariant checking (S4) is not a linting pass — it is a gate. Protocol artifacts that violate constitutional boundaries fail compilation. The runtime never executes ungoverned behavior.

**2. Topology-native addressing**

Every artifact receives a deterministic integer address (S3) derived from graph position and content. The runtime operates entirely on integer addresses — no string resolution at execution time.

**3. Compile-time closure**

All routing, bindings, input paths, and output mappings are resolved and validated before any snapshot is written. The runtime receives sealed, self-consistent instructions.

**4. Conformance at compile time**

CT implementations are tested against declared `TEST_DATA` artifacts during every build (S8). A CT that fails its conformance tests blocks snapshot validation.

**5. Multi-projection output**

A single compilation produces six distinct snapshot projections, each optimized for a different consumer:
- `canonical` — complete governed artifact graph (human-readable)
- `tokenized` — integer-addressed execution substrate (runtime input)
- `vocabulary` — FQDN ↔ address index (lookup tables)
- `evidence` — semantic causality graph (observability / replay)
- `dispatch` — per-WF routing + pipeline steps (scheduler input)
- `handlers` — CT-IR + CS handler refs + RB policy (dispatcher input)

---

## Where this fits in the system

| Layer | Repo | Responsibility |
|-------|------|----------------|
| Governance | `pgs_governance` | Invariants, constitutional rules, structural definitions |
| **Compilation** | **`pgs_compiler` ← here** | **Produce sealed, verified execution snapshots** |
| Transport | `pgs_transport` | Ingress/egress adapters for HTTP and CLI |
| Execution | `pgs_runtime` | Traverse compiled graph deterministically |
| Capabilities | `pgs_capabilities` | Provide CT/CS implementations |
| Domains | `pgs_blockchain`, `pgs_ai_governance` | Real-world workflows |
| Change Mgmt | `pgs_change_mgmt` | Governed SDLC — Change Request to Authoring Mandate (new in v0.5.0) |
| Entry point | `pgs_workspace` | Run and observe |

---

## What you should explore next

| Go here | To... |
|---------|-------|
| `pgs_workspace` | Run a full build and observe the snapshot output |
| `pgs_governance` | Author constitutional invariants and structural definitions |
| `pgs_runtime` | Understand what the tokenized snapshot is consumed for |
| `canonical_snapshot/` | Inspect the full compiled artifact graph |

---

## Research context

This implementation demonstrates:

> *"Correctness by construction, not by convention."*

And more broadly: compile-time governance enforcement, topology-native semantic addressing, and multi-projection snapshot architecture as a substrate for governed distributed systems.

---

## License

Apache-2.0. See LICENSE and NOTICE for details.
