"""
Projection types and abstractions.

Each projection is a deterministic derivation of the PIRGraph —
the sole semantic authority. No projection derives from another
projection. All derive from Graph.

Projection families:

    canonical   — human/governance/tooling authority (protocol_snapshot/)
    tokenized   — machine/silicon/runtime authority (tokenized_snapshot/)
    vocabulary  — debug/trace/symbol substrate (semantic_vocabulary/)
    evidence    — observability/replay (evidence_snapshot/)
    dispatch    — token-native execution routing (tokenized_snapshot/)
    handlers    — token-native implementation dispatch (tokenized_snapshot/)

Foundational doctrine:
    - Single semantic authority (PIRGraph)
    - Multiple deterministic sibling projections
    - Governance reasons in symbolic semantic space
    - Tokenization is machine realization space
    - Semantic Space vs Address Space separation is absolute
    - S8 validates based on ProjectionClass, never by filename
"""

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


class ProjectionType(Enum):
    """Named projection types derived from Graph."""

    CANONICAL = "canonical"      # Human/governance/tooling authority
    TOKENIZED = "tokenized"      # Machine/silicon/runtime authority (topology)
    VOCABULARY = "vocabulary"    # Debug/trace/symbol substrate
    EVIDENCE = "evidence"        # Observability/replay
    DISPATCH = "dispatch"        # Token-native execution routing tables
    HANDLERS = "handlers"        # Token-native implementation dispatch


class ProjectionClass(Enum):
    """
    Semantic class of a projection output.

    Determines validation rules applied by S8 and downstream consumers.
    S8 uses this to validate conditionally — never by filename.

    Classes:
        CANONICAL_ARTIFACT  — Protocol artifacts with fqdn_id identity.
                              Subject to roundtrip and FQDN integrity checks.
                              Lives in protocol_snapshot/.

        MACHINE_PROJECTION  — Integer-addressed machine substrate.
                              No fqdn_id. Structural integrity only.
                              Lives in tokenized_snapshot/.

        SYMBOL_SUBSTRATE    — FQDN↔address lookup tables for debug/trace.
                              No fqdn_id. Content integrity only.
                              Lives in semantic_vocabulary/.

        EVIDENCE_SUBSTRATE  — Observability, replay, and compile-trace graphs.
                              No fqdn_id. Schema integrity only.
                              Lives in evidence_snapshot/.
    """

    CANONICAL_ARTIFACT = "canonical_artifact"
    MACHINE_PROJECTION = "machine_projection"
    SYMBOL_SUBSTRATE   = "symbol_substrate"
    EVIDENCE_SUBSTRATE = "evidence_substrate"


# Map each ProjectionType to its class — explicit, no inference.
_PROJECTION_TYPE_CLASS: dict[ProjectionType, ProjectionClass] = {
    ProjectionType.CANONICAL: ProjectionClass.CANONICAL_ARTIFACT,
    ProjectionType.TOKENIZED: ProjectionClass.MACHINE_PROJECTION,
    ProjectionType.VOCABULARY: ProjectionClass.SYMBOL_SUBSTRATE,
    ProjectionType.EVIDENCE:  ProjectionClass.EVIDENCE_SUBSTRATE,
    ProjectionType.DISPATCH:  ProjectionClass.MACHINE_PROJECTION,
    ProjectionType.HANDLERS:  ProjectionClass.MACHINE_PROJECTION,
}


@dataclass(frozen=True)
class ProjectionMetadata:
    """
    Immutable metadata for a single projection.

    Written as metadata.json alongside materialized projection output.
    Enables: replay, attestation, runtime compatibility, silicon verification.

    projection_class declares the semantic class of this projection's output.
    S8 and other consumers use this to apply the correct validation rules.
    requires_fqdn_identity is derived from projection_class — no separate flag.
    """

    projection_type: ProjectionType
    projection_class: ProjectionClass
    graph_topology_hash: str      # From graph.topology_hash
    graph_address_hash: str       # From graph.address_hash
    projection_hash: str          # SHA-256 of projection content
    compiler_version: str         # Semantic version (e.g. "0.3.0")
    projection_schema_version: str  # Projection schema contract (e.g. "v0")

    @property
    def requires_fqdn_identity(self) -> bool:
        """True iff materialized files in this projection carry fqdn_id."""
        return self.projection_class == ProjectionClass.CANONICAL_ARTIFACT

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for metadata.json output."""
        return {
            "projection_type": self.projection_type.value,
            "projection_class": self.projection_class.value,
            "requires_fqdn_identity": self.requires_fqdn_identity,
            "graph_topology_hash": self.graph_topology_hash,
            "graph_address_hash": self.graph_address_hash,
            "projection_hash": self.projection_hash,
            "compiler_version": self.compiler_version,
            "projection_schema_version": self.projection_schema_version,
        }


@dataclass(frozen=True)
class Projection:
    """
    Immutable named projection derived from Graph.

    Each projection carries typed metadata and a frozen content payload.
    Content shape varies per projection_type:
        - CANONICAL: {fqdn: artifact_dict}
        - TOKENIZED: {nodes: [{address, kind}], edges: [{from, to, kind}], adjacency: {addr: [targets]}}
        - VOCABULARY: {forward: {hex: identity}, reverse: {identity: hex}}
        - EVIDENCE:   {nodes: [{fqdn, address, kind, kind_address}], edges: [{...dual...}], event_catalog: [{fqdn, address, schema}]}
        - DISPATCH:   {routing: {...}, pipeline: {...}, entry: {...}}
        - HANDLERS:   {ct: {...}, cs: {...}, rb_policy: {...}}
    """

    projection_type: ProjectionType
    metadata: ProjectionMetadata
    content: MappingProxyType     # Frozen payload (shape varies per projection_type)


def make_metadata(
    projection_type: ProjectionType,
    graph_topology_hash: str,
    graph_address_hash: str,
    projection_hash: str,
    compiler_version: str,
    projection_schema_version: str,
) -> ProjectionMetadata:
    """
    Construct ProjectionMetadata with projection_class auto-resolved from type.

    Single call site ensures projection_type and projection_class stay in sync.
    """
    return ProjectionMetadata(
        projection_type=projection_type,
        projection_class=_PROJECTION_TYPE_CLASS[projection_type],
        graph_topology_hash=graph_topology_hash,
        graph_address_hash=graph_address_hash,
        projection_hash=projection_hash,
        compiler_version=compiler_version,
        projection_schema_version=projection_schema_version,
    )


# Version constants — compiler_version must match pyproject.toml
COMPILER_VERSION = "0.5.0"
PROJECTION_SCHEMA_VERSION = "v0"

# Structure artifact code → structure scope for projection output paths.
# Explicit map — no inference, no parsing. PGS doctrine: zero guessing.
_STRUCTURE_SCOPE_MAP: dict[str, str] = {
    "STRUCTURE_BUILD_PLATFORM_CONFIG_V0": "platform",
    "STRUCTURE_BUILD_BLOCKCHAIN_CONFIG_V0": "blockchain",
    "STRUCTURE_BUILD_AI_GOVERNANCE_CONFIG_V0": "ai_governance",
}


def get_structure_scope(structure_config: dict[str, Any]) -> str | None:
    """Resolve structure scope from structure_artifact_code. Returns None if unknown."""
    code = structure_config.get("structure_artifact_code", "")
    return _STRUCTURE_SCOPE_MAP.get(code)
