"""
pgs_compiler.inspection — Protocol Inspection module.

These modules answer "What does this protocol mean?" — pure snapshot analysis,
not style compliance. They are compiler-owned because they interpret the compiler's
own output projections.

Modules:
    snapshot_discovery    — dynamic subdomain discovery from protocol_snapshot
    governance_projection — reconstruct Governance Intent per subdomain
    equivalence_validation — structural equivalence check (snapshot vs prose)
"""
