"""
ct_bytecode_validator.py — CT-IR v0 Constitutional Validator
"""

from __future__ import annotations

import re
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------
# Type System
# ---------------------------------------------------------------------

class PrimitiveType(Enum):
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    OBJECT = "object"
    ARRAY = "array"
    NULL = "null"
    ANY = "any"
    BYTES = "bytes"  # Added for crypto support
    LIST = "list"    # Added for crypto support

    @classmethod
    def from_string(cls, s: str) -> "PrimitiveType":
        try:
            return cls(s)
        except ValueError:
            raise CompileError(f"Unknown type: '{s}'")

    def is_compatible_with(self, other: "PrimitiveType") -> bool:
        if self == other:
            return True
        if self == PrimitiveType.ANY or other == PrimitiveType.ANY:
            return True
        if other == PrimitiveType.NULL:
            return True
        return False


# ---------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------

class CompileError(Exception):
    pass


# ---------------------------------------------------------------------
# Symbol Table
# ---------------------------------------------------------------------

@dataclass
class Symbol:
    name: str
    type: PrimitiveType
    defined_at_op: int
    used: bool = False


class SymbolTable:
    def __init__(self):
        self.symbols: Dict[str, Symbol] = {}

    def define(self, name: str, type: PrimitiveType, op_index: int) -> None:
        if name in self.symbols:
            raise CompileError(
                f"Symbol '{name}' redeclared at atom {op_index}"
            )
        self.symbols[name] = Symbol(name, type, op_index)

    def use(self, name: str, current_op: int) -> Symbol:
        if name not in self.symbols:
            raise CompileError(
                f"Undefined symbol '{name}' referenced at atom {current_op}"
            )

        symbol = self.symbols[name]

        if symbol.defined_at_op >= current_op:
            raise CompileError(
                f"Forward reference to symbol '{name}' at atom {current_op}"
            )

        symbol.used = True
        return symbol

    def get(self, name: str) -> Optional[Symbol]:
        return self.symbols.get(name)

    def dead_symbols(self) -> List[str]:
        return [s.name for s in self.symbols.values() if not s.used]


# ---------------------------------------------------------------------
# Opcode Registry (AUTHORITATIVE)
# ---------------------------------------------------------------------

# This set is now dynamically extensible or should be relaxed for molecules
# For now, we keep the core set but allow unknown opcodes if they follow the pattern
# to support new atoms/molecules without updating this file every time.
# However, for strictness, we should ideally load from atom_table.
# Given the current architecture, we will relax this check to allow any valid identifier
# as an opcode, assuming the compiler has already validated existence.

ATOM_SET = {
    "EXTRACT",
    "GENERATE_ID",
    "EMIT",
    # Add new crypto atoms
    "CT_PURE_DERIVE_MASTER_KEY_V0",
    "CT_PURE_DERIVE_CHILD_KEY_V0",
    "CT_PURE_PRIVATE_KEY_TO_PUBLIC_V0",
    "CT_PURE_PUBKEY_TO_ETH_ADDRESS_V0",
    "CT_PURE_MNEMONIC_TO_SEED_V0",
    "CT_PURE_GENERATE_ENTROPY_V0",
    "CT_PURE_ENTROPY_TO_MNEMONIC_V0",
    "CT_PURE_ASSEMBLE_RECORD_V0",
    # Add molecules
    "CT_PURE_DERIVE_BIP32_PATH_V0",
    "CT_PURE_DERIVE_EXTENDED_KEYS_V0",
    "CT_PURE_GENERATE_WALLET_FROM_MNEMONIC_V0",
    "CT_PURE_GENERATE_ID_V0"
}


def validate_atoms_code(opcode: str) -> None:
    # Relaxed validation: allow any valid CT code or legacy opcode
    if opcode not in ATOM_SET and not re.match(r'^CT_(PURE|EXEC|MOLECULE)_[A-Z0-9_]+_V[0-9]+$', opcode):
         raise CompileError(
            f"Unknown opcode: '{opcode}'. "
            f"Allowed opcodes: {', '.join(sorted(ATOM_SET))} or valid CT code"
        )


# ---------------------------------------------------------------------
# JSONPath Validation
# ---------------------------------------------------------------------

def validate_jsonpath(path: str) -> None:
    if '*' in path:
        raise CompileError(f"Illegal JSONPath wildcard: '{path}'")
    if '?(' in path:
        raise CompileError(f"Illegal JSONPath filter: '{path}'")
    if not path.startswith('$'):
        raise CompileError(f"JSONPath must start with '$': '{path}'")

    pattern = r'^\$(\.[a-zA-Z_][a-zA-Z0-9_]*|\[\d+\])*$'
    if not re.match(pattern, path):
        raise CompileError(f"Invalid JSONPath syntax: '{path}'")


# ---------------------------------------------------------------------
# Identifier Validation
# ---------------------------------------------------------------------

def validate_identifier(name: str, context: str) -> None:
    if not re.match(r'^[a-z_][a-z0-9_]*$', name):
        raise CompileError(
            f"Invalid identifier '{name}' in {context}"
        )


def validate_ct_code(ct_code: str) -> None:
    if not re.match(r'^CT_(PURE|EXEC|MOLECULE)_[A-Z0-9_]+_V[0-9]+$', ct_code):
        raise CompileError(f"Invalid CT code: '{ct_code}'")


def _is_ct_pure(ct_code: str) -> bool:
    return ct_code.startswith("CT_PURE_")


def _is_ct_exec(ct_code: str) -> bool:
    return ct_code.startswith("CT_EXEC_")


def _is_ct_molecule(ct_code: str) -> bool:
    return ct_code.startswith("CT_MOLECULE_")


# ---------------------------------------------------------------------
# Structural Validation
# ---------------------------------------------------------------------

def validate_structure(doc: Any) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        raise CompileError("CT-IR document must be an object")

    required = {
        "ct_composition_version",
        "ct_code",
        "inputs",
        "atom_stream",
        "outputs",
    }

    actual = set(doc.keys())

    if required - actual:
        raise CompileError(f"Missing keys: {sorted(required - actual)}")

    if actual - required:
        raise CompileError(f"Unknown keys: {sorted(actual - required)}")

    return doc


# ---------------------------------------------------------------------
# Version Validation
# ---------------------------------------------------------------------

def validate_version(v: str) -> None:
    if v != "0":
        raise CompileError(f"Unsupported CT-IR version: '{v}'")


# ---------------------------------------------------------------------
# Inputs Validation
# ---------------------------------------------------------------------

def validate_inputs(inputs: Any) -> Dict[str, PrimitiveType]:
    if not isinstance(inputs, dict) or not inputs:
        raise CompileError("'inputs' must be a non-empty object")

    out: Dict[str, PrimitiveType] = {}

    for name, spec in inputs.items():
        validate_identifier(name, "inputs")

        if not isinstance(spec, dict) or set(spec) != {"type"}:
            raise CompileError(f"Invalid input spec for '{name}'")

        out[name] = PrimitiveType.from_string(spec["type"])

    return out


# ---------------------------------------------------------------------
# Opcode Argument Validation
# ---------------------------------------------------------------------

def validate_extract(args, i, inputs):
    required = {"from", "path", "type"}
    if set(args) != required:
        raise CompileError(f"EXTRACT args mismatch at {i}")

    m = re.match(r'^\$\.inputs\.([a-z_][a-z0-9_]*)$', args["from"])
    if not m or m.group(1) not in inputs:
        raise CompileError(f"Invalid EXTRACT 'from' at {i}")

    validate_jsonpath(args["path"])
    return PrimitiveType.from_string(args["type"])


def validate_generate_id(args, i, symbols):
    required = {"prefix", "data"}
    if set(args) != required:
        raise CompileError(f"GENERATE_ID args mismatch at {i}")

    prefix = args["prefix"]
    data = args["data"]

    if not isinstance(prefix, str):
        raise CompileError(f"GENERATE_ID prefix must be string at {i}")

    if not isinstance(data, str):
        raise CompileError(f"GENERATE_ID data must be JSONPath string at {i}")

    # data is a JSONPath, NOT a symbol
    validate_jsonpath(data)

    return PrimitiveType.STRING


def validate_emit(args, i, symbols):
    if set(args) != {"value"}:
        raise CompileError(f"EMIT args mismatch at {i}")
    return symbols.use(args["value"], i).type


# ---------------------------------------------------------------------
# ATOM Stream Validation
# ---------------------------------------------------------------------

def validate_atom_stream(stream, inputs, symbols, ct_code: str) -> None:
    if not isinstance(stream, list) or not stream:
        raise CompileError("atom_stream must be non-empty list")

    emit_seen = False

    for i, inst in enumerate(stream):
        # Relaxed check to allow 'loop' property
        allowed_keys = {"atom", "args", "out", "loop"}
        if not set(inst).issubset(allowed_keys) or "atom" not in inst:
             raise CompileError(f"Invalid atom shape at {i}: {inst.keys()}")

        opcode = inst["atom"]
        args = inst["args"]
        out = inst["out"]

        validate_atoms_code(opcode)
        if out:
            validate_identifier(out, f"atom {i} output")

        if opcode == "EXTRACT":
            t = validate_extract(args, i, inputs)
            symbols.define(out, t, i)

        elif opcode == "GENERATE_ID":
            t = validate_generate_id(args, i, symbols)
            symbols.define(out, t, i)

        elif opcode == "EMIT":
            if emit_seen:
                raise CompileError("Multiple EMIT atoms found")
            emit_seen = True
            t = validate_emit(args, i, symbols)
            symbols.define(out, t, i)

        else:
            # Generic atom/molecule validation

            # 1. Mark used symbols in args
            # Args can be values or references. References start with $.results.
            # We need to scan args for references and call symbols.use()

            def scan_for_refs(obj):
                if isinstance(obj, str):
                    # Check for $.results.SYMBOL...
                    m = re.match(r"\$\.results\.([A-Za-z0-9_]+)(?:\.|$)", obj)
                    if m:
                        sym_name = m.group(1)
                        symbols.use(sym_name, i)
                elif isinstance(obj, dict):
                    for v in obj.values():
                        scan_for_refs(v)
                elif isinstance(obj, list):
                    for v in obj:
                        scan_for_refs(v)

            scan_for_refs(args)

            # Also scan loop constructs if present
            if "loop" in inst:
                loop_def = inst["loop"]
                # 'accumulator' defines initial values, which might be references
                scan_for_refs(loop_def.get("accumulator", {}))
                # 'over' is the iterator source, which might be a reference
                scan_for_refs(loop_def.get("over"))

            # 2. Define output symbol
            # For now, we assume ANY output type because we don't have full type inference for all atoms yet
            if out:
                symbols.define(out, PrimitiveType.ANY, i)

    # -----------------------------------------------------------------
    # Category-aware EMIT rules (CT Constitution)
    # -----------------------------------------------------------------
    if _is_ct_pure(ct_code) or _is_ct_molecule(ct_code):
        # PURE and MOLECULE: no EMIT atom allowed.
        # Molecule IR should not contain EMIT (it uses the final outputs mapping)
        if emit_seen:
            raise CompileError(
                f"{ct_code} is PURE/MOLECULE but contains EMIT atom"
            )
    elif _is_ct_exec(ct_code):
        # EXEC: must contain exactly one EMIT and it must be last.
        if not emit_seen:
            raise CompileError(
                f"{ct_code} requires EMIT atom"
            )
        if stream[-1]["atom"] != "EMIT":
            raise CompileError(
                f"{ct_code} EMIT must be last atom"
            )
    else:
        # FAIL LOUD if prefix is unknown
        raise CompileError(
            f"CT code must start with CT_PURE_, CT_EXEC_ or CT_MOLECULE_: '{ct_code}'"
        )



# ---------------------------------------------------------------------
# Outputs Validation
# ---------------------------------------------------------------------

def validate_outputs(outputs, symbols):
    if not isinstance(outputs, dict) or not outputs:
        raise CompileError("'outputs' must be non-empty object")

    for name, spec in outputs.items():
        validate_identifier(name, "outputs")

        if set(spec) != {"from", "type"}:
            raise CompileError(f"Invalid output spec for '{name}'")

        sym = symbols.get(spec["from"])
        if not sym:
            raise CompileError(f"Output references undefined symbol '{spec['from']}'")

        sym.used = True
        declared = PrimitiveType.from_string(spec["type"])

        if not sym.type.is_compatible_with(declared):
            raise CompileError(
                f"Output '{name}' type mismatch: "
                f"{sym.type.value} vs {declared.value}"
            )


# ---------------------------------------------------------------------
# Dead Code Detection
# ---------------------------------------------------------------------

def validate_no_dead_code(symbols):
    dead = symbols.dead_symbols()
    if dead:
        raise CompileError(f"Dead symbols detected: {dead}")


# ---------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------

def validate_ct_composition(doc: str | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(doc, str):
        doc = json.loads(doc)

    doc = validate_structure(doc)
    validate_version(doc["ct_composition_version"])
    validate_ct_code(doc["ct_code"])

    inputs = validate_inputs(doc["inputs"])
    symbols = SymbolTable()

    validate_atom_stream(doc["atom_stream"], inputs, symbols, doc["ct_code"])
    validate_outputs(doc["outputs"], symbols)
    validate_no_dead_code(symbols)

    return doc
