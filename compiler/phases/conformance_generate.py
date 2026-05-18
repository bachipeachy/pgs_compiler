"""
Conformance Generate phase: Load TEST_DATA, bind to CT-IR, generate conformance test cases.

Input: Validated artifacts (list[dict])
Output: PhaseResult with generated_tests (list[dict])

Design:
- Load TEST_DATA artifacts
- Bind bindings to CT-IR
- Write test cases to compiled/conformance/ct/<fqdn>__<case_id>.json
- Federated output (layer-specific)
"""

import json
import re
from typing import Any

import yaml

from pgs_governance.structure.structure.resolution import LayerResolver

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    PhaseResult,
    PhaseStatus,
)


def conformance_generate_phase(
    validated_artifacts: list[dict[str, Any]],
    structure: dict,
) -> PhaseResult:
    """
    Generate conformance test cases from TEST_DATA.

    Args:
        validated_artifacts: Output from validate_phase
        structure: STRUCTURE artifact dict (required for output path resolution)

    Returns:
        PhaseResult with generated_tests

    Errors:
        E101_INVALID_YAML: Failed to parse test case YAML
        E301_WRITE_FAILED: Failed to write conformance test file

    Governed By:
        INVARIANT_NO_UNDECLARED_BEHAVIOR_SURFACE_V0
        STRUCTURE_BUILD_PLATFORM_CONFIG_V0
    """
    errors: list[CompilerError] = []
    generated_tests: list[dict] = []

    # Initialize LayerResolver for STRUCTURE-driven path resolution
    resolver = LayerResolver()

    if structure is None:
        raise RuntimeError(
            "conformance_generate_phase requires 'structure' parameter."
        )

    # Index CT artifacts by artifact_code for binding
    ct_artifacts = {
        a["artifact_code"]: a for a in validated_artifacts 
        if a["artifact_type"] == "CT"
    }
    
    # Index TEST_DATA artifacts by target CT code
    test_data_by_ct: dict[str, list[dict]] = {}
    for a in validated_artifacts:
        if a["artifact_type"] != "TEST_DATA":
            continue

        # Target CT code can be in frontmatter or content
        target_ct_code = a.get("frontmatter", { }).get("target", { }).get("ct_code")

        if not target_ct_code:
            # Try parsing from content if not in frontmatter
            try:
                content = a.get("content", "")
                target_match = re.search(r"## Target\s*\n+```yaml\s*\n(.*?)\n```", content, re.DOTALL)
                if target_match:
                    target_yaml = yaml.safe_load(target_match.group(1))
                    target_ct_code = target_yaml.get("ct_code")
            except Exception:
                pass

        if target_ct_code:
            if target_ct_code not in test_data_by_ct:
                test_data_by_ct[target_ct_code] = []
            test_data_by_ct[target_ct_code].append(a)

    # Process each CT
    for ct_code, ct in ct_artifacts.items():
        td_artifacts = test_data_by_ct.get(ct_code, [])

        if not td_artifacts:
            continue

        ct_ir_base = ct.get("ct_ir")
        if not ct_ir_base:
            continue

        for td in td_artifacts:
            # Extract cases from markdown content
            content = td.get("content", "")

            # Pattern: ### Case N: id\n\n**Description:** description\n\n```yaml\n{case_data}\n```
            case_blocks = re.findall(r"### Case \d+: (?P<case_id>\w+).*?```yaml\n(?P<case_data>.*?)```", content, re.DOTALL)

            cases = []
            for case_id, case_data in case_blocks:
                try:
                    case_dict = yaml.safe_load(case_data)
                    case_dict["case_id"] = case_id
                    cases.append(case_dict)
                except Exception as e:
                    errors.append(
                        CompilerError(
                            code=ErrorCode.E101_INVALID_YAML,
                            message=f"Failed to parse case data in {td['fqdn_id']}: {e}",
                            phase="CONFORMANCE_GENERATE",
                            fqdn_id=td["fqdn_id"],
                            artifact_code=td["artifact_code"],
                        )
                    )

            for case in cases:
                case_id = case.get("case_id")
                bindings = case.get("bindings", { })
                expected = case.get("expected", { })
                assertions = case.get("assertions", { })

                # Construct CT-IR with fully bound inputs (no inference required)
                ct_ir = ct_ir_base.copy()

                # Extract type metadata before replacing inputs with test values
                input_types = {}
                if isinstance(ct_ir.get("inputs"), dict):
                    for key, spec in ct_ir["inputs"].items():
                        if isinstance(spec, dict) and "type" in spec:
                            input_types[key] = spec["type"]

                ct_ir["inputs"] = bindings
                if input_types:
                    ct_ir["input_types"] = input_types

                if "atom_stream" not in ct_ir and "atom_stream" in ct:
                    ct_ir["atom_stream"] = ct["atom_stream"]

                # Full Test IR instance
                test = {
                    "fqdn": f"{ct['fqdn_id']}::{case_id}",
                    "artifact_type": "CT_CONFORMANCE",
                    "ct_fqdn": ct["fqdn_id"],
                    "ct_ir": ct_ir,
                    "expected": expected,
                    "test_data_source": td["fqdn_id"],
                }
                if assertions:
                    test["assertions"] = assertions

                # Write test to disk
                try:
                    layer_code = ct.get("layer_code")

                    try:
                        conf_dir = resolver.resolve_output_path(
                            "conformance",
                            "COMPILER",
                            structure
                        )
                    except RuntimeError as e:
                        errors.append(
                            CompilerError(
                                code=ErrorCode.E301_WRITE_FAILED,
                                message=f"Failed to resolve conformance path from STRUCTURE: {e}",
                                phase="CONFORMANCE_GENERATE",
                                fqdn_id=ct["fqdn_id"],
                                artifact_code=ct_code,
                            )
                        )
                        continue

                    conf_dir.mkdir(parents=True, exist_ok=True)

                    # Naming rule: <fqdn>__<case_id>.json
                    filename = f"{ct['fqdn_id'].replace('::', '__')}__{case_id}.json"
                    output_path = conf_dir / filename

                    output_path.write_text(json.dumps(test, indent=2, sort_keys=True))
                    generated_tests.append(test)

                except Exception as e:
                    errors.append(
                        CompilerError(
                            code=ErrorCode.E301_WRITE_FAILED,
                            message=f"Failed to write conformance test: {e}",
                            phase="CONFORMANCE_GENERATE",
                            fqdn_id=ct["fqdn_id"],
                            artifact_code=ct_code,
                        )
                    )

    if errors:
        return PhaseResult(
            status=PhaseStatus.FAILED,
            outputs={"generated_tests": generated_tests},
            errors=tuple(errors),
        )
    else:
        return PhaseResult(
            status=PhaseStatus.SUCCESS,
            outputs={"generated_tests": generated_tests},
            errors=tuple(),
        )
