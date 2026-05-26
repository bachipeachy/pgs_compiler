"""
S9 ATTEST — Trust attestation for verified projections.

Input: State from S8 (verified flag set in stage_metadata)
Output: State with trust attestation written to disk

Produces structure_attestation.json — a trust boundary artifact asserting:
- which tokenized projection was attested (its real content hash)
- stub signing fields (algorithm, signature, key reference)
- attestation timestamp and version

This stage establishes the trust attestation architectural slot.
Real cryptographic signing (Ed25519, secp256k1) is deferred to post-v0.3.0.
The attestation_hash is a real SHA256 binding; only the signature is stub.

Invariant: only verified semantic projections become attestable artifacts.
S8_VERIFY must pass before S9_ATTEST runs.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pgs_governance.implementation.structure.resolution.layer_resolver import LayerResolver

from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.compiler.atoms.error_codes import ErrorCode
from pgs_compiler.compiler.projections import ProjectionType, get_structure_scope


_ATTESTATION_VERSION = "V0"
_STUB_ALGORITHM = "STUB"
_STUB_SIGNATURE = "STUB_NOT_CRYPTOGRAPHICALLY_SIGNED"
_STUB_KEY_REF = "STUB"


def s9_attest(state: State) -> State:
    """
    S9 ATTEST: Produce trust attestation for the verified tokenized projection.

    Writes structure_attestation.json to:
        <trust_attestation_path>/<structure_id>/structure_attestation.json

    The trust_attestation_path must be declared in the STRUCTURE
    output_configuration. The path follows the same pattern as
    tokenized_projection_path.

    State → State (with side effect: filesystem write).
    """
    state = state.with_stage("S9_ATTEST")
    trace: list[TraceEvent] = []

    # Gate: only attest verified structures
    verified = state.stage_metadata.get("verified", False)
    if not verified:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message="S9_ATTEST requires a verified state — S8_VERIFY must have passed",
            phase="S9_ATTEST",
        ))

    tokenized = state.get_projection(ProjectionType.TOKENIZED.value)
    if tokenized is None:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message="S9_ATTEST requires tokenized projection — S6_PROJECT must have run",
            phase="S9_ATTEST",
        ))

    structure_config = dict(state.structure_config)
    structure_id = get_structure_scope(structure_config)
    if not structure_id:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message="S9_ATTEST: cannot determine structure identity from structure_config",
            phase="S9_ATTEST",
        ))

    # Resolve trust output root from STRUCTURE config
    output_config = structure_config.get("output_configuration", {})
    if "trust_attestation_path" not in output_config:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message=(
                "S9_ATTEST: trust_attestation_path not declared in STRUCTURE "
                "output_configuration — add it before running S9"
            ),
            phase="S9_ATTEST",
        ))

    resolver = LayerResolver()
    try:
        trust_root = resolver.resolve_output_path(
            "trust_attestation_path",
            "",
            structure_config,
        )
    except (RuntimeError, ValueError) as e:
        return state.with_errors(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"S9_ATTEST: failed to resolve trust_attestation_path: {e}",
            phase="S9_ATTEST",
        ))

    # Structure-specific subdirectory: <trust_root>/<structure_id>/
    structure_dir = trust_root / structure_id
    try:
        structure_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return state.with_errors(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"S9_ATTEST: failed to create trust directory {structure_dir}: {e}",
            phase="S9_ATTEST",
        ))

    # Attestation binding: real SHA256 of the tokenized projection hash
    tokenized_projection_hash = tokenized.metadata.projection_hash
    attestation_hash = hashlib.sha256(
        tokenized_projection_hash.encode("utf-8")
    ).hexdigest()

    attestation: dict[str, Any] = {
        "structure_id": structure_id,
        "attestation_version": _ATTESTATION_VERSION,
        "tokenized_projection_hash": tokenized_projection_hash,
        "attestation_hash": attestation_hash,
        "signing_algorithm": _STUB_ALGORITHM,
        "signature": _STUB_SIGNATURE,
        "public_key_ref": _STUB_KEY_REF,
        "signed_at": datetime.now(timezone.utc).isoformat(),
    }

    output_path = structure_dir / "structure_attestation.json"
    try:
        json_content = json.dumps(attestation, indent=2, sort_keys=True)
        temp_path = output_path.with_suffix(".tmp")
        temp_path.write_text(json_content, encoding="utf-8")
        temp_path.replace(output_path)
    except Exception as e:
        return state.with_errors(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"S9_ATTEST: failed to write structure_attestation.json: {e}",
            phase="S9_ATTEST",
        ))

    # Register attestation file in materialized paths
    state = state.with_materialized_paths(
        state.materialized_paths + (str(output_path),)
    )

    trace.append(TraceEvent.create(
        stage="S9_ATTEST",
        operation="attestation_complete",
        subject_fqdn=structure_id,
        detail={
            "structure_id": structure_id,
            "attestation_hash": attestation_hash,
            "tokenized_projection_hash": tokenized_projection_hash,
            "signing_algorithm": _STUB_ALGORITHM,
            "output_path": str(output_path),
        },
        family=EventFamily.ATTESTATION.value,
    ))

    if trace:
        state = state.with_trace_events(*trace)

    state = state.with_metadata("attested", True)
    state = state.with_metadata("attestation_hash", attestation_hash)

    return state
