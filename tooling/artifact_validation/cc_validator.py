"""
validator.py — Capability Contract Validator

Validates CC bindings against declared capability operations.
Rejects invalid protocol. Does not help authors succeed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Set

from pgs_governance.structure.structure.resolution import paths


class CapabilityContractError(Exception):
    pass


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise CapabilityContractError(f"Malformed JSON: {path}\n{e}")


def _derive_ct_ops_from_molecule(ct_code: str) -> Set[str]:
    """Extract allowed ops from CT molecule steps."""
    path = paths.protocol.artifacts_root() / "capability_transforms" / f"{ct_code}.molecule.json"

    if not path.exists():
        path = paths.protocol.static_specs_root() / "capability_transforms" / "molecules" / f"{ct_code}.molecule.template.json"

    if not path.exists():
        raise CapabilityContractError(f"CT molecule missing: '{ct_code}'")

    data = _load_json(path)
    steps = data.get("core", {}).get("steps") or data.get("steps")

    if not isinstance(steps, list):
        raise CapabilityContractError(f"'steps' must be list in {path}")

    return {step["atom"] for step in steps if isinstance(step.get("atom"), str)}


def _load_cs_ops(cs_code: str) -> Set[str]:
    """Load allowed ops from CS operations.json."""
    for cs_type in ["persistent", "external", "ephemeral"]:
        path = paths.protocol.capability_side_effect_spec(cs_type, cs_code, "operations.json")
        if path.exists():
            data = _load_json(path)
            ops = data.get("operations")
            if isinstance(ops, dict):
                return set(ops.keys())
            raise CapabilityContractError(f"'operations' must be object in {path}")

    raise CapabilityContractError(f"CS operations.json missing: '{cs_code}'")


def _resolve_ops(capability: str) -> Set[str]:
    """Resolve allowed operations for a capability."""
    if capability.startswith("CT_"):
        return _derive_ct_ops_from_molecule(capability)
    if capability.startswith("CS_"):
        return _load_cs_ops(capability)
    raise CapabilityContractError(f"Unknown capability type: '{capability}'")


class CapabilityContractValidator:
    """Validates capability contract bindings."""

    def __init__(
        self,
        vocab_symbols: dict,
        vocab_index: dict,
        contracts: Dict[str, dict],
    ):
        self.contracts = contracts
        self.errors = []

    def run(self) -> None:
        for cc_code, contract in self.contracts.items():
            self._validate_contract(cc_code, contract)

    def _validate_contract(self, cc_code: str, contract: dict) -> None:
        bindings = contract.get("bindings")
        if bindings is None:
            return

        if isinstance(bindings, dict):
            items = [(cap, cfg) for cap, cfg in bindings.items()]
        elif isinstance(bindings, list):
            items = [(b.get("capability"), b) for b in bindings]
        else:
            self._error(cc_code, "CC_SEMANTIC_000", "'bindings' must be dict or list")
            return

        for capability, binding in items:
            op = binding.get("op") if isinstance(binding, dict) else None

            if not isinstance(capability, str) or not isinstance(op, str):
                self._error(cc_code, "CC_SEMANTIC_000", "binding requires 'capability' and 'op'")
                continue

            try:
                valid_ops = _resolve_ops(capability)
            except CapabilityContractError as e:
                self._error(cc_code, "CC_SEMANTIC_001", str(e))
                continue

            if op not in valid_ops:
                self._error(cc_code, "CC_SEMANTIC_001", f"Invalid op '{op}' for '{capability}'")

    def _error(self, cc_code: str, code: str, msg: str) -> None:
        self.errors.append((cc_code, code, msg))

    def report(self) -> None:
        if not self.errors:
            return
        print("\n" + "=" * 72)
        print("ERROR: Capability Contract Violations")
        print("=" * 72)
        for cc, code, msg in self.errors:
            print(f"[ERROR] {code} :: {cc}")
            print(f"  {msg}")

    def exit_code(self) -> int:
        return 1 if self.errors else 0
