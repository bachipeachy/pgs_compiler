"""
compiler.py — Molecule to CT-IR Compiler.

Governed by: CONSTITUTION_COMPILER_V0

Pipeline:
1. Validate input molecule against SCHEMA_MOLECULE_V0
2. Resolve step dependencies (topological order)
3. Lower to CT-IR format
4. Validate output CT-IR against SCHEMA_CT_IR_V0
5. Perform semantic validation (symbols, types, dead code)
"""

from __future__ import annotations

from typing import Dict, Any

from jsonschema import validate as jsonschema_validate
from jsonschema.exceptions import ValidationError

from pgs_compiler.tooling.experimental.molecule_builder.molecule.errors import CompileError
from pgs_compiler.tooling.experimental.molecule_builder.molecule.schema_loader import (
    load_molecule_schema,
    load_ct_ir_schema,
)
from pgs_compiler.tooling.experimental.molecule_builder.molecule.symbol_resolver import resolve_order
from pgs_compiler.tooling.experimental.molecule_builder.molecule.lowering import lower_to_ct_ir
from pgs_compiler.tooling.artifact_validation import validate_ct_composition


def compile_molecule(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Molecule → CT-IR compiler.

    Validates input, resolves dependencies, lowers to IR,
    then validates output against schema and performs semantic checks.

    Args:
        doc: Canonical molecule definition

    Returns:
        CT-IR dict ready for execution

    Raises:
        CompileError: If compilation fails at any stage
    """
    # Stage 1: Validate input molecule against schema
    molecule_schema = load_molecule_schema()
    try:
        jsonschema_validate(instance=doc, schema=molecule_schema)
    except ValidationError as e:
        raise CompileError(f"Molecule schema validation failed: {e.message}")

    ct_code = doc["ct_code"]
    inputs = doc["inputs"]
    steps = doc["steps"]
    outputs = doc["outputs"]
    emit = doc["emit"]

    # Stage 2: Semantic validation of molecule structure
    if len(emit) != 1:
        raise CompileError("Molecule must emit exactly one output")

    out_name, emit_symbol = next(iter(emit.items()))

    if out_name not in outputs:
        raise CompileError(f"Emit refers to undeclared output '{out_name}'")

    produced = {step["as"] for step in steps}
    if emit_symbol not in produced:
        raise CompileError(f"Emit symbol '{emit_symbol}' not produced by any step")

    # Stage 3: Resolve step dependencies (topological sort)
    ordered = resolve_order(steps, inputs)

    # Stage 4: Lower to CT-IR
    ct_ir = lower_to_ct_ir(
        ct_code=ct_code,
        inputs=inputs,
        ordered_steps=ordered,
        emit_symbol=emit_symbol,
    )

    # Stage 5: Validate CT-IR against schema (structural)
    ct_ir_schema = load_ct_ir_schema()
    try:
        jsonschema_validate(instance=ct_ir, schema=ct_ir_schema)
    except ValidationError as e:
        raise CompileError(f"CT-IR schema validation failed: {e.message}")

    # Stage 6: Semantic validation (symbols, types, dead code)
    validate_ct_composition(ct_ir)

    return ct_ir
