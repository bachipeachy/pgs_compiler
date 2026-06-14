"""
Type enumerations.

Defines the governed vocabulary of node kinds and edge kinds
that form the typed topology of a Protocol-Governed System.
"""

from enum import Enum


class NodeKind(Enum):
    """
    Canonical artifact type categories.

    Every Node belongs to exactly one kind. This determines
    its role in the execution topology and governs which edge
    kinds are legal for that node.
    """

    WF = "WF"                   # Workflow
    CC = "CC"                   # Capability Contract
    CT = "CT"                   # Capability Transform
    CS = "CS"                   # Capability Side Effect
    RB = "RB"                   # Runtime Binding
    IN = "IN"                   # Intent
    EV = "EV"                   # Event
    AC = "AC"                   # Actor Context
    TI = "TI"                   # Transport Ingress
    TE = "TE"                   # Transport Egress
    ASSERT = "ASSERT"           # Assertion (constitutional)
    TEST_DATA = "TEST_DATA"     # Test data (conformance)
    GOVERNANCE = "GOVERNANCE"   # Governance meta-artifact (constitution, invariant, layer)


class EdgeKind(Enum):
    """
    Typed relationship categories between graph nodes.

    Edges are explicit — no implicit traversal is permitted.
    This preserves the PGS invariant: unauthorized behavior
    must be structurally unrepresentable.
    """

    # --- Execution topology ---
    WF_CONTAINS_NODE = "WF_CONTAINS_NODE"       # WF → CC node membership
    WF_START = "WF_START"                        # WF → entry CC node
    NODE_NEXT = "NODE_NEXT"                      # CC → CC transition (with outcome condition)

    # --- Capability binding ---
    CC_BINDS_CT = "CC_BINDS_CT"                  # CC pipeline step → CT
    CC_BINDS_CS = "CC_BINDS_CS"                  # CC pipeline step → CS
    RB_MAPS = "RB_MAPS"                          # RB → CT/CS implementation mapping

    # --- Governance ---
    GOVERNED_BY = "GOVERNED_BY"                  # Artifact → Constitution
    ASSERTED_BY = "ASSERTED_BY"                  # Artifact → ASSERT
    INVARIANT_APPLIES = "INVARIANT_APPLIES"      # Invariant → artifact scope

    # --- Authority ---
    WF_ADMITS_VIA_IN = "WF_ADMITS_VIA_IN"        # WF → IN admission gate
    WF_BINDS_RB = "WF_BINDS_RB"                 # WF → RB binding

    # --- Boundary ---
    TI_INVOKES_WF = "TI_INVOKES_WF"              # TI → WF declared invocation entry point

    # --- Composition ---
    MOLECULE_COMPOSES_ATOM = "MOLECULE_COMPOSES_ATOM"  # CT molecule → CT atom
    CT_ATOM_STEP = "CT_ATOM_STEP"                      # CT → atom stream step

    # --- General ---
    REFERENCES = "REFERENCES"                    # Declared reference (generic, pre-typed)
