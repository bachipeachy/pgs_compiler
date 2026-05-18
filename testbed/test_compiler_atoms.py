"""
Compiler-layer atoms tests.

Verifies structural invariants of the compiler's own atom types:
- FQDN immutability and identity
- PhaseResult immutability
- CompilerError / ErrorCode
- Sorting and determinism utilities

These are pgs_compiler.compiler.atoms — compiler-internal data structures.
Not to be confused with capability atoms (CT transforms in pgs_capabilities).
"""

import sys
from contextlib import contextmanager

from pgs_compiler.compiler.atoms import (
    CompilerError,
    ErrorCode,
    FQDN,
    PhaseResult,
    PhaseStatus,
    build_fqdn,
    ensure_deterministic_output,
    parse_fqdn,
    require,
    require_not_none,
    sort_artifacts_by_fqdn,
)


@contextmanager
def assert_raises(exc_type):
    """Minimal raises helper — no pytest dependency."""
    try:
        yield
        raise AssertionError(f"Expected {exc_type.__name__} but nothing was raised")
    except exc_type:
        pass


def test_fqdn_immutability():
    fqdn = parse_fqdn("pkg_transforms::CT_FOO_V0")
    with assert_raises(AttributeError):
        fqdn.namespace = "different"
    with assert_raises(AttributeError):
        fqdn.artifact_code = "different"


def test_fqdn_primary_identity():
    fqdn = parse_fqdn("pkg_transforms::CT_FOO_V0")
    assert str(fqdn) == "pkg_transforms::CT_FOO_V0"
    assert repr(fqdn) == "FQDN('pkg_transforms::CT_FOO_V0')"


def test_fqdn_parse_roundtrip():
    original = "pkg_transforms::CT_FOO_V0"
    fqdn = parse_fqdn(original)
    assert str(fqdn) == original
    assert fqdn.namespace == "pkg_transforms"
    assert fqdn.artifact_code == "CT_FOO_V0"


def test_phase_result_immutability():
    result = PhaseResult(
        status=PhaseStatus.SUCCESS,
        outputs={"artifacts": []},
        errors=tuple(),
    )
    with assert_raises(AttributeError):
        result.status = PhaseStatus.FAILED
    with assert_raises(AttributeError):
        result.errors = tuple()


def test_error_code_centralized():
    assert ErrorCode.E001_NO_ARTIFACTS.value == "E001_NO_ARTIFACTS"
    assert ErrorCode.E201_MISSING_REFERENCE.value == "E201_MISSING_REFERENCE"


def test_require_invariant():
    # Should pass silently
    require(True, CompilerError(
        code=ErrorCode.E901_INTERNAL_ERROR,
        message="Should not raise",
        phase="TEST",
    ))
    # Should raise
    with assert_raises(CompilerError):
        require(False, CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message="Should raise",
            phase="TEST",
        ))


def test_require_not_none():
    value = require_not_none(42, CompilerError(
        code=ErrorCode.E902_CONFIG_ERROR,
        message="Should not raise",
        phase="TEST",
    ))
    assert value == 42
    with assert_raises(CompilerError):
        require_not_none(None, CompilerError(
            code=ErrorCode.E902_CONFIG_ERROR,
            message="Should raise",
            phase="TEST",
        ))


def test_sort_artifacts_by_fqdn():
    artifacts = [
        {"fqdn_id": "pkg_b::CT_FOO_V0", "name": "b"},
        {"fqdn_id": "pkg_a::CT_BAR_V0", "name": "a"},
        {"fqdn_id": "pkg_c::CT_BAZ_V0", "name": "c"},
    ]
    sorted_artifacts = sort_artifacts_by_fqdn(artifacts)
    assert [a["fqdn_id"] for a in sorted_artifacts] == [
        "pkg_a::CT_BAR_V0",
        "pkg_b::CT_FOO_V0",
        "pkg_c::CT_BAZ_V0",
    ]


def test_ensure_deterministic_output():
    obj = {
        "z_field": "last",
        "a_field": "first",
        "m_field": {"z": 3, "a": 1},
    }
    deterministic = ensure_deterministic_output(obj)
    assert list(deterministic.keys()) == ["a_field", "m_field", "z_field"]
    assert list(deterministic["m_field"].keys()) == ["a", "z"]


if __name__ == "__main__":
    tests = [
        test_fqdn_immutability,
        test_fqdn_primary_identity,
        test_fqdn_parse_roundtrip,
        test_phase_result_immutability,
        test_error_code_centralized,
        test_require_invariant,
        test_require_not_none,
        test_sort_artifacts_by_fqdn,
        test_ensure_deterministic_output,
    ]
    failed = []
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed.append(t.__name__)

    print()
    if failed:
        print(f"FAILED: {len(failed)}/{len(tests)}")
        sys.exit(1)
    else:
        print(f"PASSED: {len(tests)}/{len(tests)}")
