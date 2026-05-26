"""
Edge — immutable typed edge in the Protocol Intermediate Representation.

Edges represent admissible relationships between governed artifacts.
No implicit traversal is permitted — only declared edges exist.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.graph.types import EdgeKind


# Sentinel for empty immutable mappings
_EMPTY_MAP: MappingProxyType = MappingProxyType({})


@dataclass(frozen=True)
class Edge:
    """
    Immutable typed edge in the semantic graph.

    Represents a declared relationship between two nodes. Edges carry
    both FQDN identity (authoritative) and integer addresses (derived).

    Lifecycle:
        - Created by S2 CANONICALIZE (REFERENCES edges from declared refs)
        - Addressed by S3 SEMANTIC_ADDRESSING (address fields populated)
        - Typed by S5 CONSTRUCT (REFERENCES edges upgraded to specific kinds)

    Metadata carries edge-specific properties:
        - NODE_NEXT: {"condition": "SUCCESS", "condition_address": 42}
        - CC_BINDS_CT: {"step_id": "step_1", "pipeline_index": 0}
        - RB_MAPS: {"binding_type": "CT", "handler_ref": "..."}
    """

    # --- Identity (authoritative) ---
    source_fqdn: str                    # Edge source node FQDN
    target_fqdn: str                    # Edge target node FQDN

    # --- Address (derived, populated by S3) ---
    source_address: int                 # Tokenized source (-1 until SEMANTIC_ADDRESSING)
    target_address: int                 # Tokenized target (-1 until SEMANTIC_ADDRESSING)

    # --- Type ---
    kind: EdgeKind                   # Typed relationship
    kind_address: int                   # Tokenized edge kind (-1 until SEMANTIC_ADDRESSING)

    # --- Properties ---
    metadata: MappingProxyType          # Edge-specific properties

    def replace(self, **kwargs: Any) -> "Edge":
        """
        Create a new Edge with specified fields replaced.

        Returns a new instance — original remains frozen.
        """
        current = {
            "source_fqdn": self.source_fqdn,
            "target_fqdn": self.target_fqdn,
            "source_address": self.source_address,
            "target_address": self.target_address,
            "kind": self.kind,
            "kind_address": self.kind_address,
            "metadata": self.metadata,
        }
        current.update(kwargs)
        return Edge(**current)

    @staticmethod
    def create(
        source_fqdn: str,
        target_fqdn: str,
        kind: EdgeKind,
        metadata: dict[str, Any] | None = None,
    ) -> "Edge":
        """
        Factory for creating Edge with proper immutable wrapping.

        Sets address fields to -1 (populated by S3 SEMANTIC_ADDRESSING).

        Args:
            source_fqdn: Source node FQDN
            target_fqdn: Target node FQDN
            kind: Edge kind
            metadata: Edge-specific properties (will be frozen)

        Returns:
            New immutable Edge
        """
        return Edge(
            source_fqdn=source_fqdn,
            target_fqdn=target_fqdn,
            source_address=-1,
            target_address=-1,
            kind=kind,
            kind_address=-1,
            metadata=MappingProxyType(metadata or {}),
        )
