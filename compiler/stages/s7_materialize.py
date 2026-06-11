"""
S7 MATERIALIZE — Write projected artifacts to disk.

Input: State from S6 (projections populated)
Output: State with materialized_paths populated

Writes each projected artifact as deterministic JSON to the STRUCTURE-driven
output directory. Handles:
- STRUCTURE-driven path resolution via LayerResolver
- Artifact type → directory mapping
- Atomic writes (temp file + rename)
- Post-materialization workflow graph generation (best-effort)
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from pgs_governance.implementation.structure.resolution.layer_resolver import LayerResolver
from pgs_governance.implementation.structure.loading.protocol_loader import _get_artifact_type_dir_from_prefix

from pgs_compiler.compiler.graph.types import NodeKind
from pgs_compiler.compiler.graph.graph import Graph
from pgs_compiler.compiler.graph.state import State
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily, EvidenceGraph
from pgs_compiler.compiler.graph.hashing import compute_projection_hash
from pgs_compiler.compiler.atoms.errors import CompilerError
from pgs_compiler.compiler.atoms.error_codes import ErrorCode
from pgs_compiler.compiler.projections import (
    COMPILER_VERSION,
    ProjectionClass,
    ProjectionType,
    Projection,
    get_structure_scope,
)


def s7_materialize(state: State) -> State:
    """
    S7 MATERIALIZE: Write projected artifacts to disk.

    State → State (with side effect: filesystem writes).
    """
    state = state.with_stage("S7_MATERIALIZE")
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []
    materialized: list[str] = []

    # Unwrap canonical projection — content is {fqdn: artifact_dict}
    canonical = state.get_projection(ProjectionType.CANONICAL.value)
    if canonical is None:
        return state.with_errors(CompilerError(
            code=ErrorCode.E901_INTERNAL_ERROR,
            message="No canonical projection to materialize (S6 PROJECT may have failed)",
            phase="S7_MATERIALIZE",
        ))
    projections = canonical.content

    structure_config = dict(state.structure_config)

    resolver = LayerResolver()

    for fqdn in sorted(projections.keys()):
        artifact = projections[fqdn]
        artifact_type = artifact.get("artifact_type", "")
        artifact_code = artifact.get("artifact_code", "")
        layer_code = artifact.get("layer_code", "")
        domain_name = artifact.get("domain_name")

        if not layer_code:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message="Artifact missing layer_code",
                phase="S7_MATERIALIZE",
                fqdn_id=fqdn,
            ))
            continue

        # Resolve output directory via STRUCTURE
        try:
            artifact_output_dir = resolver.resolve_output_path(
                "layer_outputs",
                layer_code,
                structure_config,
                domain=domain_name,
            )
        except (RuntimeError, ValueError) as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Failed to resolve output path: {e}",
                phase="S7_MATERIALIZE",
                fqdn_id=fqdn,
            ))
            continue

        # Build output path
        encoded_fqdn = fqdn.replace("::", "__")
        try:
            type_dir_name = _get_artifact_type_dir_from_prefix(artifact_type)
        except ValueError as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Unknown artifact type for directory mapping: {e}",
                phase="S7_MATERIALIZE",
                fqdn_id=fqdn,
            ))
            continue

        type_dir = artifact_output_dir / type_dir_name
        output_path = type_dir / f"{encoded_fqdn}.json"

        # Create directory
        try:
            type_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Failed to create directory: {e}",
                phase="S7_MATERIALIZE",
                fqdn_id=fqdn,
            ))
            continue

        # Serialize
        try:
            json_content = json.dumps(artifact, indent=2, sort_keys=True)
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E302_JSON_SERIALIZE_FAILED,
                message=f"JSON serialization failed: {e}",
                phase="S7_MATERIALIZE",
                fqdn_id=fqdn,
            ))
            continue

        # Atomic write
        try:
            temp_path = output_path.with_suffix(".tmp")
            temp_path.write_text(json_content, encoding="utf-8")
            temp_path.replace(output_path)
            materialized.append(str(output_path))
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Failed to write: {e}",
                phase="S7_MATERIALIZE",
                fqdn_id=fqdn,
            ))
            continue

        trace.append(TraceEvent.create(
            stage="S7_MATERIALIZE",
            operation="artifact_written",
            subject_fqdn=fqdn,
            detail={"output_path": str(output_path), "artifact_type": artifact_type},
            family=EventFamily.MATERIALIZATION.value,
        ))

    # Post-materialization: generate conformance tests from TEST_DATA
    conf_paths, conf_errors, conf_trace = _generate_conformance_tests(
        state.graph, projections, structure_config, resolver
    )
    materialized.extend(conf_paths)
    errors.extend(conf_errors)
    trace.extend(conf_trace)

    # Post-materialization: generate workflow graphs into behavior_logic/ (best-effort)
    graph_warnings = _generate_workflow_graphs(projections, structure_config, resolver)
    if graph_warnings:
        state = state.with_warnings(*(
            CompilerError(code=ErrorCode.E901_INTERNAL_ERROR, message=w, phase="S7_MATERIALIZE")
            for w in graph_warnings
        ))

    # Write metadata.json for canonical projection
    meta_paths, meta_errors = _write_projection_metadata(canonical, materialized, structure_config, resolver)
    materialized.extend(meta_paths)
    errors.extend(meta_errors)

    # Materialize vocabulary projection (per-structure address space)
    vocabulary = state.get_projection(ProjectionType.VOCABULARY.value)
    if vocabulary is not None:
        vocab_paths, vocab_errors, vocab_trace = _materialize_vocabulary(
            vocabulary, structure_config, resolver,
        )
        materialized.extend(vocab_paths)
        errors.extend(vocab_errors)
        trace.extend(vocab_trace)

    # Materialize tokenized topology projection (per-structure machine realization)
    tokenized = state.get_projection(ProjectionType.TOKENIZED.value)
    if tokenized is not None:
        vocabulary_hash = vocabulary.metadata.projection_hash if vocabulary else ""
        tok_paths, tok_errors, tok_trace = _materialize_tokenized(
            tokenized, structure_config, resolver, vocabulary_hash,
        )
        materialized.extend(tok_paths)
        errors.extend(tok_errors)
        trace.extend(tok_trace)

    # Materialize dispatch + handlers projections (token-native runtime substrate)
    dispatch = state.get_projection(ProjectionType.DISPATCH.value)
    handlers = state.get_projection(ProjectionType.HANDLERS.value)
    if dispatch is not None or handlers is not None:
        dis_paths, dis_errors, dis_trace = _materialize_dispatch_and_handlers(
            dispatch, handlers, structure_config, resolver,
        )
        materialized.extend(dis_paths)
        errors.extend(dis_errors)
        trace.extend(dis_trace)

    # Materialize evidence projection (per-structure dual-form substrate)
    evidence = state.get_projection(ProjectionType.EVIDENCE.value)
    if evidence is not None:
        vocabulary_hash_evi = vocabulary.metadata.projection_hash if vocabulary else ""
        tokenized_hash_evi = tokenized.metadata.projection_hash if tokenized else ""
        evi_paths, evi_errors, evi_trace = _materialize_evidence(
            evidence, structure_config, resolver, vocabulary_hash_evi, tokenized_hash_evi,
        )
        materialized.extend(evi_paths)
        errors.extend(evi_errors)
        trace.extend(evi_trace)

    # Flush accumulated errors and trace events so EvidenceGraph captures S1-S7
    if errors:
        state = state.with_errors(*errors)
    if trace:
        state = state.with_trace_events(*trace)
    errors = []
    trace = []

    # Materialize EvidenceGraph (compile trace substrate — S1-S7 events)
    eg_paths, eg_errors, eg_trace = _materialize_evidence_graph(
        state, structure_config, resolver,
    )
    materialized.extend(eg_paths)
    errors.extend(eg_errors)
    trace.extend(eg_trace)

    # Materialize evidence views (visualization PNGs — best-effort, written after evidence_graph.json)
    if eg_paths:
        view_warnings = _materialize_evidence_views(eg_paths[0], structure_config, resolver)
        for w in view_warnings:
            state = state.with_warnings(CompilerError(
                code=ErrorCode.E901_INTERNAL_ERROR,
                message=w,
                phase="S7_MATERIALIZE",
            ))

    materialized_sorted = tuple(sorted(materialized))
    state = state.with_materialized_paths(materialized_sorted)

    if errors:
        state = state.with_errors(*errors)
    if trace:
        state = state.with_trace_events(*trace)

    state = state.with_metadata("materialized_count", len(materialized_sorted))

    return state


def _write_projection_metadata(
    projection: Any,
    materialized: list[str],
    structure_config: dict[str, Any],
    resolver: LayerResolver,
) -> tuple[list[str], list[CompilerError]]:
    """
    Write metadata.json for a projection to each output root directory.

    Determines output roots from the STRUCTURE layer_outputs configuration.
    metadata.json sits alongside artifact type directories in each
    compiled output root.
    """
    written: list[str] = []
    errors: list[CompilerError] = []

    if not materialized:
        return written, errors

    meta_dict = projection.metadata.to_dict()

    # Collect all output roots from STRUCTURE layer_outputs
    layer_outputs = structure_config.get("output_configuration", {}).get("layer_outputs", {})
    output_roots: set[Path] = set()

    for layer_code, layer_config in layer_outputs.items():
        domain = layer_config.get("domain") if isinstance(layer_config, dict) else None
        layer_dir = resolver.resolve_output_path(
            "layer_outputs", layer_code, structure_config,
            domain=domain,
        )
        if layer_dir.exists():
            output_roots.add(layer_dir)

    for output_root in sorted(output_roots):
        meta_path = output_root / "metadata.json"
        try:
            meta_json = json.dumps(meta_dict, indent=2, sort_keys=True)
            temp_path = meta_path.with_suffix(".tmp")
            temp_path.write_text(meta_json, encoding="utf-8")
            temp_path.replace(meta_path)
            written.append(str(meta_path))
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Failed to write projection metadata to {output_root}: {e}",
                phase="S7_MATERIALIZE",
            ))

    return written, errors


def _materialize_vocabulary(
    vocabulary: Projection,
    structure_config: dict[str, Any],
    resolver: LayerResolver,
) -> tuple[list[str], list[CompilerError], list[TraceEvent]]:
    """
    Materialize vocabulary projection as per-structure JSON files.

    Writes to STRUCTURE-resolved vocabulary output path under a
    structure-identity subdirectory:
        <vocabulary_root>/<structure_id>/forward.json
        <vocabulary_root>/<structure_id>/reverse.json
        <vocabulary_root>/<structure_id>/metadata.json
    """
    written: list[str] = []
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []

    structure_id = get_structure_scope(structure_config)
    if not structure_id:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize vocabulary: unknown structure identity",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Resolve vocabulary output root from STRUCTURE config
    output_config = structure_config.get("output_configuration", {})
    vocab_config = output_config.get("vocabulary_projection_path")
    if not vocab_config:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize vocabulary: no vocabulary_projection_path in STRUCTURE",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    try:
        vocab_root = resolver.resolve_output_path(
            "vocabulary_projection_path",
            "",  # not used for non-layer_outputs types
            structure_config,
        )
    except (RuntimeError, ValueError) as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to resolve vocabulary output path: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Structure-specific subdirectory
    structure_dir = vocab_root / structure_id
    try:
        structure_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to create vocabulary directory: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Write forward.json, reverse.json, metadata.json
    # Note: forward/reverse are flat lookup tables (hex_addr → FQDN).
    # projection_class is NOT embedded in them — adding a non-address key
    # would pollute the table and break runtime loaders.
    # S8 skips them by projection_type declared in sibling metadata.json.
    files_to_write = {
        "forward.json": vocabulary.content.get("forward", {}),
        "reverse.json": vocabulary.content.get("reverse", {}),
        "metadata.json": {
            **vocabulary.metadata.to_dict(),
            "structure_id": structure_id,
            "allocation_strategy": "deterministic_fqdn_order",
            "address_count": len(vocabulary.content.get("forward", {})),
        },
    }

    for filename, data in files_to_write.items():
        output_path = structure_dir / filename
        try:
            json_content = json.dumps(data, indent=2, sort_keys=True)
            temp_path = output_path.with_suffix(".tmp")
            temp_path.write_text(json_content, encoding="utf-8")
            temp_path.replace(output_path)
            written.append(str(output_path))
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Failed to write vocabulary {filename}: {e}",
                phase="S7_MATERIALIZE",
            ))

    if written:
        trace.append(TraceEvent.create(
            stage="S7_MATERIALIZE",
            operation="vocabulary_materialized",
            detail={
                "structure_id": structure_id,
                "output_dir": str(structure_dir),
                "files_written": len(written),
            },
            family=EventFamily.MATERIALIZATION.value,
        ))

    return written, errors, trace


def _materialize_tokenized(
    tokenized: Projection,
    structure_config: dict[str, Any],
    resolver: LayerResolver,
    vocabulary_hash: str,
) -> tuple[list[str], list[CompilerError], list[TraceEvent]]:
    """
    Materialize tokenized topology projection as per-structure JSON files.

    Writes to STRUCTURE-resolved tokenized output path under a
    structure-identity subdirectory:
        <tokenized_root>/<structure_id>/topology.json
        <tokenized_root>/<structure_id>/metadata.json
    """
    written: list[str] = []
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []

    structure_id = get_structure_scope(structure_config)
    if not structure_id:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize tokenized: unknown structure identity",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Resolve tokenized output root from STRUCTURE config
    output_config = structure_config.get("output_configuration", {})
    tok_config = output_config.get("tokenized_projection_path")
    if not tok_config:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize tokenized: no tokenized_projection_path in STRUCTURE",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    try:
        tok_root = resolver.resolve_output_path(
            "tokenized_projection_path",
            "",  # not used for non-layer_outputs types
            structure_config,
        )
    except (RuntimeError, ValueError) as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to resolve tokenized output path: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Structure-specific subdirectory
    structure_dir = tok_root / structure_id
    try:
        structure_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to create tokenized directory: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Write topology.json and metadata.json
    nodes = tokenized.content.get("nodes", [])
    edges = tokenized.content.get("edges", [])

    files_to_write = {
        "topology.json": {
            "projection_class": tokenized.metadata.projection_class.value,
            "nodes": list(nodes),
            "edges": list(edges),
            "adjacency": dict(tokenized.content.get("adjacency", {})),
        },
        "metadata.json": {
            **tokenized.metadata.to_dict(),
            "structure_id": structure_id,
            "vocabulary_hash": vocabulary_hash,
            "allocation_strategy": "deterministic_fqdn_order",
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }

    for filename, data in files_to_write.items():
        output_path = structure_dir / filename
        try:
            json_content = json.dumps(data, indent=2, sort_keys=True)
            temp_path = output_path.with_suffix(".tmp")
            temp_path.write_text(json_content, encoding="utf-8")
            temp_path.replace(output_path)
            written.append(str(output_path))
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Failed to write tokenized {filename}: {e}",
                phase="S7_MATERIALIZE",
            ))

    if written:
        trace.append(TraceEvent.create(
            stage="S7_MATERIALIZE",
            operation="tokenized_materialized",
            detail={
                "structure_id": structure_id,
                "output_dir": str(structure_dir),
                "files_written": len(written),
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
            family=EventFamily.MATERIALIZATION.value,
        ))

    return written, errors, trace


def _materialize_dispatch_and_handlers(
    dispatch: Projection | None,
    handlers: Projection | None,
    structure_config: dict[str, Any],
    resolver: LayerResolver,
) -> tuple[list[str], list[CompilerError], list[TraceEvent]]:
    """
    Materialize dispatch.json and handlers.json into the tokenized_snapshot directory.

    Both files land alongside topology.json in:
        <tokenized_root>/<structure_id>/dispatch.json
        <tokenized_root>/<structure_id>/handlers.json

    Uses the same tokenized_projection_path resolver as _materialize_tokenized.
    Writes atomically (temp + rename). Skips gracefully if either projection is None.
    """
    written: list[str] = []
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []

    structure_id = get_structure_scope(structure_config)
    if not structure_id:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize dispatch/handlers: unknown structure identity",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    try:
        tok_root = resolver.resolve_output_path(
            "tokenized_projection_path",
            "",
            structure_config,
        )
    except (RuntimeError, ValueError) as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to resolve tokenized output path for dispatch/handlers: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    structure_dir = tok_root / structure_id
    try:
        structure_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to create tokenized directory for dispatch/handlers: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    files_to_write: dict[str, Any] = {}

    if dispatch is not None:
        files_to_write["dispatch.json"] = {
            "projection_class": dispatch.metadata.projection_class.value,
            "routing":   dict(dispatch.content.get("routing", {})),
            "pipeline":  dict(dispatch.content.get("pipeline", {})),
            "entry":     dict(dispatch.content.get("entry", {})),
            "bindings":  dict(dispatch.content.get("bindings", {})),
        }

    if handlers is not None:
        files_to_write["handlers.json"] = {
            "projection_class": handlers.metadata.projection_class.value,
            "ct":        dict(handlers.content.get("ct", {})),
            "cs":        dict(handlers.content.get("cs", {})),
            "rb_policy": dict(handlers.content.get("rb_policy", {})),
        }

    for filename, data in files_to_write.items():
        output_path = structure_dir / filename
        try:
            json_content = json.dumps(data, indent=2, sort_keys=True)
            temp_path = output_path.with_suffix(".tmp")
            temp_path.write_text(json_content, encoding="utf-8")
            temp_path.replace(output_path)
            written.append(str(output_path))
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Failed to write {filename}: {e}",
                phase="S7_MATERIALIZE",
            ))

    if written:
        trace.append(TraceEvent.create(
            stage="S7_MATERIALIZE",
            operation="dispatch_handlers_materialized",
            detail={
                "structure_id": structure_id,
                "output_dir": str(structure_dir),
                "files_written": written,
            },
            family=EventFamily.MATERIALIZATION.value,
        ))

    return written, errors, trace


def _materialize_evidence(
    evidence: Projection,
    structure_config: dict[str, Any],
    resolver: LayerResolver,
    vocabulary_hash: str,
    tokenized_hash: str,
) -> tuple[list[str], list[CompilerError], list[TraceEvent]]:
    """
    Materialize evidence projection as per-structure JSON files.

    Writes to STRUCTURE-resolved evidence output path under a
    structure-identity subdirectory:
        <evidence_root>/<structure_id>/evidence.json
        <evidence_root>/<structure_id>/metadata.json
    """
    written: list[str] = []
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []

    structure_id = get_structure_scope(structure_config)
    if not structure_id:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize evidence: unknown structure identity",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Resolve evidence output root from STRUCTURE config
    output_config = structure_config.get("output_configuration", {})
    evi_config = output_config.get("evidence_projection_path")
    if not evi_config:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize evidence: no evidence_projection_path in STRUCTURE",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    try:
        evi_root = resolver.resolve_output_path(
            "evidence_projection_path",
            "",
            structure_config,
        )
    except (RuntimeError, ValueError) as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to resolve evidence output path: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Structure-specific subdirectory
    structure_dir = evi_root / structure_id
    try:
        structure_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to create evidence directory: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Write evidence.json and metadata.json
    nodes = list(evidence.content.get("nodes", []))
    edges = list(evidence.content.get("edges", []))
    event_catalog = list(evidence.content.get("event_catalog", []))

    files_to_write = {
        "evidence.json": {
            "projection_class": evidence.metadata.projection_class.value,
            "nodes": nodes,
            "edges": edges,
            "event_catalog": event_catalog,
        },
        "metadata.json": {
            **evidence.metadata.to_dict(),
            "structure_id": structure_id,
            "vocabulary_hash": vocabulary_hash,
            "tokenized_hash": tokenized_hash,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "ev_schema_count": len(event_catalog),
        },
    }

    for filename, data in files_to_write.items():
        output_path = structure_dir / filename
        try:
            json_content = json.dumps(data, indent=2, sort_keys=True)
            temp_path = output_path.with_suffix(".tmp")
            temp_path.write_text(json_content, encoding="utf-8")
            temp_path.replace(output_path)
            written.append(str(output_path))
        except Exception as e:
            errors.append(CompilerError(
                code=ErrorCode.E301_WRITE_FAILED,
                message=f"Failed to write evidence {filename}: {e}",
                phase="S7_MATERIALIZE",
            ))

    if written:
        trace.append(TraceEvent.create(
            stage="S7_MATERIALIZE",
            operation="evidence_materialized",
            detail={
                "structure_id": structure_id,
                "output_dir": str(structure_dir),
                "files_written": len(written),
                "node_count": len(nodes),
                "edge_count": len(edges),
                "ev_schema_count": len(event_catalog),
            },
            family=EventFamily.MATERIALIZATION.value,
        ))

    return written, errors, trace


def _materialize_evidence_graph(
    state: State,
    structure_config: dict[str, Any],
    resolver: LayerResolver,
) -> tuple[list[str], list[CompilerError], list[TraceEvent]]:
    """
    Materialize EvidenceGraph as compile trace substrate.

    Builds EvidenceGraph from accumulated trace events (S1-S7) and writes
    to evidence_snapshot/<structure_id>/evidence_graph.json.

    Writes:
        <evidence_root>/<structure_id>/evidence_graph.json
    """
    written: list[str] = []
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []

    structure_id = get_structure_scope(structure_config)
    if not structure_id:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize evidence graph: unknown structure identity",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Resolve evidence output root from STRUCTURE config
    output_config = structure_config.get("output_configuration", {})
    evi_config = output_config.get("evidence_projection_path")
    if not evi_config:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message="Cannot materialize evidence graph: no evidence_projection_path in STRUCTURE",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    try:
        evi_root = resolver.resolve_output_path(
            "evidence_projection_path",
            "",
            structure_config,
        )
    except (RuntimeError, ValueError) as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to resolve evidence graph output path: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    structure_dir = evi_root / structure_id
    try:
        structure_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to create evidence graph directory: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    # Build EvidenceGraph from all trace events accumulated so far (S1-S7)
    eg = EvidenceGraph.from_trace_events(state.trace_events)

    # Hash the core content (events + edges + families) — envelope fields excluded
    eg_content = eg.to_dict()
    evidence_graph_hash = compute_projection_hash(eg_content)

    data = {
        "projection_class": ProjectionClass.EVIDENCE_SUBSTRATE.value,
        **eg_content,
        "evidence_graph_hash": evidence_graph_hash,
        "structure_id": structure_id,
        "compiler_version": COMPILER_VERSION,
    }

    output_path = structure_dir / "evidence_graph.json"
    try:
        json_content = json.dumps(data, indent=2, sort_keys=True)
        temp_path = output_path.with_suffix(".tmp")
        temp_path.write_text(json_content, encoding="utf-8")
        temp_path.replace(output_path)
        written.append(str(output_path))
    except Exception as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to write evidence graph: {e}",
            phase="S7_MATERIALIZE",
        ))
        return written, errors, trace

    trace.append(TraceEvent.create(
        stage="S7_MATERIALIZE",
        operation="evidence_graph_materialized",
        detail={
            "structure_id": structure_id,
            "output_dir": str(structure_dir),
            "event_count": eg.event_count,
            "edge_count": eg.edge_count,
            "evidence_graph_hash": evidence_graph_hash,
        },
        family=EventFamily.MATERIALIZATION.value,
    ))

    return written, errors, trace


def _materialize_evidence_views(
    evidence_graph_path: str,
    structure_config: dict[str, Any],
    resolver: LayerResolver,
) -> list[str]:
    """
    Generate visualization PNGs from evidence_graph.json — best-effort post-process.

    Reads evidence_graph.json via load_evidence_graph (consumer contract: serialized
    JSON schema only, no compiler internals), builds all four views, writes PNGs to
    <evidence_root>/<structure_id>/views/*.png.

    Returns a list of warning strings (empty = all succeeded).
    PNG failures never block the build.
    """
    warnings: list[str] = []

    try:
        from pgs_compiler.visualization.consumers import load_evidence_graph
        from pgs_compiler.visualization.views import (
            build_family_view, write_family_view_png,
            build_materialization_view, write_materialization_view_png,
        )
    except ImportError as e:
        warnings.append(f"Evidence views skipped: visualization module not available ({e})")
        return warnings

    try:
        query = load_evidence_graph(evidence_graph_path)
    except Exception as e:
        warnings.append(f"Evidence views skipped: failed to load evidence_graph.json ({e})")
        return warnings

    views_dir = Path(evidence_graph_path).parent / "views"
    try:
        views_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        warnings.append(f"Evidence views skipped: failed to create views directory ({e})")
        return warnings

    view_tasks = [
        ("family_view.png",          build_family_view,           write_family_view_png),
        ("materialization_view.png", build_materialization_view,  write_materialization_view_png),
    ]

    for filename, build_fn, write_fn in view_tasks:
        output_path = views_dir / filename
        try:
            view = build_fn(query)
            ok = write_fn(view, output_path)
            if not ok:
                warnings.append(f"Evidence view {filename}: graphviz unavailable or render failed (skipped)")
        except Exception as e:
            warnings.append(f"Evidence view {filename}: failed ({e})")

    return warnings


def _generate_conformance_tests(
    graph: Graph,
    projections: Any,
    structure_config: dict[str, Any],
    resolver: LayerResolver,
) -> tuple[list[str], list[CompilerError], list[TraceEvent]]:
    """
    Generate CT conformance test files from TEST_DATA nodes.

    For each TEST_DATA node:
    1. Resolve target CT via core.target_artifact
    2. Parse test cases from markdown body (### Case N: case_id + yaml block)
    3. Build CT_CONFORMANCE JSON (ct_ir with bound inputs + expected outputs)
    4. Write to STRUCTURE-resolved conformance output path
    """
    materialized: list[str] = []
    errors: list[CompilerError] = []
    trace: list[TraceEvent] = []

    # Collect TEST_DATA nodes
    test_data_nodes = [
        node for node in graph.nodes.values()
        if node.kind == NodeKind.TEST_DATA
    ]

    if not test_data_nodes:
        return materialized, errors, trace

    # Resolve conformance output directory
    try:
        conf_dir = resolver.resolve_output_path(
            "conformance",
            "COMPILER",
            structure_config,
        )
    except (RuntimeError, ValueError) as e:
        errors.append(CompilerError(
            code=ErrorCode.E301_WRITE_FAILED,
            message=f"Failed to resolve conformance output path: {e}",
            phase="S7_MATERIALIZE",
        ))
        return materialized, errors, trace

    conf_dir.mkdir(parents=True, exist_ok=True)

    # Index CT projections by artifact_code for binding
    ct_by_code: dict[str, dict] = {}
    for fqdn, artifact in projections.items():
        if artifact.get("artifact_type") == "CT":
            ct_by_code[artifact["artifact_code"]] = artifact

    # Process each TEST_DATA node
    for td_node in test_data_nodes:
        core = td_node.frontmatter.get("core", {})
        target_ct_code = core.get("target_artifact") if isinstance(core, dict) else None

        if not target_ct_code:
            # Try parsing from content Target section
            content = td_node.metadata.get("content", "")
            target_match = re.search(
                r"## Target\s*\n+```yaml\s*\n(.*?)\n```", content, re.DOTALL
            )
            if target_match:
                target_yaml = yaml.safe_load(target_match.group(1))
                target_ct_code = target_yaml.get("ct_code") if target_yaml else None

        if not target_ct_code:
            continue

        ct_artifact = ct_by_code.get(target_ct_code)
        if not ct_artifact:
            continue

        ct_ir_base = ct_artifact.get("ct_ir")
        if not ct_ir_base:
            continue

        # Parse test cases from markdown body
        content = td_node.metadata.get("content", "")
        case_blocks = re.findall(
            r"### Case \d+: (\w+).*?```yaml\n(.*?)```",
            content,
            re.DOTALL,
        )

        for case_id, case_data in case_blocks:
            try:
                case_dict = yaml.safe_load(case_data)
            except Exception as e:
                errors.append(CompilerError(
                    code=ErrorCode.E101_INVALID_YAML,
                    message=f"Failed to parse case '{case_id}' in {td_node.fqdn}: {e}",
                    phase="S7_MATERIALIZE",
                    fqdn_id=td_node.fqdn,
                ))
                continue

            bindings = case_dict.get("bindings", {})
            expected = case_dict.get("expected", {})
            assertions = case_dict.get("assertions", {})
            expected_outcome = case_dict.get("expected_outcome", "SUCCESS")

            # Build CT-IR with bound inputs
            ct_ir = dict(ct_ir_base)

            # Extract input_types before replacing inputs with test values
            input_types = {}
            if isinstance(ct_ir.get("inputs"), dict):
                for key, spec in ct_ir["inputs"].items():
                    if isinstance(spec, dict) and "type" in spec:
                        input_types[key] = spec["type"]

            ct_ir["inputs"] = bindings
            if input_types:
                ct_ir["input_types"] = input_types

            # Build conformance test artifact
            ct_fqdn = ct_artifact["fqdn_id"]
            test = {
                "artifact_type": "CT_CONFORMANCE",
                "ct_fqdn": ct_fqdn,
                "ct_ir": ct_ir,
                "expected": expected,
                "expected_outcome": expected_outcome,
                "fqdn": f"{ct_fqdn}::{case_id}",
                "test_data_source": td_node.fqdn,
            }
            if assertions:
                test["assertions"] = assertions

            # Write to disk
            filename = f"{ct_fqdn.replace('::', '__')}__{case_id}.json"
            output_path = conf_dir / filename

            try:
                json_content = json.dumps(test, indent=2, sort_keys=True)
                temp_path = output_path.with_suffix(".tmp")
                temp_path.write_text(json_content, encoding="utf-8")
                temp_path.replace(output_path)
                materialized.append(str(output_path))
            except Exception as e:
                errors.append(CompilerError(
                    code=ErrorCode.E301_WRITE_FAILED,
                    message=f"Failed to write conformance test {filename}: {e}",
                    phase="S7_MATERIALIZE",
                    fqdn_id=td_node.fqdn,
                ))
                continue

            trace.append(TraceEvent.create(
                stage="S7_MATERIALIZE",
                operation="conformance_written",
                subject_fqdn=f"{ct_fqdn}::{case_id}",
                detail={"output_path": str(output_path), "test_data_source": td_node.fqdn},
                family=EventFamily.MATERIALIZATION.value,
            ))

    return materialized, errors, trace


def _generate_workflow_graphs(
    projections: Any,
    structure_config: dict[str, Any],
    resolver: LayerResolver,
) -> list[str]:
    """Generate workflow graph artifacts (JSON, PNG) into behavior_logic/ — best-effort post-process."""
    warnings: list[str] = []

    try:
        from pgs_compiler.visualization.wf_graph_generator import generate_workflow_graph
    except ImportError as e:
        warnings.append(f"Graph generation skipped: visualization module not available ({e})")
        return warnings

    wf_artifacts: dict[str, dict] = {}
    cc_artifacts: dict[str, dict] = {}

    for fqdn, artifact in projections.items():
        artifact_type = artifact.get("artifact_type")
        if artifact_type == "WF":
            wf_code = artifact.get("frontmatter", {}).get("wf_code")
            if wf_code:
                wf_artifacts[wf_code] = artifact
        elif artifact_type == "CC":
            cc_code = artifact.get("frontmatter", {}).get("cc_code")
            if cc_code:
                cc_artifacts[cc_code] = artifact

    if not wf_artifacts:
        return warnings

    for wf_code, wf_artifact in wf_artifacts.items():
        try:
            layer_code = wf_artifact.get("layer_code")
            domain_name = wf_artifact.get("domain_name")

            if not layer_code:
                warnings.append(f"{wf_code}: Missing layer_code")
                continue

            try:
                compiled_root = resolver.resolve_output_path(
                    "layer_outputs",
                    layer_code,
                    structure_config,
                    domain=domain_name,
                )
                behavior_logic_root = compiled_root.parent / "behavior_logic"
            except Exception as e:
                warnings.append(f"{wf_code}: Failed to resolve behavior_logic path: {e}")
                continue

            result = generate_workflow_graph(wf_artifact, cc_artifacts, behavior_logic_root)

            if result["status"] == "FAILED":
                warnings.append(f"{wf_code}: Graph generation failed - {', '.join(result.get('errors', []))}")
            elif result["status"] == "PARTIAL":
                warnings.append(f"{wf_code}: Partial graph generation - {', '.join(result.get('errors', []))}")

        except Exception as e:
            warnings.append(f"{wf_code}: Unexpected error - {e}")

    return warnings

