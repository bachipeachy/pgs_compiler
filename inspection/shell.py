"""
pi shell — readline wrapper over the one-shot command layer.

No additional semantics live here: every shell line is the one-shot
command verbatim, dispatched through the same click group with the
session (and its loaded indices) held warm across queries.

Scoping: `use <domain>` declares the session scope; the prompt becomes
`pi:<domain>>`. Bare artifact codes (FOO_BAR_V0) are expanded to
<scope>::FOO_BAR_V0 — resolution within a declared, visible scope,
not inference. Outside a declared scope, full FQDNs are required.
"""

import re
import shlex

import click

from pgs_compiler.inspection.errors import InspectionError

# Bare artifact code: versioned, fully uppercase, no domain separator.
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_V\d+$")


def run_shell(session) -> None:
    """Run the interactive pi shell over an open session."""
    from pgs_compiler.inspection.cli import pi  # late import — avoids cycle

    # Open the workspace now — fail hard before the first prompt.
    _ = session.workspace
    fqdns = [fqdn for fqdn, _ in session.resolver.list()]
    domains = sorted({fqdn.split("::", 1)[0] for fqdn in fqdns})

    scope: str | None = None

    _install_completer(pi, fqdns, domains, lambda: scope)

    click.echo("pi shell — protocol inspection (read-only). "
               "'use <domain>' to scope, 'exit' to leave.")

    while True:
        prompt = f"pi:{scope}> " if scope else "pi> "
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break

        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit"):
            break

        if line == "use" or line.startswith("use "):
            parts = line.split()
            if len(parts) == 1:
                scope = None
                click.echo("scope cleared")
            elif parts[1] in domains:
                scope = parts[1]
            else:
                click.echo(
                    f"Error: unknown domain '{parts[1]}' — declared domains: "
                    + ", ".join(domains),
                    err=True,
                )
            continue

        try:
            args = shlex.split(line)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            continue

        if scope:
            args = [
                f"{scope}::{token}" if _CODE_RE.match(token) else token
                for token in args
            ]

        try:
            pi.main(args=args, prog_name="pi", standalone_mode=False, obj=session)
        except InspectionError as exc:
            click.echo(f"Error: {exc}", err=True)
        except click.ClickException as exc:
            exc.show()
        except click.exceptions.Abort:
            break
        except SystemExit as exc:  # --strict style exits stay in-shell
            if exc.code not in (0, None):
                click.echo(f"(exit {exc.code})", err=True)


def _install_completer(pi_group, fqdns, domains, get_scope) -> None:
    """Tab completion: objects, verbs, FQDNs (and scoped bare codes)."""
    try:
        import readline
    except ImportError:  # readline unavailable — shell still works
        return

    top_level = sorted(pi_group.commands) + ["use", "exit", "quit"]

    def candidates_for(tokens: list[str]) -> list[str]:
        if not tokens:
            return top_level
        if tokens[0] == "use":
            return domains
        if len(tokens) == 1:
            group = pi_group.commands.get(tokens[0])
            if isinstance(group, click.Group):
                return sorted(group.commands)
            return []
        # target position: FQDNs, plus bare codes within the declared scope
        scope = get_scope()
        scoped = [
            fqdn.split("::", 1)[1] for fqdn in fqdns
            if scope and fqdn.startswith(f"{scope}::")
        ]
        return fqdns + scoped

    def complete(text: str, state: int):
        buffer = readline.get_line_buffer()
        tokens = buffer[: readline.get_begidx()].split()
        matches = sorted(c for c in candidates_for(tokens) if c.startswith(text))
        return matches[state] if state < len(matches) else None

    readline.set_completer(complete)
    readline.set_completer_delims(" \t\n")
    readline.parse_and_bind("tab: complete")
