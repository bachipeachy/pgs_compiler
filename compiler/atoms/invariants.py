"""
Lightweight invariant enforcement.

NOT the PGS ASSERT framework - just simple fail-fast helpers.

Design:
- Simple condition checking
- Raises CompilerError on violation
- No protocol semantics
- No registry hooks
- Just: if not condition → error
"""

from .errors import CompilerError


def require(condition: bool, error: CompilerError) -> None:
    """
    Require condition to be true, raise error if false.

    Lightweight assertion for fail-fast enforcement.
    NOT PGS ASSERT framework - no protocol semantics.

    Args:
        condition: Boolean condition that must be true
        error: Error to raise if condition is false

    Raises:
        CompilerError: If condition is false

    Examples:
        >>> require(
        ...     fqdn_id in artifacts,
        ...     CompilerError(
        ...         code=ErrorCode.E201_MISSING_REFERENCE,
        ...         message=f"Reference {fqdn_id} not found",
        ...         phase="VALIDATE"
        ...     )
        ... )
    """
    if not condition:
        raise error


def require_not_none(value: any, error: CompilerError) -> any:
    """
    Require value is not None, raise error if None.

    Args:
        value: Value to check
        error: Error to raise if value is None

    Returns:
        value (if not None)

    Raises:
        CompilerError: If value is None

    Examples:
        >>> config = require_not_none(
        ...     config_dict.get("artifact_types"),
        ...     CompilerError(
        ...         code=ErrorCode.E902_CONFIG_ERROR,
        ...         message="Missing required config: artifact_types",
        ...         phase="CONFIG"
        ...     )
        ... )
    """
    if value is None:
        raise error
    return value


def require_exists(path: "Path", error: CompilerError) -> "Path":
    """
    Require path exists, raise error if not.

    Args:
        path: Path to check
        error: Error to raise if path doesn't exist

    Returns:
        path (if exists)

    Raises:
        CompilerError: If path doesn't exist

    Examples:
        >>> input_dir = require_exists(
        ...     Path(args.input_dir),
        ...     CompilerError(
        ...         code=ErrorCode.E001_NO_ARTIFACTS,
        ...         message=f"Input directory not found: {args.input_dir}",
        ...         phase="DISCOVERY"
        ...     )
        ... )
    """
    from pathlib import Path

    if not isinstance(path, Path):
        path = Path(path)

    if not path.exists():
        raise error

    return path
