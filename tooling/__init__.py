"""
pgs_tooling — Developer tooling and protocol-analysis utilities for PGS.

No runtime execution semantics live here.

Bounded contexts:
  builder/                   — StructureTree loader; compiler-adjacent
  artifact_validation/       — CC, CT-IR, and WF graph validation (compiler phase)
  protocol_validation/       — Shared validation primitives and standalone CLI validators
  visualization/             — Protocol graph and execution trace rendering
  experimental/              — Dormant strategic experiments
"""