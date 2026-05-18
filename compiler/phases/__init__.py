"""
Phases: Compilation pipeline stages.

Each phase is an independently callable unit with explicit I/O contracts.

Design:
- Pure molecules (composed of atoms)
- Immutable results (PhaseResult)
- Explicit inputs/outputs
- No shared state
- Independently testable

Phases:
- discover: Scan filesystem for protocol artifacts
- parse: Extract frontmatter + content from markdown
- validate: Check references, cycles, schemas, bindings
- materialize: Write compiled JSON artifacts
- verify: Check outputs match expectations
- conformance_generate: Generate tests from TEST_DATA

Terminal Phase: conformance_generate (Phase 8)
Execution happens in pgs_runtime, NOT in compiler.
"""

from pgs_compiler.compiler.phases.discover import discover_phase
from pgs_compiler.compiler.phases.materialize import materialize_phase
from pgs_compiler.compiler.phases.parse import parse_phase
from pgs_compiler.compiler.phases.validate import validate_phase
from pgs_compiler.compiler.phases.validate_test_data import validate_test_data_phase
from pgs_compiler.compiler.phases.verify import verify_phase
from pgs_compiler.compiler.phases.conformance_generate import conformance_generate_phase

__all__ = [
    "discover_phase",
    "parse_phase",
    "validate_phase",
    "validate_test_data_phase",
    "materialize_phase",
    "verify_phase",
    "conformance_generate_phase",
]
