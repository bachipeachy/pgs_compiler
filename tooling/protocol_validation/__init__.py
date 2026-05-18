"""
protocol_validation — Shared validation primitives and standalone CLI validators.

  core/   — ValidationError, load_json_file (reusable base)
  cli/    — Standalone validators: graph, payload, schema
"""
from pgs_compiler.tooling.protocol_validation.core.base import ValidationError, load_json_file

__all__ = ["ValidationError", "load_json_file"]
