# artifact_validation

Compiler-phase semantic validation for protocol artifacts.

Validates the full artifact surface at compile time:
- **CC** — Capability Contract input/output bindings
- **CT-IR** — Capability Transform bytecode composition
- **WF graph** — Workflow DAG structure and reachability
- **WF↔CC linkage** — Workflow-to-contract reference integrity

This module rejects structurally invalid protocol. It is a compiler gate, not a developer aid.
