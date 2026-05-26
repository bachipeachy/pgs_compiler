"""
CT_VALIDATE_WF_EXECUTION_GRAPH

Validates WF execution graph structure (DAG-based).

Enforces: INVARIANT_WF_EXECUTION_PATH_VALID_V0
"""

from typing import Any

from pgs_governance.implementation.structure.exceptions import StructuredError


class CTValidationError(StructuredError):
    """Raised when CT-IR violates host execution invariants."""

    def __init__(self, message: str):
        super().__init__(
            code="CT_VALIDATION_FAILED",
            message=message,
            details={"node_category": "CT"},
        )


def _derive_ct_category(ct_code: str) -> str:
    """
    Derive CT category from CT code prefix.

    This is the ONLY source of truth for CT category.
    """
    if ct_code.startswith("CT_PURE_"):
        return "PURE"
    if ct_code.startswith("CT_EXEC_"):
        return "EXEC"
    if ct_code.startswith("CT_MOLECULE_"):
        return "MOLECULE"
    raise CTValidationError(
        f"Invalid CT code '{ct_code}'. "
        "CT code must start with CT_PURE_, CT_EXEC_ or CT_MOLECULE_."
    )


def validate_ct_ir(ct_ir: dict) -> None:
    """
    Runtime CT-IR validator.

    RESPONSIBILITY (STRICT):
    - Validate CT-IR host shape
    - Enforce CT category execution invariants (PURE vs EXEC)

    NON-RESPONSIBILITIES:
    - Opcode legality
    - Atom typing
    - Symbol resolution
    - Bytecode ordering
    - Compiler correctness
    """

    if not isinstance(ct_ir, dict):
        raise CTValidationError("CT-IR must be a dictionary")

    required_keys = {
        "ct_composition_version",
        "ct_code",
        "inputs",
        "atom_stream",
        "outputs",
    }

    missing = required_keys - ct_ir.keys()
    if missing:
        raise CTValidationError(
            f"CT-IR missing required keys: {sorted(missing)}"
        )

    if not isinstance(ct_ir["atom_stream"], list):
        raise CTValidationError("CT-IR 'atom_stream' must be a list")

    # ---- Category enforcement ----

    ct_code = ct_ir["ct_code"]
    category = _derive_ct_category(ct_code)

    atom_stream: list[dict] = ct_ir["atom_stream"]

    if category in {"PURE", "MOLECULE"}:
        # Molecules follow the same purity invariants as atoms
        _validate_pure_ct(atom_stream, ct_code)
    elif category == "EXEC":
        _validate_exec_ct(atom_stream, ct_code)


def _validate_pure_ct(
    atom_stream: list[dict],
    ct_code: str,
) -> None:
    """
    Enforce CT_PURE_* and CT_MOLECULE_* invariants.

    PURE/MOLECULE CTs:
    - Must not emit traces
    - Must not depend on execution context
    - Must not perform control-flow or termination
    """
    for idx, instr in enumerate(atom_stream):
        opcode = instr.get("atom")

        if opcode in {"EMIT", "TRACE"}:
            raise CTValidationError(
                f"{ct_code} is pure/molecule but contains '{opcode}' "
                f"atom at position {idx}"
            )

        if opcode in {"EXIT", "ABORT", "ADVANCE"}:
            raise CTValidationError(
                f"{ct_code} is pure/molecule but contains control-flow "
                f"atom '{opcode}' at position {idx}"
            )

        if instr.get("uses_execution_context") is True:
            raise CTValidationError(
                f"{ct_code} is pure/molecule but atom at position {idx} "
                "declares execution context usage"
            )


def _validate_exec_ct(
    atom_stream: list[dict],
    ct_code: str,
) -> None:
    """
    Enforce CT_EXEC_* invariants.

    EXEC CTs:
    - May emit trace records
    - May observe execution context
    - Must NOT perform side effects
    """
    for idx, instr in enumerate(atom_stream):
        opcode = instr.get("atom")

        if opcode in {
            "WRITE_FILE",
            "PERSIST",
            "HTTP_CALL",
            "DB_WRITE",
        }:
            raise CTValidationError(
                f"{ct_code} is CT_EXEC but contains forbidden "
                f"side-effect atom '{opcode}' at position {idx}"
            )
