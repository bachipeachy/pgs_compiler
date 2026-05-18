"""
minimal_syntax.py — Minimal Molecule Syntax Expander.

Governed by: CONSTITUTION_COMPILER_V0 §9

Minimal syntax expansion is a distinct phase from lowering.
This module transforms human-authored compact syntax into canonical form.

COMPACT SYNTAX (dict-based):
----------------------------
```yaml
ct_code: CT_PURE_EXAMPLE_V0
ct_kind: molecule
emit:
  output_name: step_name

steps:
  - step_name = CT_ATOM_CODE:
      input_arg: source

  - loop_step = CT_ATOM_CODE foreach iter in collection:
      start:
        acc_field: source.path
      carry:
        acc_field: result_field
```

CANONICAL OUTPUT:
-----------------
```json
{
  "ct_code": "CT_PURE_EXAMPLE_V0",
  "inputs": {"source": "any", "collection": "any"},
  "steps": [
    {"kind": "molecule", "molecule": "CT_ATOM_CODE", "as": "step_name", "with": {...}},
    {"kind": "loop", "molecule": "CT_ATOM_CODE", "as": "loop_step", "over": "...", ...}
  ],
  "outputs": {"output_name": {"type": "object"}},
  "emit": {"output_name": "step_name"}
}
```

Constitutional rules:
- Minimal syntax is non-authoritative
- Canonical form is the source of truth
- All validation occurs on canonical form
- Expansion is stateless and deterministic
"""

from __future__ import annotations

import re
from typing import Dict, List, Any, Set, Tuple


class MinimalSyntaxError(Exception):
    """Error during minimal syntax expansion."""
    pass


def is_compact_syntax(ct_def: Dict[str, Any]) -> bool:
    """
    Detect if molecule definition uses compact YAML syntax (not canonical).

    Compact syntax has:
    - 'steps' list with "name = CT_CODE" keys
    - Does NOT have canonical step markers (kind, as in each step)

    Args:
        ct_def: Molecule definition dict

    Returns:
        True if compact syntax, False if already canonical
    """
    steps = ct_def.get("steps", [])
    if not steps:
        return False

    first_step = steps[0]
    if not isinstance(first_step, dict):
        return False

    # Canonical format has "kind" and "as" keys
    if "kind" in first_step and "as" in first_step:
        return False

    # Compact format has a single key matching pattern "name = CT_CODE" or "name = CT_CODE foreach..."
    keys = list(first_step.keys())
    if len(keys) == 1:
        key = keys[0]
        if "=" in key and ("CT_" in key or "foreach" in key):
            return True

    return False


def expand_to_canonical(ct_def: Dict[str, Any]) -> Dict[str, Any]:
    """
    Expand compact YAML molecule format to canonical format.

    This is a pure, stateless transformation.
    No external lookups, no caching, no side effects.

    Args:
        ct_def: Molecule definition in compact format

    Returns:
        Molecule definition in canonical format

    Raises:
        MinimalSyntaxError: If syntax is invalid
    """
    ct_code = ct_def.get("ct_code", "")
    emit = ct_def.get("emit", {})
    raw_steps = ct_def.get("steps", [])

    # Validate emit declaration
    if not emit or not isinstance(emit, dict):
        raise MinimalSyntaxError("Molecule must have emit declaration as dict")

    emit_output = list(emit.keys())[0]
    emit_source = emit[emit_output]

    # Parse and expand steps
    canonical_steps = []
    known_steps: Set[str] = set()
    inferred_inputs: Set[str] = set()

    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise MinimalSyntaxError(f"Invalid step format: {raw_step}")

        step_key = list(raw_step.keys())[0]
        step_value = raw_step[step_key]

        step_name, step_ct, is_loop, iterator, collection = _parse_step_key(step_key)

        if is_loop:
            canonical_step, step_inputs = _expand_loop_step(
                step_name, step_ct, iterator, collection, step_value, known_steps
            )
        else:
            canonical_step, step_inputs = _expand_regular_step(
                step_name, step_ct, step_value, known_steps
            )

        canonical_steps.append(canonical_step)
        known_steps.add(step_name)
        inferred_inputs.update(step_inputs)

    # Build canonical structure
    return {
        "ct_code": ct_code,
        "inputs": {inp: "any" for inp in sorted(inferred_inputs)},
        "steps": canonical_steps,
        "outputs": {emit_output: {"type": "object"}},
        "emit": emit,
    }


def _parse_step_key(key: str) -> Tuple[str, str, bool, str, str]:
    """
    Parse a compact step key.

    Formats:
    - "step_name = CT_CODE"
    - "step_name = CT_CODE foreach iter in collection"

    Returns:
        (step_name, ct_code, is_loop, iterator, collection)
    """
    # Check for loop syntax: "name = CT_CODE foreach iter in collection"
    loop_match = re.match(
        r"(\w+)\s*=\s*(CT_\w+)\s+foreach\s+(\w+)\s+in\s+(\w+)",
        key.strip()
    )
    if loop_match:
        return (
            loop_match.group(1),  # step_name
            loop_match.group(2),  # ct_code
            True,                 # is_loop
            loop_match.group(3),  # iterator
            loop_match.group(4),  # collection
        )

    # Regular step: "name = CT_CODE"
    regular_match = re.match(r"(\w+)\s*=\s*(CT_\w+)", key.strip())
    if regular_match:
        return (
            regular_match.group(1),  # step_name
            regular_match.group(2),  # ct_code
            False,                   # is_loop
            "",                      # iterator
            "",                      # collection
        )

    raise MinimalSyntaxError(f"Invalid step key format: {key}")


def _resolve_path(arg: str, known_steps: Set[str]) -> str:
    """
    Resolve a binding to JSONPath format.

    Rules:
    - If first part is a known step name -> $.results.{path}
    - Otherwise -> $.inputs.{path}
    """
    arg = arg.strip()

    # Already a JSONPath
    if arg.startswith("$."):
        return arg

    parts = arg.split(".")

    # If first part is a known step, it's a result reference
    if parts[0] in known_steps:
        return f"$.results.{arg}"
    else:
        return f"$.inputs.{arg}"


def _expand_regular_step(
    step_name: str,
    step_ct: str,
    step_value: Any,
    known_steps: Set[str],
) -> Tuple[Dict[str, Any], Set[str]]:
    """
    Expand a regular (non-loop) step.

    Returns:
        (canonical_step, inferred_inputs)
    """
    inferred_inputs: Set[str] = set()
    with_bindings: Dict[str, str] = {}

    if isinstance(step_value, dict):
        for k, v in step_value.items():
            resolved = _resolve_path(str(v), known_steps)
            with_bindings[k] = resolved
            if resolved.startswith("$.inputs."):
                input_name = resolved.replace("$.inputs.", "").split(".")[0]
                inferred_inputs.add(input_name)

    canonical_step = {
        "kind": "molecule",
        "molecule": step_ct,
        "as": step_name,
        "with": with_bindings,
    }

    return canonical_step, inferred_inputs


def _expand_loop_step(
    step_name: str,
    step_ct: str,
    iterator: str,
    collection: str,
    step_value: Any,
    known_steps: Set[str],
) -> Tuple[Dict[str, Any], Set[str]]:
    """
    Expand a loop step.

    Returns:
        (canonical_step, inferred_inputs)
    """
    inferred_inputs: Set[str] = {collection}
    start_bindings: Dict[str, str] = {}
    carry_bindings: Dict[str, str] = {}

    if isinstance(step_value, dict):
        for k, v in step_value.get("start", {}).items():
            resolved = _resolve_path(str(v), known_steps)
            start_bindings[k] = resolved
            if resolved.startswith("$.inputs."):
                input_name = resolved.replace("$.inputs.", "").split(".")[0]
                inferred_inputs.add(input_name)

        for k, v in step_value.get("carry", {}).items():
            carry_bindings[k] = str(v)

    # Build inputs mapping: accumulator fields + iterator -> atom inputs
    # Accumulator fields map to $.accumulator.{field}
    # Iterator maps to $.iterator
    loop_inputs: Dict[str, str] = {}
    for key in start_bindings:
        loop_inputs[key] = f"$.accumulator.{key}"
    loop_inputs[iterator] = "$.iterator"

    canonical_step = {
        "kind": "loop",
        "as": step_name,
        "molecule": step_ct,
        "over": f"$.inputs.{collection}",
        "iterator": iterator,
        "accumulator": start_bindings,
        "inputs": loop_inputs,
        "update_accumulator": carry_bindings,
    }

    return canonical_step, inferred_inputs
