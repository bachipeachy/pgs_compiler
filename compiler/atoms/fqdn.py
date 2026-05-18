"""
FQDN (Fully Qualified Domain Name) utilities.

Patch 1 Applied: FQDN is PRIMARY identity, never use artifact_code for uniqueness.

FQDN Format: {namespace}::{artifact_code}
Example: pgs_governance::CT_SCAN_ARTIFACTS_V0

Design:
- FQDN is PRIMARY identity (all references use FQDN)
- artifact_code is display/logging ONLY (not guaranteed unique)
- Namespace prevents collision across layers (e.g., pgs_governance, pgs_compiler)
- Parse/build functions for deterministic construction
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FQDN:
    """
    Fully Qualified Domain Name for artifact identity.

    CRITICAL: This is the PRIMARY identity.
    artifact_code alone is NOT sufficient (may collide).

    IMMUTABILITY GUARANTEE:
    - frozen=True prevents mutation
    - Always use str(fqdn) or fqdn.fqdn for identity
    - NEVER access .namespace or .artifact_code separately outside atoms layer
    - Prevents accidental reversion to partial identity

    Fields:
        namespace: Package/layer namespace (e.g., "pgs_governance") [INTERNAL]
        artifact_code: Short code (e.g., "CT_SCAN_V0") [INTERNAL]
        fqdn: Full identifier (namespace::artifact_code) [PUBLIC]
    """

    namespace: str
    artifact_code: str

    @property
    def fqdn(self) -> str:
        """
        Get full FQDN string.

        This is the ONLY public interface for identity.
        Use this, not namespace or artifact_code separately.
        """
        return f"{self.namespace}::{self.artifact_code}"

    def __str__(self) -> str:
        """
        String representation is the FQDN.

        Always use this for display/logging/comparison.
        """
        return self.fqdn

    def __hash__(self) -> int:
        """Hash by FQDN (for use in dicts/sets)."""
        return hash(self.fqdn)

    def __repr__(self) -> str:
        """Repr is also the FQDN (not internal components)."""
        return f"FQDN('{self.fqdn}')"


def parse_fqdn(fqdn_str: str) -> FQDN:
    """
    Parse FQDN string into components.

    Args:
        fqdn_str: FQDN string (namespace::artifact_code)

    Returns:
        FQDN object

    Raises:
        ValueError: If FQDN format invalid

    Examples:
        >>> parse_fqdn("pgs_governance::CT_SCAN_V0")
        FQDN(namespace='pgs_governance', artifact_code='CT_SCAN_V0')
    """
    if "::" not in fqdn_str:
        raise ValueError(
            f"Invalid FQDN format: '{fqdn_str}'\n"
            f"Expected: {{namespace}}::{{artifact_code}}\n"
            f"Example: pgs_governance::CT_SCAN_V0"
        )

    parts = fqdn_str.split("::", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid FQDN: '{fqdn_str}' (expected exactly one '::')")

    namespace, artifact_code = parts

    if not namespace:
        raise ValueError(f"Invalid FQDN: '{fqdn_str}' (empty namespace)")

    if not artifact_code:
        raise ValueError(f"Invalid FQDN: '{fqdn_str}' (empty artifact_code)")

    return FQDN(namespace=namespace, artifact_code=artifact_code)


def build_fqdn(source_path: Path, layer_root: Path, artifact_code: str) -> FQDN:
    """
    Build FQDN from source path and layer root.

    Derives namespace from directory structure:
    - Namespace = layer_root.name (e.g., pgs_governance, pgs_compiler)

    Args:
        source_path: Path to artifact source file
        layer_root: Root directory of layer
        artifact_code: Short code (e.g., CT_SCAN_V0)

    Returns:
        FQDN object

    Examples:
        >>> build_fqdn(
        ...     Path("/pgs/pgs_governance/registry/CT_FOO.md"),
        ...     Path("/pgs/pgs_governance"),
        ...     "CT_FOO_V0"
        ... )
        FQDN(namespace='pgs_governance', artifact_code='CT_FOO_V0')
    """
    # Namespace is derived from layer root directory name
    # This ensures uniqueness across different layers/repos
    namespace = layer_root.name

    return FQDN(namespace=namespace, artifact_code=artifact_code)


def extract_artifact_code(filename: str) -> str:
    """
    Extract artifact code from filename.

    Args:
        filename: Artifact filename (e.g., "CT_SCAN_V0.md")

    Returns:
        Artifact code without extension

    Examples:
        >>> extract_artifact_code("CT_SCAN_ARTIFACTS_V0.md")
        'CT_SCAN_ARTIFACTS_V0'
    """
    # Remove extension
    if filename.endswith(".md"):
        return filename[:-3]
    return filename


def validate_artifact_code(code: str) -> bool:
    """
    Validate artifact code format.

    Expected pattern: {TYPE}_{NAME}_V{VERSION}
    Examples: CT_SCAN_V0, WF_BUILD_V1

    Args:
        code: Artifact code to validate

    Returns:
        True if valid, False otherwise
    """
    # Pattern: TYPE_NAME_VN (where TYPE is 2-20 uppercase letters)
    pattern = r"^[A-Z]{2,20}_[A-Z0-9_]+_V\d+$"
    return bool(re.match(pattern, code))


def to_fqdn(ref: str, namespace: str) -> FQDN:
    """
    Normalize reference to FQDN.

    CRITICAL: All references MUST be FQDN.
    This helper converts partial references (artifact_code only) to full FQDN.

    Args:
        ref: Reference string (either "namespace::artifact_code" or "artifact_code")
        namespace: Default namespace if ref is partial

    Returns:
        FQDN object

    Examples:
        >>> to_fqdn("pgs_governance::CT_SCAN_V0", "fallback")
        FQDN('pgs_governance::CT_SCAN_V0')

        >>> to_fqdn("CT_SCAN_V0", "pgs_governance")
        FQDN('pgs_governance::CT_SCAN_V0')
    """
    if "::" in ref:
        # Already FQDN format
        return parse_fqdn(ref)
    else:
        # Partial reference (artifact_code only)
        return FQDN(namespace=namespace, artifact_code=ref)
