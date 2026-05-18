"""
Centralized error code registry.

All error codes in one place to prevent:
- String drift
- Inconsistent reporting
- Duplicate codes
- Missing documentation

Add new codes here, never inline in phase code.
"""

from enum import Enum


class ErrorCode(Enum):
    """
    Error codes for trad-compiler.

    Organized by phase:
    - E0xx: Discovery errors
    - E1xx: Parse errors
    - E2xx: Validation errors
    - E3xx: Materialization errors
    - E4xx: Verification errors
    - E7xx: ASSERT errors
    - E8xx: Conformance errors
    - E9xx: Internal/system errors
    """

    # ==================
    # Discovery (E0xx)
    # ==================
    E001_NO_ARTIFACTS = "E001_NO_ARTIFACTS"
    """No artifacts found in search path."""

    E002_DUPLICATE_FQDN = "E002_DUPLICATE_FQDN"
    """Duplicate FQDN detected (collision)."""

    E003_INVALID_FILENAME = "E003_INVALID_FILENAME"
    """Invalid filename pattern."""

    E004_CROSS_REPO_REF = "E004_CROSS_REPO_REF"
    """Cross-repo reference detected (source_path outside input_dir)."""

    # ==================
    # Parse (E1xx)
    # ==================
    E101_INVALID_YAML = "E101_INVALID_YAML"
    """Invalid YAML frontmatter."""

    E102_MISSING_FIELD = "E102_MISSING_FIELD"
    """Missing required field."""

    E103_TYPE_MISMATCH = "E103_TYPE_MISMATCH"
    """Field type mismatch."""

    E104_INVALID_FQDN = "E104_INVALID_FQDN"
    """Invalid FQDN format."""

    # ==================
    # Validation (E2xx)
    # ==================
    E201_MISSING_REFERENCE = "E201_MISSING_REFERENCE"
    """Reference to non-existent artifact (FQDN not found)."""

    E202_CIRCULAR_DEPENDENCY = "E202_CIRCULAR_DEPENDENCY"
    """Circular dependency detected (A→B→A)."""

    E203_SCHEMA_INVALID = "E203_SCHEMA_INVALID"
    """Schema validation failed (Pydantic error)."""

    E204_INVALID_RB_BINDING = "E204_INVALID_RB_BINDING"
    """RB references invalid CS artifact."""

    E205_CT_VALIDATION_FAILED = "E205_CT_VALIDATION_FAILED"
    """CT-IR validation failed."""

    # ==================
    # Materialization (E3xx)
    # ==================
    E301_WRITE_FAILED = "E301_WRITE_FAILED"
    """Failed to write output file."""

    E302_JSON_SERIALIZE_FAILED = "E302_JSON_SERIALIZE_FAILED"
    """JSON serialization failed."""

    # ==================
    # Verification (E4xx)
    # ==================
    E401_MISSING_OUTPUT = "E401_MISSING_OUTPUT"
    """Expected output file not found."""

    E402_UNDECLARED_OUTPUT = "E402_UNDECLARED_OUTPUT"
    """Output file not in manifest."""

    E403_OUTPUT_MISMATCH = "E403_OUTPUT_MISMATCH"
    """Output doesn't match expected schema."""

    # ==================
    # ASSERT Phase (E701-E750)
    # ==================
    E701_ASSERTION_FAILURE = "E701"
    """Assertion violations detected."""

    E702_UNKNOWN_ASSERT = "E702"
    """No executor for ASSERT artifact."""

    E703_MALFORMED_ASSERT = "E703"
    """ASSERT artifact schema violation."""

    # ==================
    # Conformance (E8xx)
    # ==================
    E801_TEST_DATA_MISSING = "E801"
    """Test data missing for CT."""

    E802_CONFORMANCE_FAILURE = "E802"
    """CT conformance test failed."""

    E803_TEST_DATA_INVALID = "E803"
    """TEST_DATA does not match CT contract."""

    # ==================
    # Internal (E9xx)
    # ==================
    E901_INTERNAL_ERROR = "E901_INTERNAL_ERROR"
    """Internal compiler error (bug)."""

    E902_CONFIG_ERROR = "E902_CONFIG_ERROR"
    """Configuration error."""


# Error suggestions (actionable fixes)
ERROR_SUGGESTIONS: dict[ErrorCode, str] = {
    ErrorCode.E001_NO_ARTIFACTS: "Check input directory path and artifact_types config",
    ErrorCode.E002_DUPLICATE_FQDN: "Rename artifact or change namespace to make FQDN unique",
    ErrorCode.E003_INVALID_FILENAME: "Ensure filename matches pattern: {TYPE}_{NAME}_V{N}.md",
    ErrorCode.E004_CROSS_REPO_REF: "Move artifact into input_dir or remove reference",
    ErrorCode.E101_INVALID_YAML: "Check YAML syntax, ensure proper indentation",
    ErrorCode.E102_MISSING_FIELD: "Add required field to artifact frontmatter",
    ErrorCode.E104_INVALID_FQDN: "FQDN format: {namespace}::{artifact_code}",
    ErrorCode.E201_MISSING_REFERENCE: "Add referenced artifact or remove reference",
    ErrorCode.E202_CIRCULAR_DEPENDENCY: "Break dependency cycle between artifacts",
    ErrorCode.E204_INVALID_RB_BINDING: "Ensure RB references valid CS artifact",
    ErrorCode.E205_CT_VALIDATION_FAILED: "Check CT atom_stream and purity constraints",
    ErrorCode.E301_WRITE_FAILED: "Check output directory permissions and disk space",
    ErrorCode.E401_MISSING_OUTPUT: "Check materialization phase completed successfully",
    ErrorCode.E402_UNDECLARED_OUTPUT: "Remove stale file or add to expected outputs",
    ErrorCode.E701_ASSERTION_FAILURE: "Fix detected violations in protocol artifacts",
    ErrorCode.E702_UNKNOWN_ASSERT: "Ensure an executor is registered for this ASSERT artifact",
    ErrorCode.E703_MALFORMED_ASSERT: "Check ASSERT artifact against CONSTITUTION_ASSERT_V0",
    ErrorCode.E801_TEST_DATA_MISSING: "Create TEST_DATA artifact for the CT",
    ErrorCode.E802_CONFORMANCE_FAILURE: "Debug CT implementation to match expected behavior",
    ErrorCode.E803_TEST_DATA_INVALID: "Fix TEST_DATA bindings to match CT inputs contract",
}
