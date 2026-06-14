# pi — Protocol Inspection Command Processor — Design & Implementation Plan

- **Name:** `pi` (Protocol Inspection command processor)
- **Status:** **APPROVED — implementation plan.** Substrate tool enhancement at the
  dev phase, not a business-domain change: **no CR, no dossier.** (Greenlit with
  patches, expert reviews 2026-06-11 ×3; all questions resolved, §11.)
- **Version:** v0.3 (v0.2 morphed from proposal into implementation plan: §10 replaced
  with checkpoint plan, §12 change-management impact added)
- **Date:** 2026-06-11
- **Home repo:** `pgs_compiler` (SoC verdict, §8) — building on feature branch `pi`;
  release = workspace v0.6.0; user performs all commits and squash-merges
- **STATUS (2026-06-12): CP-1 and CP-2 DELIVERED.** Full taxonomy live
  (`pi` console script + `python -m pgs_compiler.inspection`); both index
  projections emitted by `pgs_compiler.cli build` (the working cross-structure
  point — the Phase B aggregation compile path was found dead and retired);
  testbeds green; snapshot VALID, 77/77 conformance, hash `f82f84f6fcc84c63`.
  Remaining (deferred, no checkpoint): `pi behavior_logic diff`; lifecycle
  enrichment when AR_ lands.
- **Doctrinal Anchor:** `pgs_workspace/doc/pgs_compiler_conceptual_model_v0.md` §9 — Protocol Inspection
- **Related:** `pgs_workspace/doc/parkinglot/artifact_retirement_model.txt` (full lifecycle enrichment lands with AR_; not blocking, §11 Q4)

---

## 1. Summary

`pi` is a read-only command processor that makes the compiled snapshot set explorable
from the terminal. It answers the questions every author, reviewer, and AI agent asks
during authoring, change management, and debugging — *who references this artifact,
what does it depend on, what breaks if I change it, which store does it own, what
superseded it* — by traversing the materialized snapshot projections that already
exist in the workspace.

It is one inspection core with three surfaces (§5.3), all over one command taxonomy (§6):

- **One-shot CLI:** `pi artifact refs blockchain::CC_GENERATE_TX_ID_V0` — scriptable, CI-friendly.
- **Interactive shell:** `pi` opens a `pi>` prompt with the snapshot index held in
  memory — fast repeated queries, tab-completion over the vocabulary, the daily
  authoring driver.
- **Programmatic API:** the inspection library (`pgs_compiler.inspection`) the CLI is
  built on, importable by in-ecosystem tooling; `--json` output serves agents and CI
  across the process boundary.

It is **not** a new capability. The compiler conceptual model (§9) already defines
Protocol Inspection as a first-class analytical capability: *"compilation answers — is
this protocol admissible? Inspection answers — what does this protocol mean?"* The
embryo already exists as `pgs_compiler.cli inspect`. This proposal grows that embryo
into the complete inspection surface the authoring experience is missing.

**Naming note.** An earlier framing called this "PQL — PGS Query Language." That name is
rejected here. A query *language* (grammar, parser, composable expressions) is
over-engineering for a graph this size, and "PQL" introduces new terminology where the
project already has an established term. The capability is **Protocol Inspection**; the
command processor is **`pi`** — its initials. No new vocabulary is created.

**Strategic framing (from expert review).** The strongest reason to build `pi` is not
debugging — it is eliminating manual navigation through hundreds of distributed
Markdown artifacts. As the registry grows to hundreds or thousands of artifacts,
authors stop thinking *"which file do I open?"* and start thinking *"what relationship
do I want to understand?"* `pi` is the relationship-navigation surface for the
protocol snapshot.

---

## 2. Problem Statement

The snapshot already knows the answer. The author manually rediscovers it.

Today an author asking *"who uses `CC_GENERATE_TX_ID_V0`?"* greps across hundreds of
distributed Markdown artifacts, opens workflow JSON, reads PNG projections, and mentally
reconstructs a dependency graph that the compiler has already built, verified, and
materialized into `evidence_snapshot/`. This is inverted: the human serves as a slow,
error-prone query engine over data that is fully indexed.

The existing `pgs_compiler.cli inspect` partially closes this gap but has three
limitations that keep it from being the daily authoring tool:

1. **It requires `--structure`.** The author must already know which STRUCTURE compiled
   an artifact before asking about it — precisely the kind of prior knowledge the tool
   should eliminate. (Zero Inference cuts both ways: the tool must not guess, but it may
   *resolve* — the reverse vocabulary makes FQDN → domain/structure resolution a lookup,
   not an inference.)
2. **It is per-structure.** Cross-structure and cross-domain questions (federated
   impact, vocabulary-wide search) have no query surface.
3. **It covers causality only.** Storage ownership, artifact lifecycle/supersession,
   assertion violations, and authoring-source retrieval have no query verbs at all.

---

## 3. Value Proposition

| Consumer | Question answered | Today | With `pi` |
|----------|-------------------|-------|-----------|
| Protocol author | Who references this CC/CT/CS? | grep + MD archaeology | `pi artifact refs` |
| CR author (Stage 0–3) | Blast radius of a proposed change? | hand-assembled list | `pi topology impact` → paste into dossier |
| Governance reviewer | Which assertions govern this WF? | read compiled JSON | `pi artifact show` |
| Maintainer | What superseded the retired WF? | tribal knowledge | `pi artifact lifecycle` (needs AR_ model) |
| Onboarding engineer | What does this workflow actually do? | open PNG + 6 MD files | `pi wf lineage` / `pi behavior_logic show` |
| AI coding agent | Ground truth before editing | re-derives graph each session | deterministic, token-cheap queries |
| CI / conformance | Are there unresolved violations? | parse compiler output | `pi validate --strict`, exit-code semantics |

The highest-leverage integration is **change management**. The dossier pipeline
(Stage 3, analysis loop) currently asks the human or agent to enumerate affected
artifacts. With `pi`, impact analysis becomes *mechanically generated
evidence* — the `pi topology impact` output is pasted (or referenced) into the dossier, and the
review question shifts from "did you find everything?" to "is this generated list
acceptable?" Every CR benefits from this on day one.

Secondary value: because inspection answers come from the same verified projections the
runtime consumes, an inspection result *carries snapshot authority* (conceptual model
§9). It is not a heuristic. This makes `pi` output admissible as dossier
evidence in a way grep output never is.

---

## 4. Doctrinal Alignment

| Doctrine | How `pi` complies |
|----------|---------------------------|
| Snapshot Sovereignty | Strictly read-only over all snapshot directories. No write path exists in the tool. |
| Single Semantic Model | Queries only materialized projections (evidence, vocabulary, PPS, canonical, visualization graphs). Never re-derives meaning from MD source or filesystem scans. |
| Zero Inference | All resolution is lookup against `vocabulary_snapshot/*/reverse.json` and the workspace `manifest.json`. Unresolvable FQDN → hard failure, never a guess. |
| Fail Hard | Missing snapshot, missing projection, unknown FQDN → non-zero exit with explicit cause. No fallback, no partial answer. |
| Trace Output Only | Traces are not a query source. `pi` answers *what is admitted*, never *what happened*. (`pi trace` is a delegating facade over `pgs_runtime examine`.) |
| Runtime Dumbness | Zero runtime dependency. The runtime never imports or invokes inspection. |
| Diagrams are projections | `pi behavior_logic` commands emit terminal trees / Mermaid / DOT from `*.graph.json` — the behavior logic source of truth — never from the PNGs. |

---

## 5. High-Level Architecture

```
                         ┌────────────────────────────────────────────┐
                         │       pi — command processor / shell       │
                         │                                            │
   author / agent / CI → │  command layer (object → verb taxonomy)    │
                         │  traversal     (graph walk, closure)       │
                         │  resolver      (FQDN → domain/structure)   │
                         │  loader        (read-only snapshot access) │
                         └───────┬────────────────────────────────────┘
                                 │  reads only — never writes
        ┌────────────┬───────────┼────────────┬─────────────┬───────────┐
        ▼            ▼           ▼            ▼             ▼           ▼
  protocol_     evidence_   vocabulary_   pps_snapshot/  visualization  manifest.json
  snapshot/     snapshot/   snapshot/     index.json     <WF>.graph.json  snapshot_status.json
  artifacts/    evidence_   forward.json  (authoring MD               
  (canonical)   graph.json  reverse.json   per FQDN)                  
```

### 5.1 Layers

1. **Loader** — opens snapshot projections from an explicit `--workspace` root (or
   `PGS_WORKSPACE` env var, declared explicitly — no cwd guessing). Validates
   `snapshot_status.json` and refuses to answer from an invalid snapshot.
2. **Resolver** — bare FQDN in, `(domain, structure, artifact kind, file paths)` out,
   via the reverse vocabulary and manifest. This is the layer that removes
   `--structure` from the user's burden. Ambiguity (same code in two domains without a
   domain prefix) is a hard error listing the candidates — never a guess.
3. **Traversal** — pure graph operations over `evidence_graph.json` and
   `*.graph.json`: upstream/downstream walk, transitive closure, supersession-chain
   walk. No domain knowledge; structure only (the compiler analog of Runtime Dumbness).
4. **Command layer** — an object-centric taxonomy, `pi <object> <verb> [target]`
   (§6). Fixed nouns and fixed verbs — not a grammar.
5. **Output projections** — every command renders to: terminal tree (default),
   `--json` (stable schema, for agents and CI), and where graph-shaped,
   `--mermaid` / `--dot`. PNG/SVG generation reuses the compiler's existing Behavior
   Logic Diagram pipeline.
6. **Shell mode** — a thin readline wrapper over the same command layer. `pi` with no
   arguments opens a `pi>` prompt, holds the resolver index in memory across queries,
   and tab-completes objects, verbs, and FQDNs from the vocabulary. No additional
   semantics live in the shell; every shell command is the one-shot command verbatim.

### 5.2 Query source map

| Command group | Primary projection consumed |
|---------------|------------------------------|
| `pi artifact`, `pi wf/cc/ct/cs/rb/in/ev/ac` | `protocol_snapshot/artifacts/` + `evidence_snapshot/<domain>/evidence_graph.json` |
| `pi topology` | evidence graph (transitive closure, cross-structure via resolver) + `*.graph.json` |
| `pi behavior_logic` | `protocol_snapshot/behavior_logic/<WF>/` — Behavior Logic projections |
| `pi store` | STRUCTURE `entity_stores` + RB data-path declarations *(needs compiler collateral, §7)* |
| `pi structure` | evidence graph + STRUCTURE artifacts |
| `pi vocab` | `vocabulary_snapshot/*/forward.json`, `reverse.json` |
| `pi pps` | `pps_snapshot/index.json` (authoring Markdown per FQDN) |
| `pi snapshot`, `pi validate` | `manifest.json`, `snapshot_status.json`, materialized conformance results *(§7)* |
| `pi artifact lifecycle` | AR_ artifacts + supersession edges *(needs AR_ model + compiler collateral, §7)* |
| `pi trace` | **delegates** to `pgs_runtime examine` — traces are runtime output, never parsed by `pi` itself (§9) |

The `pi artifact source` command deserves emphasis: because the PPS snapshot carries
the authoring Markdown indexed by FQDN, `pi artifact source blockchain::WF_MINT_V0`
returns the governed authoring document — closing the loop between graph navigation
and the MD files the author is actually editing.

### 5.3 One core, three surfaces — the programmatic interface

Layers 1–3 (loader, resolver, traversal) are not CLI internals. They are the
**inspection library** — `pgs_compiler.inspection`, an importable, read-only Python
API — and the command layer is merely its thinnest consumer. This is deliberate
repetition of the system's own pattern: one verified model, multiple projections.
The inspection capability has one core and three surfaces:

| Surface | Consumer | Form |
|---------|----------|------|
| Terminal (one-shot + shell) | humans | `pi <object> <verb>` |
| Structured output | AI agents, CI, scripts | `pi ... --json` (stable schema, process boundary) |
| Library | in-ecosystem Python: change-mgmt validation, conformance tests, future LSP / web explorer | `from pgs_compiler.inspection import ...` |

All three surfaces return the same answer by construction, because all three are the
same traversal core reading the same materialized projections. There is no separate
"API design" — the CLI taxonomy (§6) is the API, projected onto the terminal; the
library exposes the same objects and verbs as functions.

The library carries the identical invariants: read-only, fail-hard, zero inference,
query-only (§9). External agents and CI should prefer the `--json` surface — a process
boundary with a stable schema, no import coupling. The library import is for
in-ecosystem tooling that already depends on `pgs_compiler`.

---

## 6. Command Taxonomy (v0)

One fixed shape, two levels, object first:

```
pi <object> <verb> [target] [flags]
```

Object-centric rather than verb-centric (expert Patch 1): the noun namespaces grow
gracefully as commands accumulate, and shell-mode tab completion reads naturally
(`pi> cc <TAB>` lists CC verbs; `pi> cc show <TAB>` completes CC FQDNs).

Common flags everywhere: `--workspace <abs path>`, `--domain <d>`, `--json`,
`--transitive`, and for graph-shaped output `--mermaid` / `--dot`.

### 6.1 Modes

```
pi artifact refs blockchain::CC_GENERATE_TX_ID_V0     # one-shot (scripts, CI, agents)

pi                                                     # interactive shell
pi> use blockchain                                     # explicit session scope
pi:blockchain> artifact refs CC_GENERATE_TX_ID_V0     # bare code expands to FQDN
pi:blockchain> behavior_logic show WF_MINT_V0
pi:blockchain> use ai_governance                       # switch scope; always visible
pi:ai_governance>
```

Scope is *declared* via `use` and *visible* in the prompt — bare-code expansion within
a declared scope is resolution, not inference, so Zero Inference is preserved. Outside
a declared scope, full FQDNs are required.

### 6.2 `pi artifact` — kind-agnostic, the daily drivers (expert Patch 3)

Authoring questions are relationship questions — *why is X here, who references X,
what executes X* — not file-location questions. This group answers them for any FQDN
regardless of kind:

```
pi artifact show      <fqdn>    # identity, kind, governed-by, outcomes, events emitted
pi artifact refs      <fqdn>    # who references this artifact (consumers; --transitive)
pi artifact deps      <fqdn>    # what this artifact depends on (--transitive)
pi artifact lineage   <fqdn>    # full ancestry + descendants as a tree
pi artifact owner     <fqdn>    # owning domain / subdomain / STRUCTURE
pi artifact source    <fqdn>    # authoring Markdown, retrieved from PPS snapshot
pi artifact lifecycle <fqdn>    # status + supersedes / superseded-by chain (AR_ model)
pi artifact list      [--kind wf|cc|ct|cs|rb|in|ev|ac] [--status ACTIVE|RETIRED|...]
```

### 6.3 Kind objects — `pi wf | cc | ct | cs | rb | in | ev | ac`

Every kind object supports `list` and `show` (sugar over `pi artifact` with the kind
pre-bound), plus kind-specific verbs where the concern has structure of its own:

```
pi wf  list [--domain d] [--subdomain s]
pi wf  show     <fqdn>            # header, intent, declared subdomain, terminal states
pi wf  lineage  <fqdn>            # execution tree: every CC, every routed outcome
pi wf  outcomes <fqdn>            # reachable terminal states (EXIT_SUCCESS, ...)

pi cc  show     <fqdn>            # declared inputs, outputs, routing outcomes
pi cc  outcomes <fqdn>            # enumerated outcome set
pi cc  binding  <fqdn>            # CT/CS resolution via RB (execution mapping)

pi ct  show     <fqdn>            # contract + purity surface
pi ct  impl     <fqdn>            # concrete implementation bound via RB

pi cs  show     <fqdn>
pi cs  surface  [--domain d]      # the enumerated side-effect surface — what can touch the world

pi rb  show     <fqdn>
pi rb  resolve  <ct-or-cs fqdn>   # which RB binds this declaration, to what

pi in  show     <fqdn>            # admission gate: payload contract, ACK/NACK semantics
pi ev  list     [--family CONSTRUCTION|...]
pi ac  show     <fqdn>            # authority context
```

### 6.4 `pi structure` and `pi store` — compilation and storage ownership

```
pi structure list                          # all STRUCTURE_BUILD_* in the snapshot
pi structure show      <code>              # phase type, domains, what it compiled
pi structure artifacts <code>              # every artifact admitted under it
pi structure stores    <code>              # entity_stores it declares

pi store list          [--domain d]
pi store show          <STORE>             # owning structure + declared data path
pi store consumers     <STORE>             # reader / writer CCs
```

### 6.5 `pi topology` — "if I change this, what moves?" (expert Patch 5)

The change-management workhorse. Distinct from `pi artifact refs` (direct edges):
topology commands compute reachability and closure across the federated graph.

```
pi topology wf     <fqdn>     # full reachability graph of a workflow
pi topology cc     <fqdn>     # every WF position this CC occupies, with routing context
pi topology impact <fqdn>     # transitive consumer closure, grouped by kind and domain
pi topology path   <from> <to>  # is <to> reachable from <from>; show the path(s)
```

`pi topology impact` output is the artifact intended for dossier evidence
(Stage 3 analysis loop).

### 6.6 `pi snapshot` and `pi pps` — first-class targets (expert Patch 2)

```
pi snapshot status            # snapshot_status.json: valid? when built? by what?
pi snapshot summary           # domains, subdomains, artifact counts by kind
pi snapshot topology          # domain → subdomain → WF map (the FB boundary view)
pi snapshot stats             # graph metrics: nodes, edges, depth, orphans
pi snapshot validate          # conformance / assertion results (§7.5)
pi snapshot violations        # unsatisfied assertions, with missing artifacts named

pi pps stats                  # PPS coverage: indexed artifacts by kind, by domain
pi pps list   [--kind wf]     # what the authoring surface contains
pi pps show   <fqdn>          # raw PPS entry (authoring MD + parsed header)
```

### 6.7 `pi behavior_logic` — Behavior Logic (expert Patch 4)

Behavior Logic projections are the workflow graphs under
`protocol_snapshot/behavior_logic/<WF>/`. All rendering reads `*.graph.json` —
the behavior logic source of truth — never the PNGs.

```
pi behavior_logic list    [--domain d]
pi behavior_logic show    <wf-fqdn>     # terminal tree render of the behavior logic
pi behavior_logic render  <wf-fqdn> --mermaid|--dot   # text to stdout (pi writes nothing)
pi behavior_logic open    <wf-fqdn>     # open the compiler-materialized PNG
pi behavior_logic diff    <wf-fqdn> --against <other-workspace>   # later phase: structural diff
```

(`--png|--svg` render forms were dropped at CP-2: pi is write-free; the PNG is
already compiler-materialized and `open` covers it.)

### 6.8 `pi vocab` — the address space

```
pi vocab search  <term>       # vocabulary search across all domains
pi vocab resolve <fqdn>       # FQDN → domain, structure, kind, file paths (the resolver, exposed)
pi vocab stats                # vocabulary size by domain
```

### 6.9 `pi trace` — delegating facade (SoC boundary)

Traces are runtime output; *what happened* belongs to `pgs_runtime examine`, and `pi`
must never re-implement trace analysis. These commands exist for shell-session
ergonomics only and **delegate** to the runtime:

```
pi trace list    [--domain d] [--subdomain s]    # enumerate traces/ (filesystem listing)
pi trace explain <trace-id>                      # delegates to: pgs_runtime examine
```

### 6.10 Top-level conveniences

```
pi validate                   # snapshot validate + violations; non-zero exit with --strict (CI gate)
pi stats                      # workspace-wide one-screen summary
pi help [object]              # taxonomy-aware help
```

### 6.11 Expected daily drivers

Per expert review, the commands expected to dominate actual usage:

```
pi artifact refs   <fqdn>
pi topology impact <fqdn>
pi behavior_logic show  <wf>
pi snapshot validate
pi pps stats
pi trace explain   <trace-id>
```

### 6.12 Mapping from the v0 verb set

| v0 verb (superseded) | v0.1 command |
|----------------------|--------------|
| `show` | `pi artifact show` |
| `consumers` | `pi artifact refs` |
| `dependencies` | `pi artifact deps` |
| `lineage` | `pi wf lineage` / `pi artifact lineage` |
| `impact` | `pi topology impact` |
| `stores` | `pi store show` / `pi store consumers` |
| `lifecycle` | `pi artifact lifecycle` |
| `violations` | `pi snapshot violations` |
| `search` | `pi vocab search` |
| `source` | `pi artifact source` |

Explicitly **not** in scope: composable query expressions, joins, filters beyond flags,
or any "language." The escape hatch for arbitrary questions is `--json` piped to `jq` —
the projections are already structured data.

---

## 7. Collateral Requirements on the Compiler

`pi` consumes only materialized projections; everything it cannot answer today
is a gap in what the compiler emits, not in the tool. Five collateral items, in
dependency order:

1. **Federated artifact index (required for the resolver).** A single compiled index
   mapping every FQDN → `{domain, structure, artifact kind, canonical path, evidence
   path}`. The reverse vocabulary covers most of this; what is missing is the
   FQDN → STRUCTURE mapping materialized in one place (today it is implicit in which
   `evidence_snapshot/<domain>/` directory an artifact appears in). **Resolved home
   (§11 Q1): a new top-level projection, `protocol_snapshot/artifact_index/`**, emitted
   during Phase B aggregation. Rationale: the manifest is build metadata, the
   vocabulary is semantic metadata — the index is *query metadata*, and deserves its
   own projection rather than overloading either.
2. **Stable, versioned schema for `evidence_graph.json`.** Once an external tool
   consumes it, the evidence graph schema becomes a contract. It needs a declared
   schema version field and the same immutable-versioning discipline as protocol
   artifacts.
3. **Store-ownership projection (required for `stores`).** STRUCTURE artifacts already
   declare `entity_stores` and RB artifacts already declare data paths; the compiler
   should materialize the join — store → owning structure → reading/writing CCs — as a
   projection rather than forcing the tool to re-derive it from two artifact kinds.
4. **Lifecycle edges (required for full `lifecycle`; NOT blocking — §11 Q4).**
   `pi artifact lifecycle` ships first in a degraded-but-honest form, reading the
   declared artifact header status and reporting ACTIVE / RETIRED / UNKNOWN. The rich
   form — supersession chains (`supersedes` / `superseded_by`) and the full
   ACTIVE / RETIRED / DEPRECATED / PROHIBITED progression — arrives when the AR_
   retirement model (`artifact_retirement_model.txt`) lands and the compiler emits
   lifecycle edges into the evidence graph. The two proposals remain mutually
   reinforcing (AR_ gives lifecycle a governed form; `pi` makes it visible), but
   neither blocks the other.
5. **Materialized conformance results (required for `violations`).** Assertion
   outcomes currently surface as build output. The `build` phase should additionally
   write them as a snapshot projection (e.g., alongside `snapshot_status.json`) so
   violation state is queryable after the fact without re-running the build.

Items 1–2 unblock the core command groups (`pi artifact`, the kind objects,
`pi topology`, `pi vocab`, `pi pps`, `pi behavior_logic`) and require no new compiler analysis —
only re-emission of facts the semantic graph already holds. Items 3–5 each add one
projection (`pi store`, `pi artifact lifecycle`, `pi snapshot validate/violations`
respectively).

---

## 8. Repo Placement — Separation of Concerns

**Verdict: `pgs_compiler`.** Grown from the existing `inspect` subcommand, exposed as a
`pi` console entry point.

The reasoning, repo by repo:

| Repo | Why not (or why) |
|------|------------------|
| **pgs_compiler** ✅ | Inspection is doctrinally a compiler capability (conceptual model §9: inspection answers carry the authority of the compiler's own semantic model). Every projection the tool reads is compiler-emitted; the schema contracts (§7.2) are compiler-owned, so producer and consumer of those contracts evolve in one repo, in lockstep. The `inspect` embryo already lives here. |
| pgs_workspace ❌ | The workspace is an execution environment, not a development environment, and its own script rules forbid what this tool does (reading five snapshot directories; workspace scripts read `protocol_snapshot/` only and write `traces/` only). The workspace *hosts the data*; it must not own the analysis logic. |
| pgs_runtime ❌ | Runtime Dumbness. The runtime executes topology; it must never grow analytical or authoring-support capability. Trace examination (`pgs_runtime examine`) stays in the runtime because traces are runtime output — that boundary (admissibility questions vs. execution questions) is exactly the compiler/runtime split. |
| pgs_governance ❌ | Governance declares constitutional truth; it does not ship developer tooling. Governance is upstream of the compiler in the dependency graph, and tooling there would invert it. |
| pgs_change_mgmt ❌ | A consumer, not the owner. It is a markdown templates/dossiers repo with no Python package; its existing dependency arrow (`pgs_change_mgmt → pgs_compiler` for validation) already points the right way — Stage 3 impact analysis simply calls `pi topology impact`. |
| new repo (`pgs_inspect`) ❌ | A tenth repo adds ecosystem weight without a new responsibility boundary. The tool's contracts are compiler projections; separating it would require versioning those schemas across repo boundaries for one consumer. Revisit only if non-CLI consumers (LSP server, web explorer) materialize. |

Dependency direction after adoption (unchanged shape, one new consumer edge):

```
pgs_change_mgmt ──→ pgs_compiler (validation + pi)
                         │
                         └─ pi reads pgs_workspace snapshots (read-only)
```

---

## 9. Non-Goals

The governing boundary (V0 Principle, §11 Q7):

> **`pi` answers questions. The compiler performs changes. The runtime performs execution.**

V0 is query-only across all three surfaces — CLI, shell, and library. Commands users
will eventually ask for (`pi artifact retire`, `pi structure rebuild`,
`pi snapshot compile`) are mutations and belong to the compiler's CLI; admitting them
into `pi` would turn it into a second compiler CLI and dissolve the boundary that
keeps inspection answers trustworthy. Mutation surfaces, if ever, arrive after the
query model stabilizes — via their own CR, not scope creep.

- **Not a query language.** No grammar, no parser, no composable expressions. The
  interactive shell (§6.1) is a readline convenience over the fixed taxonomy — every
  shell command is a one-shot command verbatim — not a language.
- **Not a runtime input.** No component of execution may ever consume inspection
  output. (Same rule as traces.)
- **Not a mutation tool.** No command writes anything, anywhere — including caches.
  If a query is slow, the fix is a compiler-emitted projection, not a tool-side cache.
- **Not a trace analyzer.** *What happened* belongs to `pgs_runtime examine`;
  `pi trace` only delegates to it (§6.9) and must never grow its own trace parsing.
- **Not a draft validator.** It answers questions about the *compiled* snapshot.
  Validating not-yet-compiled dossier artifacts remains the compiler's `compile` path.

---

## 10. Implementation Plan (pgs_compiler)

### 10.1 Work breakdown

All code lands in `pgs_compiler`. The workspace changes only through a normal compiler
build (regenerated snapshots gain `protocol_snapshot/artifact_index/`). No runtime,
governance, or domain repo is touched.

1. **Compiler emission** (collateral, §7):
   - `artifact_index/` projection, emitted in Phase B aggregation (§7.1)
   - `schema_version` field in `evidence_graph.json` (§7.2)
   - store-ownership projection (§7.3)
   - materialized conformance results alongside `snapshot_status.json` (§7.5)
2. **Inspection library** — `pgs_compiler/inspection/` (the core, §5.3):
   - loader (explicit workspace root; refuses invalid snapshots via `snapshot_status.json`)
   - resolver (artifact_index + reverse vocabulary; ambiguity → hard error)
   - traversal (upstream/downstream walks, transitive closure, path search)
   - exposes **zero write APIs** — read-only by construction
3. **Command layer**: `pgs_compiler.cli` subcommands + `pi` console-script entry point
   (pyproject), rendering terminal trees / `--json` / `--mermaid` / `--dot`
4. **Shell mode**: readline wrapper over the command layer; `use` scoping with
   `pi:<domain>>` prompt; completion fed from the vocabulary
5. **Behavior logic rendering**: reuse the compiler's existing visualization
   pipeline (reads `*.graph.json` only)
6. **Trace delegation**: subprocess invocation of `pgs_runtime examine` — no trace
   parsing inside `pi`

### 10.2 Checkpoints — two, deliberately

Human input is already encoded in this document (taxonomy, resolutions §11, compliance
gates §10.3). Checkpoints exist only to verify, not to re-decide.

| Checkpoint | Scope delivered | Demonstration gate |
|------------|-----------------|--------------------|
| **CP-1 — Core proof** | §7.1 + §7.2 emission; inspection library; one-shot `pi`: `artifact`, kind objects, `topology`, `vocab`, `pps`, `snapshot status/summary/stats/topology`; `--json` | Full `build` regenerates workspace snapshot with `artifact_index/`; daily drivers (§6.11) run against the real snapshot; human reviews outputs |
| **CP-2 — Full surface** | Shell mode + `use` scoping; `behavior_logic`; `trace` delegation; `store` (§7.3); `snapshot validate/violations` (§7.5); `pi validate --strict`; `lifecycle` (degraded: ACTIVE/RETIRED/UNKNOWN); Mermaid/DOT | Full taxonomy walkthrough in the shell; CI exit-code semantics verified; compiler conformance suite green |

Deferred beyond CP-2, no checkpoint until triggered: `pi behavior_logic diff`; lifecycle
enrichment when AR_ lands.

### 10.3 Compliance gates — no-compromise checklist, verified at both checkpoints

- [ ] **Snapshot Sovereignty** — `artifact_index/` and all new projections enter the
      workspace only via `pgs_compiler.cli build`; nothing is hand-placed or patched
- [ ] **Read-only** — inspection library has no write API; `pi` writes nothing,
      anywhere, including caches
- [ ] **Zero Inference** — unresolvable or ambiguous FQDN → hard error naming the
      candidates; no fallback, no guessing; shell scope is declared via `use` and
      visible in the prompt
- [ ] **Fail Hard** — missing/invalid snapshot or projection → non-zero exit with
      explicit cause
- [ ] **SoC** — no `pgs_runtime` import anywhere in the `pi` path; `pi trace`
      delegates via subprocess; no domain knowledge in the traversal core
- [ ] **Query-only (V0 Principle)** — no mutation verb exists in the taxonomy, the
      CLI, or the library surface
- [ ] **No hardcoded paths** — workspace root is explicit (`--workspace` flag or
      `PGS_WORKSPACE` env var, declared); no cwd guessing, no `../` traversal
- [ ] **Determinism** — same snapshot + same command → byte-identical output (stable
      ordering on every listing)

---

## 11. Question Resolutions (expert reviews, 2026-06-11)

All Stage 0 pre-questions are resolved. Recorded here as input to the eventual CR.

| # | Question | Decision |
|---|----------|----------|
| 1 | Federated artifact index home | **New top-level projection: `protocol_snapshot/artifact_index/`**, emitted in Phase B. Manifest = build metadata; vocabulary = semantic metadata; index = query metadata — each gets its own projection. |
| 2 | `violations` exit semantics | `pi snapshot violations` exits 0 (pure query); `--strict` exits non-zero (CI gate). Both worlds. |
| 3 | Tool name | **`pi`** — strong, short, memorable. Console-script entry point; implementation stays a `pgs_compiler.cli` subcommand. |
| 4 | AR_ sequencing | **Do not block `pi` on AR_.** Phases 0–3 land first. `pi artifact lifecycle` initially reports ACTIVE / RETIRED / UNKNOWN from declared artifact status; supersession chains and the full status progression enrich it after AR_ lands. |
| 5 | `visualization/` rename | **Superseded by terminology ruling (2026-06-12).** The term is **Behavior Logic** (`behavior_logic`) — no acronym. The on-disk path is `protocol_snapshot/behavior_logic/`; the user-facing command is `pi behavior_logic`. |
| 6 | Shell scoping | **`pi> use blockchain`**, and the prompt becomes **`pi:blockchain>`** — scope is declared and permanently visible. Bare-code expansion within declared scope is resolution, not inference; Zero Inference preserved. |
| 7 | Query-only vs governed actions | **V0 is query-only** across all surfaces (CLI, shell, library): observe, inspect, explain, analyze. Principle: *`pi` answers questions; the compiler performs changes; the runtime performs execution.* Mutation commands (`pi artifact retire`, `pi structure rebuild`, `pi snapshot compile`) are explicitly rejected for V0 and require their own CR if ever proposed. |

---

## 12. Change-Management Impact

**None to process or pipeline structure.** `pi` is a substrate tool enhancement at the
dev phase, not a business-domain change — hence no CR and no dossier for `pi` itself.
The SDLC pipeline (CR → Authoring Mandate) is unchanged in shape, stages, and
templates' semantics.

Exactly two template touches follow delivery, both one-line, additive, and optional:

1. `0_agent_context_template_v0.md` — state that `pi` is available as the inspection
   surface, so agents query relationships instead of grepping markdown.
2. `3_analysis_loop_template_v0.md` — reference `pi topology impact --json` output as
   the preferred, mechanically generated impact-analysis evidence.

Neither touch gates `pi` delivery. Both are made in `pgs_change_mgmt` after CP-1
proves the outputs are worth citing.
