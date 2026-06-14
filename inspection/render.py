"""
Output projections — terminal text (default) and --json (stable schema).

Both surfaces render the same result object. JSON output is the agent/CI
contract: {"schema_version", "query", "result"}, sorted keys, deterministic.
"""

import json
from typing import Any, Callable

import click

OUTPUT_SCHEMA_VERSION = "v0"


def emit(
    as_json: bool,
    query: dict[str, Any],
    result: Any,
    text_renderer: Callable[[Any], None],
) -> None:
    """Render one command result to the selected surface."""
    if as_json:
        envelope = {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "query": query,
            "result": result,
        }
        click.echo(json.dumps(envelope, indent=2, sort_keys=True))
    else:
        text_renderer(result)


# ── terminal helpers ─────────────────────────────────────────────

def heading(text: str) -> None:
    click.echo(click.style(text, bold=True))


def field(label: str, value: Any, indent: int = 2) -> None:
    click.echo(f"{' ' * indent}{label}: {value}")


def fqdn_line(fqdn: str, annotation: str = "", indent: int = 2) -> None:
    suffix = f"  {click.style(annotation, dim=True)}" if annotation else ""
    click.echo(f"{' ' * indent}{click.style(fqdn, fg='cyan')}{suffix}")


def render_tree(
    node: dict[str, Any],
    prefix: str = "",
    is_last: bool = True,
    is_root: bool = True,
) -> None:
    """Render a lineage tree node (fqdn/kind/children) as box-drawing lines."""
    connector = "" if is_root else ("└─ " if is_last else "├─ ")
    label = f"{click.style(node['fqdn'], fg='cyan')} {click.style('[' + node['kind'] + ']', dim=True)}"
    edge = node.get("edge_kind")
    if edge:
        label += f" {click.style('(' + edge + ')', dim=True)}"
    if node.get("cycle"):
        label += click.style("  ↺ cycle", fg="yellow")
    click.echo(f"{prefix}{connector}{label}")
    children = node.get("children", [])
    child_prefix = prefix + ("" if is_root else ("   " if is_last else "│  "))
    for i, child in enumerate(children):
        render_tree(child, child_prefix, i == len(children) - 1, is_root=False)
