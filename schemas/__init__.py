"""
Schema validators for protocol artifacts.

NO PYDANTIC - explicit validation functions only.

Design:
- Each artifact type has its own validator
- Validators return List[CompilerError]
- No objects, no models, no magic
- Full control over what is valid

Validators:
- validate_ct: Capability Transform
- validate_cs: Capability Side-effect
- validate_cc: Capability Contract
- validate_wf: Workflow
- validate_rb: Runtime Binding
- validate_vocab: Vocabulary
- validate_constitution: Constitution
- validate_in: Intent
"""

from pgs_compiler.compiler.schemas.cc import validate_cc
from pgs_compiler.compiler.schemas.cs import validate_cs
from pgs_compiler.compiler.schemas.ct import validate_ct
from pgs_compiler.compiler.schemas.rb import validate_rb
from pgs_compiler.compiler.schemas.wf import validate_wf

__all__ = [
    "validate_ct",
    "validate_cs",
    "validate_cc",
    "validate_wf",
    "validate_rb",
]
