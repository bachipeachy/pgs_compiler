"""
Visualization views — deterministic static renderers over EvidenceQuery.

ISOLATION INVARIANT: All modules in this package MUST use only
visualization.consumers as their data source. No compiler internals.

Views:
    structural_dag    — compilation topology DAG (DOT format)
    artifact_lineage  — causality chain per materialized artifact (DOT format)
    family_view       — event family distribution (ASCII / JSON)
    materialization_view — stage-by-stage artifact output (ASCII / JSON)

Architecture:
    EvidenceQuery → EvidenceProjection → View DTO → Renderer → output string

Renderers produce ONLY deterministic static output (DOT, ASCII, JSON).
Interactive rendering is out of scope for this layer.
"""

from .structural_dag import (
    StructuralDAGView,
    build_structural_dag_view,
    render_structural_dag,
    write_structural_dag_png,
)
from .artifact_lineage import (
    ArtifactLineageView,
    ArtifactLineage,
    build_artifact_lineage_view,
    render_artifact_lineage,
    write_artifact_lineage_png,
)
from .family_view import (
    FamilyViewDTO,
    FamilyStageStat,
    build_family_view,
    render_family_view,
    write_family_view_png,
)
from .materialization_view import (
    MaterializationViewDTO,
    build_materialization_view,
    render_materialization_view,
    write_materialization_view_png,
)

__all__ = [
    # Structural DAG
    "StructuralDAGView",
    "build_structural_dag_view",
    "render_structural_dag",
    "write_structural_dag_png",
    # Artifact Lineage
    "ArtifactLineageView",
    "ArtifactLineage",
    "build_artifact_lineage_view",
    "render_artifact_lineage",
    "write_artifact_lineage_png",
    # Family View
    "FamilyViewDTO",
    "FamilyStageStat",
    "build_family_view",
    "render_family_view",
    "write_family_view_png",
    # Materialization View
    "MaterializationViewDTO",
    "build_materialization_view",
    "render_materialization_view",
    "write_materialization_view_png",
]
