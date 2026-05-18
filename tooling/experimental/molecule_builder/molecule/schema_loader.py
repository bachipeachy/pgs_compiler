"""
schema_loader.py — Load molecule schema from pgs_governance.registry.

Governed by: CONSTITUTION_COMPILER_V0
"""

import json

from pgs_governance.structure.structure.resolution import paths
from pgs_compiler.tooling.experimental.molecule_builder.molecule.errors import CompileError


def load_molecule_schema() -> dict:
    """
    Load the canonical molecule schema from pgs_governance.registry.

    Uses SCHEMA_MOLECULE_V0 from registry/schemas/.
    """
    schema_path = paths.governance.schema("SCHEMA_MOLECULE_V0")
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CompileError(f"Molecule schema not found at {schema_path}")
    except json.JSONDecodeError as e:
        raise CompileError(f"Invalid JSON in molecule schema: {e}")


def load_ct_ir_schema() -> dict:
    """
    Load the CT-IR schema from pgs_governance.registry.

    Uses SCHEMA_CT_IR_V0 from registry/schemas/.
    """
    schema_path = paths.governance.schema("SCHEMA_CT_IR_V0")
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CompileError(f"CT-IR schema not found at {schema_path}")
    except json.JSONDecodeError as e:
        raise CompileError(f"Invalid JSON in CT-IR schema: {e}")
