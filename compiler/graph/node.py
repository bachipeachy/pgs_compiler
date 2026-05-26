"""
Node — immutable semantic node in the Protocol Intermediate Representation.

Each node represents a canonical governed artifact in the topology.
Nodes are FQDN-addressed, semantically typed, and immutable.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.graph.types import NodeKind


# Sentinel for empty immutable mappings
_EMPTY_MAP: MappingProxyType = MappingProxyType({})


@dataclass(frozen=True)
class Node:
    """
    Immutable node in the semantic graph.

    Represents a single governed artifact (WF, CC, CT, CS, RB, IN, EV, AC,
    ASSERT, TEST_DATA, or GOVERNANCE). Identity is the FQDN.

    Lifecycle:
        - Created by S1 EXTRACT (frontmatter populated, address=-1, ir=None)
        - Enriched by S2 CANONICALIZE (namespace/fqdn finalized)
        - Addressed by S3 SEMANTIC_ADDRESSING (address assigned)
        - Completed by S5 CONSTRUCT (ir populated for CT/CS/CC/WF)

    Since frozen, enrichment returns a NEW node via replace().
    """

    # --- Identity ---
    fqdn: str                           # Primary identity: "blockchain::WF_REGISTER_ACTOR_UNVERIFIED_V0"
    address: int                        # Deterministic semantic address (-1 until S3 SEMANTIC_ADDRESSING)
    kind: NodeKind                   # Artifact type category

    # --- FQDN components ---
    namespace: str                      # FQDN namespace component (e.g., "blockchain")
    artifact_code: str                  # FQDN code component (e.g., "WF_REGISTER_ACTOR_UNVERIFIED_V0")
    version: str                        # Version string (e.g., "V0")

    # --- Compilation context ---
    layer_code: str                     # STRUCTURE layer (e.g., "PLATFORM", "DOMAINS")
    domain_name: str | None             # Domain context for DOMAINS layer (None for PLATFORM)

    # --- Content ---
    content_hash: str                   # SHA-256 of source file content
    frontmatter: MappingProxyType       # Immutable parsed Machine YAML block
    ir: MappingProxyType | None         # CT-IR, CS-IR, or CC projection (populated by S5 CONSTRUCT)
    metadata: MappingProxyType          # Stage-accumulated metadata

    def replace(self, **kwargs: Any) -> "Node":
        """
        Create a new Node with specified fields replaced.

        This is the only way to "modify" a node — it returns a new instance.
        The original remains unchanged (frozen dataclass guarantee).

        Args:
            **kwargs: Fields to replace (must be valid Node field names)

        Returns:
            New Node with updated fields
        """
        # Get current values
        current = {
            "fqdn": self.fqdn,
            "address": self.address,
            "kind": self.kind,
            "namespace": self.namespace,
            "artifact_code": self.artifact_code,
            "version": self.version,
            "layer_code": self.layer_code,
            "domain_name": self.domain_name,
            "content_hash": self.content_hash,
            "frontmatter": self.frontmatter,
            "ir": self.ir,
            "metadata": self.metadata,
        }
        current.update(kwargs)
        return Node(**current)

    @staticmethod
    def create(
        fqdn: str,
        kind: NodeKind,
        namespace: str,
        artifact_code: str,
        version: str,
        layer_code: str,
        content_hash: str,
        frontmatter: dict[str, Any],
        domain_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Node":
        """
        Factory for creating Node with proper immutable wrapping.

        Converts mutable dicts to MappingProxyType. Sets address=-1
        and ir=None (populated by later stages).

        Args:
            fqdn: Fully qualified domain name
            kind: Node kind (artifact type)
            namespace: FQDN namespace
            artifact_code: FQDN code component
            version: Version string
            layer_code: STRUCTURE layer
            content_hash: SHA-256 of source
            frontmatter: Parsed Machine YAML (will be frozen)
            domain_name: Domain context (optional)
            metadata: Additional metadata (optional, will be frozen)

        Returns:
            New immutable Node
        """
        return Node(
            fqdn=fqdn,
            address=-1,
            kind=kind,
            namespace=namespace,
            artifact_code=artifact_code,
            version=version,
            layer_code=layer_code,
            domain_name=domain_name,
            content_hash=content_hash,
            frontmatter=MappingProxyType(frontmatter),
            ir=None,
            metadata=MappingProxyType(metadata or {}),
        )
