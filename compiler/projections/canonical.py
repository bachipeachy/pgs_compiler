"""
Canonical projection — human/governance/tooling authority.

Derives from PIRGraph. Produces the traditional protocol_snapshot/ output:
JSON artifact files with fqdn_id, artifact_code, artifact_type, frontmatter,
ct_ir, cs_ir, cc_projection, etc.

Output format per artifact:
{
    "fqdn_id": "namespace::ARTIFACT_CODE_Vn",
    "artifact_code": "ARTIFACT_CODE_Vn",
    "artifact_type": "CT",
    "namespace": "namespace",
    "version": "0",
    "layer_code": "PLATFORM",
    "module_path": "pkg.registry.module",
    "content": "# full markdown source ...",
    "content_hash": "sha256hex",
    "frontmatter": {...},
    "references": ["ns::CODE_V0", ...],
    "ct_ir": {...},       # CT only
    "cs_ir": {...},       # CS only
    "cc_projection": {...} # CC only
}

All dict keys are sorted recursively for deterministic output.
Transient pipeline fields (source_path) are stripped.
"""

from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.graph.types import NodeKind
from pgs_compiler.compiler.graph.node import Node
from pgs_compiler.compiler.graph.graph import Graph
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.graph.evidence import EventFamily
from pgs_compiler.compiler.graph.hashing import compute_projection_hash
from pgs_compiler.compiler.atoms.sorting import ensure_deterministic_output
from pgs_compiler.compiler.projections import (
    Projection,
    ProjectionType,
    make_metadata,
    COMPILER_VERSION,
    PROJECTION_SCHEMA_VERSION,
)


def project_canonical(graph: Graph) -> tuple[Projection, list[TraceEvent]]:
    """
    Generate the canonical projection from Graph.

    Produces {fqdn: artifact_dict} for all non-TEST_DATA nodes.
    This is the projection that becomes protocol_snapshot/.

    Args:
        graph: Fully constructed PIRGraph (output of S5 CONSTRUCT)

    Returns:
        Tuple of (Projection with canonical content, trace events)
    """
    projected: dict[str, dict[str, Any]] = {}
    trace: list[TraceEvent] = []

    for fqdn in sorted(graph.nodes.keys()):
        node = graph.nodes[fqdn]

        # Skip TEST_DATA — used only for conformance, not materialized
        if node.kind == NodeKind.TEST_DATA:
            continue

        artifact_dict = _project_node(node)

        if artifact_dict is not None:
            projected[fqdn] = ensure_deterministic_output(artifact_dict)
            trace.append(TraceEvent.create(
                stage="S6_PROJECT",
                operation="artifact_projected",
                subject_fqdn=fqdn,
                subject_token=node.address,
                detail={"artifact_type": node.kind.value},
                family=EventFamily.PROJECTION.value,
            ))

    projection_hash = compute_projection_hash(projected)

    metadata = make_metadata(
        projection_type=ProjectionType.CANONICAL,
        graph_topology_hash=graph.topology_hash,
        graph_address_hash=graph.address_hash,
        projection_hash=projection_hash,
        compiler_version=COMPILER_VERSION,
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
    )

    projection = Projection(
        projection_type=ProjectionType.CANONICAL,
        metadata=metadata,
        content=MappingProxyType(projected),
    )

    return projection, trace


def _resolve_artifact_type(node: Node) -> str:
    """
    Resolve the artifact type prefix written into the canonical projection.

    Single source of truth: the ArtifactKindRegistry (replaces the legacy _GOVERNANCE_PREFIXES list).
    Non-GOVERNANCE nodes: kind.value IS the prefix. GOVERNANCE nodes: keep the code's prefix when the
    descriptor says so, else collapse to "GOVERNANCE".
    """
    from pgs_governance.implementation.artifact_kinds import REGISTRY
    return REGISTRY.canonical_type(node.kind.value, node.artifact_code)


def _project_node(node: Node) -> dict[str, Any] | None:
    """
    Project a single Node into canonical JSON artifact format.

    Returns None if the node should not be materialized.
    """
    metadata = dict(node.metadata)
    frontmatter = dict(node.frontmatter)

    artifact: dict[str, Any] = {
        "fqdn_id": node.fqdn,
        "artifact_code": node.artifact_code,
        "artifact_type": _resolve_artifact_type(node),
        "namespace": node.namespace,
        "version": node.version,
        "layer_code": node.layer_code,
        "module_path": metadata.get("module_path", ""),
        "content": metadata.get("content", ""),
        "content_hash": node.content_hash,
        "frontmatter": _deep_dict(frontmatter),
        "references": list(metadata.get("references", [])),
    }

    # Domain artifacts carry domain_name
    if node.domain_name:
        artifact["domain_name"] = node.domain_name

    # Type-specific IR fields
    if node.ir is not None:
        ir = dict(node.ir)

        if node.kind == NodeKind.CT and "ct_code" in ir:
            artifact["ct_ir"] = _deep_dict(ir)

        elif node.kind == NodeKind.CS and "handler_ref" in ir:
            artifact["cs_ir"] = _deep_dict(ir)

        elif node.kind == NodeKind.CC and "cc_projection" in ir:
            artifact["cc_projection"] = _deep_dict(ir["cc_projection"])

    return artifact


def _deep_dict(obj: Any) -> Any:
    """Recursively convert MappingProxyType and other mappings to plain dicts."""
    if hasattr(obj, "items"):
        return {k: _deep_dict(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_deep_dict(item) for item in obj]
    return obj
