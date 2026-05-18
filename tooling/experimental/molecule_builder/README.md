# molecule_builder (experimental)

Dormant higher-order compiler abstraction — preserved for strategic optionality.

Implements a molecule-to-CT-IR compiler:
1. Schema-validates the molecule definition
2. Resolves step dependencies (topological sort)
3. Lowers to CT-IR format
4. Validates output CT-IR semantically

**Status:** Not currently wired into the compiler pipeline.
**Why preserved:** The lowering, symbol resolution, and syntax subsystems represent a potential declarative macro layer above raw CT-IR. This may become strategically important.

unused ≠ obsolete. dormant ≠ deprecated.
