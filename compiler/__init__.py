"""
trad-compiler: Traditional imperative compiler for protocol artifacts.

CRITICAL: This package has ZERO imports from pgs_* packages.
Enforced by CI check: tests/test_no_pgs_imports.sh

Architecture:
- atoms/: Pure functions (errors, FQDN, YAML parsing)
- phases/: Pipeline stages (discover, parse, validate, materialize, verify)
- schemas/: Pydantic models (artifact type definitions)
- io/: Side-effects (file I/O, JSON writing)
"""

__version__ = "1.0.0"
