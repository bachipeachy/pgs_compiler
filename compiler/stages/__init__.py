"""
Compilation stages.

Each stage is a pure function: State → State.
Stages execute in fixed order: S1 through S9.
"""

from pgs_compiler.compiler.stages.s1_extract import s1_extract
from pgs_compiler.compiler.stages.s2_canonicalize import s2_canonicalize
from pgs_compiler.compiler.stages.s3_semantic_addressing import s3_semantic_addressing
from pgs_compiler.compiler.stages.s4_govern import s4_govern
from pgs_compiler.compiler.stages.s5_construct import s5_construct
from pgs_compiler.compiler.stages.s6_project import s6_project
from pgs_compiler.compiler.stages.s7_materialize import s7_materialize
from pgs_compiler.compiler.stages.s8_verify import s8_verify
from pgs_compiler.compiler.stages.s9_attest import s9_attest

__all__ = [
    "s1_extract",
    "s2_canonicalize",
    "s3_semantic_addressing",
    "s4_govern",
    "s5_construct",
    "s6_project",
    "s7_materialize",
    "s8_verify",
    "s9_attest",
]
