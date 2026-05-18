# pgs_tooling

Developer tooling and protocol-analysis utilities for PGS.

No runtime execution semantics live here.

## Bounded Contexts

| Directory | Purpose |
|---|---|
| `builder/` | StructureTree loader — compiler-adjacent package discovery |
| `artifact_validation/` | Compiler-phase semantic validation: CC, CT-IR, and WF graph |
| `protocol_validation/` | Shared validation primitives (`core/`) and standalone CLI validators (`cli/`) |
| `visualization/` | Protocol graph and execution trace rendering (DOT/PNG) |
| `experimental/` | Dormant strategic experiments — preserved for optionality |
