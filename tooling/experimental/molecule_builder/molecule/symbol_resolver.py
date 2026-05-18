import re
from typing import Dict, List, Set, Any

from pgs_compiler.tooling.experimental.molecule_builder.molecule.errors import CompileError

_RESULT_REF = re.compile(r"\$\.results\.([A-Za-z0-9_]+)(?:\.|$)")
_INPUT_REF = re.compile(r"\$\.inputs\.([A-Za-z0-9_]+)(?:\.|$)")


def resolve_order(steps: List[dict], inputs: Dict[str, str]) -> List[dict]:
    """Strict dependency resolution."""
    # Start with molecule inputs as defined symbols
    defined: Set[str] = set(inputs.keys())
    
    # Track step outputs (e.g., 'derive_key')
    step_outputs: Set[str] = set()
    
    remaining = steps[:]
    ordered: List[dict] = []

    while remaining:
        progressed = False

        for step in list(remaining):
            deps = _dependencies(step)
            
            # Check if all dependencies are met
            # A dependency is met if it's either a molecule input or a previous step output
            # Note: _dependencies returns the root symbol (e.g., 'derive_key' from '$.results.derive_key.x')
            # or the input name (e.g., 'seed_bytes' from '$.inputs.seed_bytes')
            
            missing = []
            for dep in deps:
                if dep.startswith("input:"):
                    input_name = dep.split(":")[1]
                    if input_name not in inputs:
                        missing.append(f"$.inputs.{input_name}")
                else:
                    # It's a step dependency
                    if dep not in step_outputs:
                        missing.append(f"$.results.{dep}")

            if not missing:
                out = step["as"]
                if out in step_outputs:
                    raise CompileError(f"Symbol redeclared: '{out}'")

                ordered.append(step)
                step_outputs.add(out)
                remaining.remove(step)
                progressed = True
                break

        if not progressed:
            raise CompileError(
                f"Unresolvable CT molecule dependencies: "
                f"{[s['as'] for s in remaining]}"
            )

    return ordered


def _dependencies(step: dict) -> Set[str]:
    """
    Extract symbolic dependencies from JSONPath bindings.
    Returns a set of root symbols.
    """
    deps: Set[str] = set()

    # If it's a loop, we must NOT recurse into 'inputs' or 'update_accumulator'
    # because they refer to loop-local symbols ($.accumulator, $.iterator)
    # We ONLY care about dependencies in 'accumulator' (initial state) and 'over' (iterator source)

    scan_target = step
    if step.get("kind") == "loop":
        # Create a synthetic object that only contains the fields that bind to external scope
        scan_target = {
            "over": step.get("over"),
            "accumulator": step.get("accumulator"),
            # 'with' might be used in future loop designs, so include it if present
            "with": step.get("with")
        }

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            # Check for $.results.STEP_NAME...
            for m in _RESULT_REF.findall(v):
                deps.add(m)
            
            # Check for $.inputs.INPUT_NAME...
            # We prefix these to distinguish them from step outputs in the resolver logic
            for m in _INPUT_REF.findall(v):
                deps.add(f"input:{m}")

    walk(scan_target)
    return deps
