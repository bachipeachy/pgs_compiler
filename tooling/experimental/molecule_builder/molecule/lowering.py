"""
lowering.py — Lower canonical molecule format to CT-IR.

Governed by: CONSTITUTION_COMPILER_V0 §8, §12

This module performs pure, stateless transformation from canonical
molecule format to CT-IR (Capability Transform Intermediate Representation).

Constitutional rules:
- No global state or caches
- Pure transformation function
- All inputs passed as parameters
- Deterministic output
"""

from typing import Dict, List

from pgs_compiler.tooling.experimental.molecule_builder.molecule.errors import CompileError


def lower_to_ct_ir(
    ct_code: str,
    inputs: Dict[str, str],
    ordered_steps: List[dict],
    emit_symbol: str
) -> dict:
    """
    Lower ordered molecule steps to CT-IR format.

    This is a pure transformation function with no side effects.
    It assumes all step references are valid (validation is caller's responsibility).

    Args:
        ct_code: Molecule identifier (e.g., "CT_PURE_EXAMPLE_V0")
        inputs: Input parameter definitions {name: type}
        ordered_steps: Dependency-ordered list of steps
        emit_symbol: Symbol name to emit as output

    Returns:
        CT-IR dict ready for execution

    Raises:
        CompileError: If step structure is invalid
    """
    atom_stream = []

    for step in ordered_steps:
        # Get instruction name (atom or molecule reference)
        instr_name = step.get("atom") or step.get("molecule")

        if not instr_name:
            raise CompileError(f"Step missing 'atom' or 'molecule' identifier: {step}")

        # Build args from 'with' bindings
        args = {}
        if "with" in step:
            args.update(step["with"])

        # Create IR instruction
        ir_atom = {
            "atom": instr_name,  # IR uses 'atom' for both atoms and molecules
            "args": args,
            "out": step.get("as")
        }

        # Preserve loop constructs if present
        if step.get("kind") == "loop":
            ir_atom["loop"] = {
                "over": step.get("over"),
                "iterator": step.get("iterator"),
                "accumulator": step.get("accumulator"),
                "inputs": step.get("inputs"),
                "update_accumulator": step.get("update_accumulator")
            }

        atom_stream.append(ir_atom)

    return {
        "ct_composition_version": "0",
        "ct_code": ct_code,
        "inputs": {
            k: {"type": v} for k, v in inputs.items()
        },
        "atom_stream": atom_stream,
        "outputs": {
            "value": {
                "from": emit_symbol,
                "type": "any"
            }
        }
    }
