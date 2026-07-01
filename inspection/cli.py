"""
pi — Protocol Inspection command processor (one-shot CLI surface).

Object-centric taxonomy over the inspection library:

    pi <object> <verb> [target] [flags]

Strictly read-only: every command queries materialized snapshot
projections; nothing is written anywhere, including caches.
The workspace root is explicit (--workspace or PGS_WORKSPACE).
"""

import sys
from typing import Any

import click

from pgs_compiler.inspection import behavior_logic as behavior_logic_lib
from pgs_compiler.inspection import traces as trace_lib
from pgs_compiler.inspection.errors import AmbiguousCode, InspectionError, UnresolvedFqdn
from pgs_compiler.inspection.loader import (
    PPS_SECTION_BY_KIND,
    Workspace,
    classify_lifecycle,
    parse_header_fields,
)
from pgs_compiler.inspection.render import emit, field, fqdn_line, heading, render_tree
from pgs_compiler.inspection.resolver import Resolver
from pgs_compiler.inspection.traversal import SemanticGraph

KIND_OBJECTS = {
    "wf": "WF", "cc": "CC", "ct": "CT", "cs": "CS",
    "rb": "RB", "in": "IN", "ev": "EV", "ac": "AC",
}


class Session:
    """Lazy, per-invocation handle: workspace, resolver, graph."""

    def __init__(self, workspace_arg: str | None):
        self._workspace_arg = workspace_arg
        self._workspace: Workspace | None = None
        self._resolver: Resolver | None = None
        self._graph: SemanticGraph | None = None

    @property
    def workspace(self) -> Workspace:
        if self._workspace is None:
            self._workspace = Workspace.open(self._workspace_arg)
        return self._workspace

    @property
    def resolver(self) -> Resolver:
        if self._resolver is None:
            self._resolver = Resolver(self.workspace)
        return self._resolver

    @property
    def graph(self) -> SemanticGraph:
        if self._graph is None:
            self._graph = SemanticGraph(self.workspace)
        return self._graph


def json_flag(fn):
    return click.option("--json", "as_json", is_flag=True, help="Stable JSON output")(fn)


pass_session = click.make_pass_decorator(Session)


@click.group(invoke_without_command=True)
@click.option(
    "--workspace",
    envvar="PGS_WORKSPACE",
    default=None,
    help="Absolute path to pgs_workspace root (or set PGS_WORKSPACE)",
)
@click.pass_context
def pi(ctx: click.Context, workspace: str | None) -> None:
    """pi — protocol inspection over the compiled snapshot set (read-only)."""
    if ctx.obj is None:  # shell dispatch passes its warm session via obj=
        ctx.obj = Session(workspace)
    if ctx.invoked_subcommand is None:
        from pgs_compiler.inspection.shell import run_shell
        run_shell(ctx.obj)


# ─────────────────────────────────────────────────────────────────
# pi artifact — kind-agnostic daily drivers
# ─────────────────────────────────────────────────────────────────

@pi.group()
def artifact() -> None:
    """Kind-agnostic artifact queries (any FQDN)."""


@artifact.command("show")
@click.argument("ref")
@json_flag
@pass_session
def artifact_show(session: Session, ref: str, as_json: bool) -> None:
    """Identity, governance, and direct relationship summary."""
    fqdn, entry = session.resolver.resolve(ref)
    graph = session.graph
    governed_by = sorted({
        e.target for e in graph.out_edges(fqdn) if e.kind == "GOVERNED_BY"
    })
    result = {
        "fqdn": fqdn,
        **entry,
        "governed_by": governed_by,
        "direct_refs": len(graph.refs(fqdn)),
        "direct_deps": len(graph.deps(fqdn)),
    }

    def text(r: dict[str, Any]) -> None:
        heading(f"Artifact: {fqdn}")
        field("kind", r["kind"])
        field("domain", r["domain"])
        field("structures", ", ".join(r["structures"]) or "(none)")
        field("canonical", r["canonical_path"])
        for scope, addr in r["addresses"].items():
            field(f"address[{scope}]", addr)
        field("governed by", ", ".join(r["governed_by"]) or "(none)")
        field("direct refs", r["direct_refs"])
        field("direct deps", r["direct_deps"])

    emit(as_json, {"command": "artifact show", "target": fqdn}, result, text)


@artifact.command("refs")
@click.argument("ref")
@click.option("--transitive", is_flag=True, help="Full consumer closure")
@json_flag
@pass_session
def artifact_refs(session: Session, ref: str, transitive: bool, as_json: bool) -> None:
    """Who references this artifact (consumers)."""
    fqdn, _ = session.resolver.resolve(ref)
    result = session.graph.refs(fqdn, transitive=transitive)

    def text(records: list[dict[str, Any]]) -> None:
        heading(f"Referenced by ({len(records)}): {fqdn}")
        for r in records:
            note = f"[{r['kind']}] via {r['edge_kind']}"
            note += f" depth {r['depth']}" if transitive else ""
            fqdn_line(r["fqdn"], note)

    emit(as_json, {"command": "artifact refs", "target": fqdn, "transitive": transitive}, result, text)


@artifact.command("deps")
@click.argument("ref")
@click.option("--transitive", is_flag=True, help="Full dependency closure")
@json_flag
@pass_session
def artifact_deps(session: Session, ref: str, transitive: bool, as_json: bool) -> None:
    """What this artifact depends on."""
    fqdn, _ = session.resolver.resolve(ref)
    result = session.graph.deps(fqdn, transitive=transitive)

    def text(records: list[dict[str, Any]]) -> None:
        heading(f"Depends on ({len(records)}): {fqdn}")
        for r in records:
            note = f"[{r['kind']}] via {r['edge_kind']}"
            note += f" depth {r['depth']}" if transitive else ""
            fqdn_line(r["fqdn"], note)

    emit(as_json, {"command": "artifact deps", "target": fqdn, "transitive": transitive}, result, text)


@artifact.command("lineage")
@click.argument("ref")
@json_flag
@pass_session
def artifact_lineage(session: Session, ref: str, as_json: bool) -> None:
    """Full ancestry (dependencies) and descendants (consumers) as trees."""
    fqdn, _ = session.resolver.resolve(ref)
    result = session.graph.lineage(fqdn)

    def text(r: dict[str, Any]) -> None:
        heading(f"Ancestors (dependencies): {fqdn}")
        render_tree(r["ancestors"])
        click.echo()
        heading(f"Descendants (consumers): {fqdn}")
        render_tree(r["descendants"])

    emit(as_json, {"command": "artifact lineage", "target": fqdn}, result, text)


@artifact.command("owner")
@click.argument("ref")
@json_flag
@pass_session
def artifact_owner(session: Session, ref: str, as_json: bool) -> None:
    """Owning domain / subdomain / STRUCTURE."""
    fqdn, entry = session.resolver.resolve(ref)
    result = {
        "fqdn": fqdn,
        "domain": entry["domain"],
        "structures": entry["structures"],
    }
    if entry["kind"] in PPS_SECTION_BY_KIND:
        pps_entry = session.workspace.pps.get(
            PPS_SECTION_BY_KIND[entry["kind"]], {}
        ).get(fqdn)
        if pps_entry and "subdomain" in pps_entry:
            result["subdomain"] = pps_entry["subdomain"]

    def text(r: dict[str, Any]) -> None:
        heading(f"Owner: {fqdn}")
        field("domain", r["domain"])
        if "subdomain" in r:
            field("subdomain", r["subdomain"])
        field("structures", ", ".join(r["structures"]) or "(none)")

    emit(as_json, {"command": "artifact owner", "target": fqdn}, result, text)


@artifact.command("source")
@click.argument("ref")
@json_flag
@pass_session
def artifact_source(session: Session, ref: str, as_json: bool) -> None:
    """Authoring Markdown, retrieved from the PPS snapshot."""
    fqdn, entry = session.resolver.resolve(ref)
    pps_entry = session.workspace.pps_entry(fqdn, entry["kind"])
    content = pps_entry.get("raw", {}).get("content", "")
    result = {"fqdn": fqdn, "kind": entry["kind"], "content": content}

    def text(r: dict[str, Any]) -> None:
        click.echo(r["content"])

    emit(as_json, {"command": "artifact source", "target": fqdn}, result, text)


@artifact.command("list")
@click.option("--kind", type=click.Choice(sorted(KIND_OBJECTS.values())), default=None)
@click.option("--domain", default=None)
@json_flag
@pass_session
def artifact_list(session: Session, kind: str | None, domain: str | None, as_json: bool) -> None:
    """List indexed artifacts, optionally filtered by kind and/or domain."""
    entries = session.resolver.list(kind=kind, domain=domain)
    result = [{"fqdn": f, "kind": e["kind"], "domain": e["domain"]} for f, e in entries]

    def text(records: list[dict[str, Any]]) -> None:
        heading(f"Artifacts ({len(records)})")
        for r in records:
            fqdn_line(r["fqdn"], f"[{r['kind']}]")

    emit(as_json, {"command": "artifact list", "kind": kind, "domain": domain}, result, text)


# ─────────────────────────────────────────────────────────────────
# Kind objects — pi wf|cc|ct|cs|rb|in|ev|ac (list/show sugar + extras)
# ─────────────────────────────────────────────────────────────────

def _make_kind_group(name: str, kind: str) -> click.Group:
    group = click.Group(name=name, help=f"{kind}_ artifacts (kind-bound queries)")

    @click.command("list")
    @click.option("--domain", default=None)
    @json_flag
    @pass_session
    def kind_list(session: Session, domain: str | None, as_json: bool) -> None:
        entries = session.resolver.list(kind=kind, domain=domain)
        result = [{"fqdn": f, "domain": e["domain"]} for f, e in entries]

        def text(records: list[dict[str, Any]]) -> None:
            heading(f"{kind} artifacts ({len(records)})")
            for r in records:
                fqdn_line(r["fqdn"])

        emit(as_json, {"command": f"{name} list", "domain": domain}, result, text)

    # `show` is sugar over `artifact show` with the kind verified.
    @click.command("show")
    @click.argument("ref")
    @json_flag
    @pass_session
    @click.pass_context
    def kind_show(ctx: click.Context, session: Session, ref: str, as_json: bool) -> None:
        fqdn, entry = session.resolver.resolve(ref)
        if entry["kind"] != kind:
            raise InspectionError(
                f"'{fqdn}' is kind {entry['kind']}, not {kind} — "
                f"use: pi {entry['kind'].lower()} show, or pi artifact show"
            )
        ctx.invoke(artifact_show, ref=fqdn, as_json=as_json)

    group.add_command(kind_list)
    group.add_command(kind_show)
    return group


_KIND_GROUPS = {name: _make_kind_group(name, kind) for name, kind in KIND_OBJECTS.items()}
for _group in _KIND_GROUPS.values():
    pi.add_command(_group)


@_KIND_GROUPS["wf"].command("lineage")
@click.argument("ref")
@json_flag
@pass_session
def wf_lineage(session: Session, ref: str, as_json: bool) -> None:
    """Execution tree: every node, every routed outcome."""
    fqdn, _ = session.resolver.resolve(ref)
    sub = session.graph.wf_subgraph(fqdn)

    routing_by_from: dict[str, list[dict[str, str]]] = {}
    for r in sub["routing"]:
        routing_by_from.setdefault(r["from"], []).append(r)

    def build(node_fqdn: str, on_path: frozenset) -> dict[str, Any]:
        node = {
            "fqdn": node_fqdn,
            "kind": session.graph.node_kind(node_fqdn),
            "children": [],
        }
        for r in routing_by_from.get(node_fqdn, []):
            if r["to"] in on_path:
                node["children"].append({
                    "fqdn": r["to"], "kind": session.graph.node_kind(r["to"]),
                    "edge_kind": r["condition"], "cycle": True, "children": [],
                })
                continue
            child = build(r["to"], on_path | {r["to"]})
            child["edge_kind"] = r["condition"]
            node["children"].append(child)
        return node

    trees = [build(start, frozenset({start})) for start in sub["start"]]
    result = {"workflow": fqdn, "execution_trees": trees}

    def text(r: dict[str, Any]) -> None:
        heading(f"Execution tree: {fqdn}")
        for tree in r["execution_trees"]:
            render_tree(tree)

    emit(as_json, {"command": "wf lineage", "target": fqdn}, result, text)


@_KIND_GROUPS["wf"].command("outcomes")
@click.argument("ref")
@json_flag
@pass_session
def wf_outcomes(session: Session, ref: str, as_json: bool) -> None:
    """Reachable terminal states declared by the workflow."""
    fqdn, entry = session.resolver.resolve(ref)
    pps_entry = session.workspace.pps_entry(fqdn, entry["kind"])
    nodes = pps_entry.get("nodes", {})
    terminals = []
    for node_name in sorted(nodes):
        node = nodes[node_name]
        if node.get("type") == "EXIT":
            routed_from = sorted(
                f"{src}:{cond}"
                for src, spec in nodes.items()
                for cond, target in (spec.get("next") or {}).items()
                if target == node_name
            )
            terminals.append({
                "terminal": node_name,
                "reason": node.get("reason", ""),
                "routed_from": routed_from,
            })
    result = {"workflow": fqdn, "terminals": terminals}

    def text(r: dict[str, Any]) -> None:
        heading(f"Terminal states: {fqdn}")
        for t in r["terminals"]:
            field(t["terminal"], t["reason"])
            for src in t["routed_from"]:
                fqdn_line(src, indent=6)

    emit(as_json, {"command": "wf outcomes", "target": fqdn}, result, text)


@_KIND_GROUPS["cc"].command("outcomes")
@click.argument("ref")
@json_flag
@pass_session
def cc_outcomes(session: Session, ref: str, as_json: bool) -> None:
    """Enumerated outcome set declared by the CC."""
    fqdn, _ = session.resolver.resolve(ref)
    outcomes = session.workspace.pps.get("cc_outcomes", {}).get(fqdn)
    if outcomes is None:
        pps_entry = session.workspace.pps_entry(fqdn, "CC")
        outcomes = pps_entry.get("outcomes", [])
    result = {"cc": fqdn, "outcomes": sorted(outcomes)}

    def text(r: dict[str, Any]) -> None:
        heading(f"Outcomes: {fqdn}")
        for o in r["outcomes"]:
            fqdn_line(o)

    emit(as_json, {"command": "cc outcomes", "target": fqdn}, result, text)


@_KIND_GROUPS["cc"].command("binding")
@click.argument("ref")
@json_flag
@pass_session
def cc_binding(session: Session, ref: str, as_json: bool) -> None:
    """CT/CS resolution via RB (execution mapping)."""
    fqdn, _ = session.resolver.resolve(ref)
    graph = session.graph
    targets = sorted({
        edge.target for edge in graph.out_edges(fqdn)
        if edge.kind in ("CC_BINDS_CT", "CC_BINDS_CS")
    })
    bindings = [
        {
            "binds": target,
            "kind": graph.node_kind(target),
            "mapped_by_rb": sorted({
                e.source for e in graph.in_edges(target) if e.kind == "RB_MAPS"
            }),
        }
        for target in targets
    ]
    result = {"cc": fqdn, "bindings": bindings}

    def text(r: dict[str, Any]) -> None:
        heading(f"Bindings: {fqdn}")
        for b in r["bindings"]:
            fqdn_line(b["binds"], f"[{b['kind']}]")
            for rb in b["mapped_by_rb"]:
                fqdn_line(rb, "[RB maps]", indent=6)

    emit(as_json, {"command": "cc binding", "target": fqdn}, result, text)


@_KIND_GROUPS["ct"].command("impl")
@click.argument("ref")
@json_flag
@pass_session
def ct_impl(session: Session, ref: str, as_json: bool) -> None:
    """Runtime bindings that map this CT to a concrete implementation."""
    fqdn, entry = session.resolver.resolve(ref)
    rbs = sorted({
        e.source for e in session.graph.in_edges(fqdn) if e.kind == "RB_MAPS"
    })
    result = {"ct": fqdn, "mapped_by_rb": rbs, "canonical_path": entry["canonical_path"]}

    def text(r: dict[str, Any]) -> None:
        heading(f"Implementation mapping: {fqdn}")
        for rb in r["mapped_by_rb"]:
            fqdn_line(rb, "[RB maps]")
        field("contract", r["canonical_path"])

    emit(as_json, {"command": "ct impl", "target": fqdn}, result, text)


@_KIND_GROUPS["cs"].command("surface")
@click.option("--domain", default=None)
@json_flag
@pass_session
def cs_surface(session: Session, domain: str | None, as_json: bool) -> None:
    """The enumerated side-effect surface — what can touch the world."""
    graph = session.graph
    entries = session.resolver.list(kind="CS", domain=domain)
    result = [
        {
            "fqdn": f,
            "domain": e["domain"],
            "mapped_by_rb": sorted({
                edge.source for edge in graph.in_edges(f) if edge.kind == "RB_MAPS"
            }),
        }
        for f, e in entries
    ]

    def text(records: list[dict[str, Any]]) -> None:
        heading(f"Side-effect surface ({len(records)} CS)")
        for r in records:
            fqdn_line(r["fqdn"])
            for rb in r["mapped_by_rb"]:
                fqdn_line(rb, "[RB maps]", indent=6)

    emit(as_json, {"command": "cs surface", "domain": domain}, result, text)


@_KIND_GROUPS["rb"].command("resolve")
@click.argument("ref")
@json_flag
@pass_session
def rb_resolve(session: Session, ref: str, as_json: bool) -> None:
    """Which RB binds this CT/CS declaration, to what."""
    fqdn, entry = session.resolver.resolve(ref)
    if entry["kind"] not in ("CT", "CS"):
        raise InspectionError(
            f"'{fqdn}' is kind {entry['kind']} — rb resolve takes a CT or CS FQDN"
        )
    rbs = sorted({
        e.source for e in session.graph.in_edges(fqdn) if e.kind == "RB_MAPS"
    })
    result = {"declaration": fqdn, "kind": entry["kind"], "resolved_by": rbs}

    def text(r: dict[str, Any]) -> None:
        heading(f"RB resolution: {fqdn}")
        for rb in r["resolved_by"]:
            fqdn_line(rb)

    emit(as_json, {"command": "rb resolve", "target": fqdn}, result, text)


# ─────────────────────────────────────────────────────────────────
# pi topology — reachability and closure (the change-mgmt workhorse)
# ─────────────────────────────────────────────────────────────────

@pi.group()
def topology() -> None:
    """Reachability and closure across the federated graph."""


@topology.command("wf")
@click.argument("ref")
@json_flag
@pass_session
def topology_wf(session: Session, ref: str, as_json: bool) -> None:
    """Full reachability graph of a workflow."""
    fqdn, _ = session.resolver.resolve(ref)
    result = session.graph.wf_subgraph(fqdn)

    def text(r: dict[str, Any]) -> None:
        heading(f"Topology: {fqdn}")
        field("start", ", ".join(r["start"]))
        field("members", len(r["members"]))
        for m in r["members"]:
            fqdn_line(m, f"[{session.graph.node_kind(m)}]", indent=4)
        field("runtime bindings", ", ".join(r["runtime_bindings"]) or "(none)")
        heading("Routing:")
        for route in r["routing"]:
            click.echo(f"  {route['from']}  ──{route['condition']}──▶  {route['to']}")

    emit(as_json, {"command": "topology wf", "target": fqdn}, result, text)


@topology.command("cc")
@click.argument("ref")
@json_flag
@pass_session
def topology_cc(session: Session, ref: str, as_json: bool) -> None:
    """Every WF position this artifact occupies, with routing context."""
    fqdn, _ = session.resolver.resolve(ref)
    result = {"artifact": fqdn, "positions": session.graph.cc_positions(fqdn)}

    def text(r: dict[str, Any]) -> None:
        heading(f"WF positions: {fqdn}")
        for wf, pos in r["positions"].items():
            fqdn_line(wf)
            for inc in pos["incoming"]:
                click.echo(f"      ◀── {inc['from']}  [{inc['condition']}]")
            for out in pos["outgoing"]:
                click.echo(f"      ──▶ {out['to']}  [{out['condition']}]")

    emit(as_json, {"command": "topology cc", "target": fqdn}, result, text)


@topology.command("impact")
@click.argument("ref")
@json_flag
@pass_session
def topology_impact(session: Session, ref: str, as_json: bool) -> None:
    """Transitive consumer closure, grouped by kind and domain."""
    fqdn, _ = session.resolver.resolve(ref)
    grouped = session.graph.impact(fqdn)
    total = sum(len(fqdns) for domains in grouped.values() for fqdns in domains.values())
    result = {"artifact": fqdn, "impacted_count": total, "impacted": grouped}

    def text(r: dict[str, Any]) -> None:
        heading(f"Impact closure ({r['impacted_count']}): {fqdn}")
        for kind, domains in r["impacted"].items():
            click.echo(click.style(f"  {kind}", bold=True))
            for domain, fqdns in domains.items():
                for f in fqdns:
                    fqdn_line(f, f"[{domain}]", indent=4)

    emit(as_json, {"command": "topology impact", "target": fqdn}, result, text)


@topology.command("path")
@click.argument("source_ref")
@click.argument("target_ref")
@json_flag
@pass_session
def topology_path(session: Session, source_ref: str, target_ref: str, as_json: bool) -> None:
    """Is target reachable from source — show the shortest path(s)."""
    source, _ = session.resolver.resolve(source_ref)
    target, _ = session.resolver.resolve(target_ref)
    paths = session.graph.paths(source, target)
    result = {"source": source, "target": target, "reachable": bool(paths), "paths": paths}

    def text(r: dict[str, Any]) -> None:
        heading(f"Path: {source} → {target}")
        if not r["reachable"]:
            click.echo("  not reachable")
            return
        for p in r["paths"]:
            click.echo("  " + "  ──▶  ".join(p))

    emit(
        as_json,
        {"command": "topology path", "source": source, "target": target},
        result,
        text,
    )


# ─────────────────────────────────────────────────────────────────
# pi vocab — the address space
# ─────────────────────────────────────────────────────────────────

@pi.group()
def vocab() -> None:
    """Vocabulary / address-space queries."""


@vocab.command("search")
@click.argument("term")
@json_flag
@pass_session
def vocab_search(session: Session, term: str, as_json: bool) -> None:
    """Substring search over all indexed FQDNs (case-insensitive)."""
    needle = term.lower()
    result = [
        {"fqdn": f, "kind": e["kind"], "domain": e["domain"]}
        for f, e in session.resolver.list()
        if needle in f.lower()
    ]

    def text(records: list[dict[str, Any]]) -> None:
        heading(f"Matches ({len(records)}): '{term}'")
        for r in records:
            fqdn_line(r["fqdn"], f"[{r['kind']}]")

    emit(as_json, {"command": "vocab search", "term": term}, result, text)


@vocab.command("resolve")
@click.argument("ref")
@json_flag
@pass_session
def vocab_resolve(session: Session, ref: str, as_json: bool) -> None:
    """FQDN → domain, structures, kind, paths (the resolver, exposed)."""
    fqdn, entry = session.resolver.resolve(ref)
    result = {"fqdn": fqdn, **entry}

    def text(r: dict[str, Any]) -> None:
        heading(f"Resolved: {fqdn}")
        for key in ("kind", "domain", "canonical_path"):
            field(key, r[key])
        field("structures", ", ".join(r["structures"]) or "(none)")
        for scope, addr in r["addresses"].items():
            field(f"address[{scope}]", addr)
        for scope, path in r["evidence_paths"].items():
            field(f"evidence[{scope}]", path)

    emit(as_json, {"command": "vocab resolve", "target": fqdn}, result, text)


@vocab.command("stats")
@json_flag
@pass_session
def vocab_stats(session: Session, as_json: bool) -> None:
    """Vocabulary size by scope and indexed artifacts by domain."""
    ws = session.workspace
    by_domain: dict[str, int] = {}
    for _, entry in session.resolver.list():
        by_domain[entry["domain"]] = by_domain.get(entry["domain"], 0) + 1
    result = {
        "address_space_by_scope": {
            scope: len(ws.vocabulary_reverse(scope)) for scope in ws.scopes
        },
        "indexed_artifacts_by_domain": dict(sorted(by_domain.items())),
    }

    def text(r: dict[str, Any]) -> None:
        heading("Address space (entries per scope)")
        for scope, count in r["address_space_by_scope"].items():
            field(scope, count)
        heading("Indexed artifacts (per domain)")
        for domain, count in r["indexed_artifacts_by_domain"].items():
            field(domain, count)

    emit(as_json, {"command": "vocab stats"}, result, text)


# ─────────────────────────────────────────────────────────────────
# pi pps — the authoring projection surface
# ─────────────────────────────────────────────────────────────────

@pi.group()
def pps() -> None:
    """PPS snapshot (authoring surface) queries."""


@pps.command("stats")
@json_flag
@pass_session
def pps_stats(session: Session, as_json: bool) -> None:
    """PPS coverage: indexed artifacts by kind, domains, subdomains."""
    index = session.workspace.pps
    result = {
        "version": index.get("version"),
        "generated_at": index.get("generated_at"),
        "counts": {
            section: len(index.get(section, {}))
            for section in sorted(set(PPS_SECTION_BY_KIND.values()))
        },
        "domains": sorted(index.get("domains", {})),
        "subdomains": sorted(index.get("subdomains", {})),
    }

    def text(r: dict[str, Any]) -> None:
        heading("PPS coverage")
        for section, count in r["counts"].items():
            field(section, count)
        field("domains", ", ".join(r["domains"]))
        field("subdomains", ", ".join(r["subdomains"]))

    emit(as_json, {"command": "pps stats"}, result, text)


@pps.command("list")
@click.option("--kind", type=click.Choice(sorted(PPS_SECTION_BY_KIND)), default=None)
@json_flag
@pass_session
def pps_list(session: Session, kind: str | None, as_json: bool) -> None:
    """FQDNs present on the authoring surface."""
    index = session.workspace.pps
    sections = (
        {kind: PPS_SECTION_BY_KIND[kind]}
        if kind else dict(sorted(PPS_SECTION_BY_KIND.items()))
    )
    result = {
        k: sorted(index.get(section, {})) for k, section in sections.items()
    }

    def text(r: dict[str, list[str]]) -> None:
        for k, fqdns in r.items():
            heading(f"{k} ({len(fqdns)})")
            for f in fqdns:
                fqdn_line(f)

    emit(as_json, {"command": "pps list", "kind": kind}, result, text)


@pps.command("show")
@click.argument("ref")
@json_flag
@pass_session
def pps_show(session: Session, ref: str, as_json: bool) -> None:
    """Raw PPS entry: parsed header + authoring Markdown."""
    fqdn, entry = session.resolver.resolve(ref)
    pps_entry = session.workspace.pps_entry(fqdn, entry["kind"])
    result = pps_entry

    def text(r: dict[str, Any]) -> None:
        heading(f"PPS entry: {fqdn}")
        for key in sorted(r):
            if key == "raw":
                continue
            field(key, r[key])
        click.echo()
        click.echo(r.get("raw", {}).get("content", ""))

    emit(as_json, {"command": "pps show", "target": fqdn}, result, text)


# ─────────────────────────────────────────────────────────────────
# pi snapshot — snapshot-level views
# ─────────────────────────────────────────────────────────────────

@pi.group()
def snapshot() -> None:
    """Snapshot-level status and structure queries."""


@snapshot.command("status")
@json_flag
@pass_session
def snapshot_status(session: Session, as_json: bool) -> None:
    """snapshot_status.json: valid? when built? what hash?"""
    result = session.workspace.snapshot_status

    def text(r: dict[str, Any]) -> None:
        heading("Snapshot status")
        for key in sorted(r):
            field(key, r[key])

    emit(as_json, {"command": "snapshot status"}, result, text)


@snapshot.command("discover")
@click.option("--domain", required=True, help="the CR's domain (e.g. blockchain)")
@click.option("--subdomain", default=None, help="the CR's subdomain (e.g. chain)")
@click.option("--tokens", required=True,
              help="declared transformation-scope concept tokens, comma-separated (e.g. BLOCK,COMMIT)")
@json_flag
@pass_session
def snapshot_discover(session: Session, domain: str, subdomain: str | None,
                      tokens: str, as_json: bool) -> None:
    """Discovery Projection — the governed semantic neighbourhood for a transformation scope.

    The platform ACQUIRES the neighbourhood deterministically (existing / absent / structural /
    relationships / authority evidence, each existing node with inclusion provenance). It never
    DISPOSES of it — RELEVANT/EXCLUDED/NEW are the worker's judgment (SPP)."""
    from pgs_compiler.inspection.discovery import (
        TransformationScope, compute_discovery_projection)
    scope = TransformationScope(
        domain=domain, subdomain=subdomain,
        concept_tokens=tuple(t.strip().upper() for t in tokens.split(",") if t.strip()))
    result = compute_discovery_projection(session.graph, scope)

    def text(r: dict[str, Any]) -> None:
        ident, ev = r["projection_identity"], r["evidence"]
        heading(f"Discovery Projection — {ident['subject']}")
        field("projection_id", ident["projection_id"])
        field("source_snapshot_id", ident["source_snapshot_id"])
        field("roots", len(ident["bounds"]["roots"]))
        heading("Evidence")
        field("existing", len(ev["existing"]))
        field("absent (negative)", ", ".join(a["concept"] for a in ev["absent"]) or "(none)")
        field("orphans", len(ev["structural"]["orphans"]))
        field("dangling_references", len(ev["structural"]["dangling_references"]))
        field("relationships", len(ev["relationships"]))
        by_kind: dict[str, int] = {}
        for n in ev["existing"]:
            by_kind[n["kind"]] = by_kind.get(n["kind"], 0) + 1
        heading("Neighbourhood by kind")
        for k, v in sorted(by_kind.items()):
            field(k, v)

    emit(as_json, {"command": "snapshot discover"}, result, text)


@snapshot.command("impact-projection")
@click.argument("ref")
@json_flag
@pass_session
def snapshot_impact_projection(session: Session, ref: str, as_json: bool) -> None:
    """Impact Projection — the governed blast radius (transitive consumers) of an artifact.

    A second Semantic Projection sharing the Discovery contract (identity, determinism, closure). The
    platform ACQUIRES who is impacted; whether that impact matters to a change is the worker's judgment
    (Knowledge Partition Theorem). The Public Semantic Surface (cross-boundary consumers) is well-defined
    here because the subject already exists."""
    from pgs_compiler.inspection.impact_projection import compute_impact_projection
    fqdn, _ = session.resolver.resolve(ref)
    result = compute_impact_projection(session.graph, fqdn)

    def text(r: dict[str, Any]) -> None:
        ident, ev = r["projection_identity"], r["evidence"]
        heading(f"Impact Projection — {ident['subject']}")
        field("projection_id", ident["projection_id"])
        field("source_snapshot_id", ident["source_snapshot_id"])
        field("impacted", len(ev["impacted"]))
        field("direct consumers", len(ev["direct"]))
        field("public surface (cross-boundary)", len(ev["public_surface"]))
        heading("Impacted by kind")
        for k, v in ev["by_kind"].items():
            field(k, v)

    emit(as_json, {"command": "snapshot impact-projection", "target": fqdn}, result, text)


@snapshot.command("semantic-model")
@json_flag
@pass_session
def snapshot_semantic_model(session: Session, as_json: bool) -> None:
    """Semantic Model — every artifact's deterministically-derived semantic dimensions.

    The substrate under the projections (the Semantic Dimension Model): projections become queries over
    one model. Every dimension carries its derivation source; a property that would need inference is not
    a dimension but a disposition (Knowledge Partition Theorem). `undetermined` counts are the signal for
    the next compiler-model enrichment."""
    from pgs_compiler.inspection.semantic_model import (
        compute_semantic_model, derivation_coverage, DIMENSIONS)
    model = compute_semantic_model(session.graph, session.workspace)
    cov = derivation_coverage(model)
    result = {"artifacts": len(model), "dimensions": list(DIMENSIONS), "derivation_coverage": cov}

    def text(r: dict[str, Any]) -> None:
        heading(f"Semantic Model — {r['artifacts']} artifacts × {len(r['dimensions'])} dimensions")
        for d in r["dimensions"]:
            c = r["derivation_coverage"][d]
            field(d, f"{c['determined']} determined · {c['undetermined']} undetermined")

    emit(as_json, {"command": "snapshot semantic-model"}, result, text)


@snapshot.command("summary")
@json_flag
@pass_session
def snapshot_summary(session: Session, as_json: bool) -> None:
    """Domains, structures, artifact counts by kind."""
    index = session.workspace.artifact_index
    by_kind: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for entry in index["artifacts"].values():
        by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
        by_domain[entry["domain"]] = by_domain.get(entry["domain"], 0) + 1
    result = {
        "artifact_count": index["artifact_count"],
        "compiler_version": index["compiler_version"],
        "structures": index["structures"],
        "by_kind": dict(sorted(by_kind.items())),
        "by_domain": dict(sorted(by_domain.items())),
    }

    def text(r: dict[str, Any]) -> None:
        heading("Snapshot summary")
        field("artifacts", r["artifact_count"])
        field("compiler", r["compiler_version"])
        heading("Structures")
        for scope, structure in r["structures"].items():
            field(scope, structure)
        heading("By kind")
        for kind, count in r["by_kind"].items():
            field(kind, count)
        heading("By domain")
        for domain, count in r["by_domain"].items():
            field(domain, count)

    emit(as_json, {"command": "snapshot summary"}, result, text)


@snapshot.command("topology")
@json_flag
@pass_session
def snapshot_topology(session: Session, as_json: bool) -> None:
    """Domain → subdomain → workflow map (the FB boundary view)."""
    workflows = session.workspace.pps.get("workflows", {})
    nested: dict[str, dict[str, list[str]]] = {}
    for fqdn in sorted(workflows):
        wf = workflows[fqdn]
        domain = wf.get("namespace", fqdn.split("::", 1)[0])
        subdomain = wf.get("subdomain", "(undeclared)")
        nested.setdefault(domain, {}).setdefault(subdomain, []).append(fqdn)
    result = {d: dict(sorted(s.items())) for d, s in sorted(nested.items())}

    def text(r: dict[str, Any]) -> None:
        heading("Snapshot topology (domain → subdomain → WF)")
        for domain, subs in r.items():
            click.echo(click.style(f"  {domain}", bold=True))
            for subdomain, fqdns in subs.items():
                click.echo(f"    {subdomain}")
                for f in fqdns:
                    fqdn_line(f, indent=6)

    emit(as_json, {"command": "snapshot topology"}, result, text)


@snapshot.command("stats")
@json_flag
@pass_session
def snapshot_stats(session: Session, as_json: bool) -> None:
    """Graph metrics: nodes, edges, kinds, orphans."""
    result = session.graph.stats()

    def text(r: dict[str, Any]) -> None:
        heading("Semantic graph stats (federated)")
        field("nodes", r["node_count"])
        field("edges", r["edge_count"])
        heading("Nodes by kind")
        for kind, count in r["nodes_by_kind"].items():
            field(kind, count)
        heading("Edges by kind")
        for kind, count in r["edges_by_kind"].items():
            field(kind, count)
        heading(f"Orphans ({len(r['orphans'])}) — nodes with no graph edges, by kind")
        for kind, fqdns in r["orphans_by_kind"].items():
            click.echo(click.style(f"  {kind}  ({len(fqdns)})", bold=True))
            for f in fqdns:
                fqdn_line(f, indent=4)

    emit(as_json, {"command": "snapshot stats"}, result, text)


# ─────────────────────────────────────────────────────────────────
# pi artifact lifecycle — degraded form until the AR_ model lands
# ─────────────────────────────────────────────────────────────────

@artifact.command("lifecycle")
@click.argument("ref")
@json_flag
@pass_session
def artifact_lifecycle(session: Session, ref: str, as_json: bool) -> None:
    """Declared status + supersession (degraded: ACTIVE/RETIRED/UNKNOWN)."""
    fqdn, entry = session.resolver.resolve(ref)
    canonical = session.workspace.canonical_artifact(entry)
    header = parse_header_fields(canonical.get("content", ""))
    declared = header.get("Status")
    result = {
        "fqdn": fqdn,
        "lifecycle": classify_lifecycle(declared),
        "declared_status": declared,
        "supersedes": header.get("Supersedes"),
        "note": "degraded lifecycle — supersession chains arrive with the AR_ model",
    }

    def text(r: dict[str, Any]) -> None:
        heading(f"Lifecycle: {fqdn}")
        field("lifecycle", r["lifecycle"])
        field("declared status", r["declared_status"] or "(not declared)")
        field("supersedes", r["supersedes"] or "(not declared)")

    emit(as_json, {"command": "artifact lifecycle", "target": fqdn}, result, text)


# ─────────────────────────────────────────────────────────────────
# pi behavior_logic — reads *.graph.json, never the PNGs
# ─────────────────────────────────────────────────────────────────

@pi.group(name="behavior_logic")
def behavior_logic() -> None:
    """Behavior Logic projections."""


def _behavior_logic_code(session: Session, ref: str) -> tuple[str, str]:
    """Resolve a WF reference to (fqdn, behavior logic directory code)."""
    fqdn, entry = session.resolver.resolve(ref)
    if entry["kind"] != "WF":
        raise InspectionError(f"'{fqdn}' is kind {entry['kind']} — behavior_logic takes a WF FQDN")
    return fqdn, fqdn.split("::", 1)[1]


@behavior_logic.command("list")
@click.option("--domain", default=None)
@json_flag
@pass_session
def behavior_logic_list(session: Session, domain: str | None, as_json: bool) -> None:
    """Workflows with a materialized behavior logic projection."""
    wf_by_code = {
        f.split("::", 1)[1]: (f, e["domain"])
        for f, e in session.resolver.list(kind="WF")
    }
    result = [
        {"code": code, "workflow": wf_by_code[code][0], "domain": wf_by_code[code][1]}
        for code in session.workspace.behavior_logic_codes()
        if code in wf_by_code
        and (domain is None or wf_by_code[code][1] == domain)
    ]

    def text(records: list[dict[str, Any]]) -> None:
        heading(f"Behavior Logic ({len(records)})")
        for r in records:
            fqdn_line(r["workflow"], f"[{r['domain']}]")

    emit(as_json, {"command": "behavior_logic list", "domain": domain}, result, text)


@behavior_logic.command("show")
@click.argument("ref")
@json_flag
@pass_session
def behavior_logic_show(session: Session, ref: str, as_json: bool) -> None:
    """Terminal tree render of the behavior logic (from graph.json)."""
    fqdn, code = _behavior_logic_code(session, ref)
    graph = session.workspace.behavior_logic_graph(code)
    tree = behavior_logic_lib.execution_tree(graph)
    result = {"workflow": fqdn, "entry": graph["entry"], "tree": tree}

    def text(r: dict[str, Any]) -> None:
        heading(f"Behavior Logic: {fqdn}")
        render_tree(r["tree"])

    emit(as_json, {"command": "behavior_logic show", "target": fqdn}, result, text)


@behavior_logic.command("render")
@click.argument("ref")
@click.option("--mermaid", "form", flag_value="mermaid")
@click.option("--dot", "form", flag_value="dot")
@pass_session
def behavior_logic_render(session: Session, ref: str, form: str | None) -> None:
    """Emit the behavior logic as Mermaid or DOT text (stdout only — pi writes nothing)."""
    if form is None:
        raise InspectionError("declare an output form: --mermaid or --dot")
    fqdn, code = _behavior_logic_code(session, ref)
    graph = session.workspace.behavior_logic_graph(code)
    click.echo(behavior_logic_lib.to_mermaid(graph) if form == "mermaid" else behavior_logic_lib.to_dot(graph))


@behavior_logic.command("open")
@click.argument("ref")
@pass_session
def behavior_logic_open(session: Session, ref: str) -> None:
    """Open the compiler-materialized behavior logic PNG."""
    fqdn, code = _behavior_logic_code(session, ref)
    png = session.workspace.behavior_logic_png_path(code)
    click.echo(f"opening {png}")
    click.launch(str(png))


# ─────────────────────────────────────────────────────────────────
# pi trace — delegating facade (traces belong to pgs_runtime examine)
# ─────────────────────────────────────────────────────────────────

@pi.group()
def trace() -> None:
    """Trace listing + delegation to pgs_runtime examine."""


@trace.command("list")
@click.option("--domain", default=None)
@click.option("--workflow", default=None)
@json_flag
@pass_session
def trace_list(session: Session, domain: str | None, workflow: str | None, as_json: bool) -> None:
    """Enumerate the traces/ tree (filesystem listing only)."""
    result = trace_lib.list_traces(session.workspace.root, domain, workflow)

    def text(records: list[dict[str, Any]]) -> None:
        heading(f"Traces ({len(records)})")
        for r in records:
            fqdn_line(r["trace_id"], f"[{r['domain']}/{r['workflow']}]")

    emit(as_json, {"command": "trace list", "domain": domain, "workflow": workflow}, result, text)


@trace.command("explain")
@click.argument("trace_id")
@pass_session
def trace_explain(session: Session, trace_id: str) -> None:
    """Delegates to: pgs_runtime examine <trace>.jsonl"""
    import shutil
    import subprocess

    jsonl = trace_lib.resolve_trace_jsonl(session.workspace.root, trace_id)
    runtime = shutil.which("pgs_runtime")
    if runtime is None:
        raise InspectionError(
            "pgs_runtime not found on PATH — trace analysis belongs to the "
            "runtime; install/activate the environment that provides it"
        )
    completed = subprocess.run([runtime, "examine", str(jsonl)], check=False)
    if completed.returncode != 0:
        sys.exit(completed.returncode)


# ─────────────────────────────────────────────────────────────────
# pi store — storage ownership (from the materialized store index)
# ─────────────────────────────────────────────────────────────────

@pi.group()
def store() -> None:
    """Entity-store ownership and consumers."""


def _resolve_store(session: Session, name: str) -> tuple[str, dict[str, Any]]:
    """'domain::STORE' exact, or bare STORE when unique across domains."""
    stores = session.workspace.store_index["stores"]
    if "::" in name:
        if name not in stores:
            raise UnresolvedFqdn(f"store not in store index: {name}")
        return name, stores[name]
    candidates = sorted(k for k in stores if k.split("::", 1)[1] == name)
    if not candidates:
        raise UnresolvedFqdn(f"store '{name}' not declared by any storage STRUCTURE")
    if len(candidates) > 1:
        raise AmbiguousCode(name, candidates)
    return candidates[0], stores[candidates[0]]


@store.command("list")
@click.option("--domain", default=None)
@json_flag
@pass_session
def store_list(session: Session, domain: str | None, as_json: bool) -> None:
    """All declared entity stores."""
    stores = session.workspace.store_index["stores"]
    result = [
        {
            "store": key,
            "path": declaration["path"],
            "declared_by": declaration["declared_by"],
        }
        for key, s in sorted(stores.items())
        if domain is None or s["domain"] == domain
        for declaration in s["declarations"]
    ]

    def text(records: list[dict[str, Any]]) -> None:
        heading(f"Entity store declarations ({len(records)})")
        for r in records:
            fqdn_line(r["store"], r["path"])

    emit(as_json, {"command": "store list", "domain": domain}, result, text)


@store.command("show")
@click.argument("name")
@json_flag
@pass_session
def store_show(session: Session, name: str, as_json: bool) -> None:
    """Owning structure + declared data path + binding surface."""
    key, entry = _resolve_store(session, name)
    result = {"store": key, **entry}

    def text(r: dict[str, Any]) -> None:
        heading(f"Store: {key}")
        for d in r["declarations"]:
            field("path", d["path"])
            field("declared by", d["declared_by"], indent=4)
            field("description", d["description"], indent=4)
            for b in d["bindings"]:
                fqdn_line(b["rb"], f"via {b['cs']}", indent=4)
                for wf in b["workflows"]:
                    fqdn_line(wf, "[WF]", indent=8)

    emit(as_json, {"command": "store show", "target": key}, result, text)


@store.command("consumers")
@click.argument("name")
@json_flag
@pass_session
def store_consumers(session: Session, name: str, as_json: bool) -> None:
    """CCs that touch this store (via RB-bound side effects)."""
    key, entry = _resolve_store(session, name)
    consumers = sorted({
        cc
        for declaration in entry["declarations"]
        for b in declaration["bindings"]
        for cc in b["consumer_ccs"]
    })
    result = {"store": key, "consumer_ccs": consumers}

    def text(r: dict[str, Any]) -> None:
        heading(f"Consumers of {key} ({len(r['consumer_ccs'])})")
        for cc in r["consumer_ccs"]:
            fqdn_line(cc)

    emit(as_json, {"command": "store consumers", "target": key}, result, text)


# ─────────────────────────────────────────────────────────────────
# pi snapshot validate / violations  +  top-level conveniences
# ─────────────────────────────────────────────────────────────────

@snapshot.command("validate")
@json_flag
@pass_session
def snapshot_validate(session: Session, as_json: bool) -> None:
    """Conformance / validation state of the snapshot (pure query)."""
    status = session.workspace.snapshot_status
    conformance = session.workspace.conformance_results
    result = {
        "status": status.get("status"),
        "snapshot_hash": status.get("snapshot_hash"),
        "conformance": {
            "passed": conformance["passed"],
            "failed": conformance["failed"],
            "artifact_count": conformance["artifact_count"],
        },
    }

    def text(r: dict[str, Any]) -> None:
        heading("Snapshot validation")
        field("status", r["status"])
        field("snapshot hash", r["snapshot_hash"])
        field("conformance", f"{r['conformance']['passed']}/{r['conformance']['artifact_count']} passed")

    emit(as_json, {"command": "snapshot validate"}, result, text)


@snapshot.command("violations")
@click.option("--strict", is_flag=True, help="Exit non-zero if violations exist (CI gate)")
@json_flag
@pass_session
def snapshot_violations(session: Session, strict: bool, as_json: bool) -> None:
    """Unsatisfied conformance cases, with failing artifacts named."""
    conformance = session.workspace.conformance_results
    failures = [c for c in conformance["cases"] if not c["passed"]]
    result = {"violation_count": len(failures), "violations": failures}

    def text(r: dict[str, Any]) -> None:
        heading(f"Violations ({r['violation_count']})")
        for v in r["violations"]:
            fqdn_line(v["fqdn"])
            if v.get("error"):
                for line in str(v["error"]).splitlines():
                    click.echo(f"      {line}")
        if not r["violations"]:
            click.echo("  (none — all conformance cases pass)")

    emit(as_json, {"command": "snapshot violations", "strict": strict}, result, text)
    if strict and failures:
        sys.exit(1)


@pi.command("validate")
@click.option("--strict", is_flag=True, help="Exit non-zero unless VALID with zero violations")
@json_flag
@pass_session
def validate(session: Session, strict: bool, as_json: bool) -> None:
    """Snapshot validity + violations in one pass (CI entry point)."""
    status = session.workspace.snapshot_status
    conformance = session.workspace.conformance_results
    failures = [c for c in conformance["cases"] if not c["passed"]]
    valid = status.get("status") == "VALID" and not failures
    result = {
        "valid": valid,
        "status": status.get("status"),
        "snapshot_hash": status.get("snapshot_hash"),
        "conformance_passed": conformance["passed"],
        "conformance_failed": conformance["failed"],
        "violations": failures,
    }

    def text(r: dict[str, Any]) -> None:
        heading("Validation")
        field("valid", r["valid"])
        field("status", r["status"])
        field("conformance", f"{r['conformance_passed']} passed, {r['conformance_failed']} failed")
        for v in r["violations"]:
            fqdn_line(v["fqdn"], "FAILED")

    emit(as_json, {"command": "validate", "strict": strict}, result, text)
    if strict and not valid:
        sys.exit(1)


@pi.command("stats")
@json_flag
@pass_session
def stats(session: Session, as_json: bool) -> None:
    """Workspace-wide one-screen summary."""
    status = session.workspace.snapshot_status
    index = session.workspace.artifact_index
    graph_stats = session.graph.stats()
    result = {
        "snapshot": {
            "status": status.get("status"),
            "snapshot_hash": status.get("snapshot_hash"),
            "timestamp": status.get("timestamp"),
        },
        "artifacts": index["artifact_count"],
        "stores": session.workspace.store_index["store_count"],
        "graph": {
            "nodes": graph_stats["node_count"],
            "edges": graph_stats["edge_count"],
        },
        "pps": {
            section: len(session.workspace.pps.get(section, {}))
            for section in sorted(set(PPS_SECTION_BY_KIND.values()))
        },
    }

    def text(r: dict[str, Any]) -> None:
        heading("Workspace stats")
        field("snapshot", f"{r['snapshot']['status']}  ({r['snapshot']['snapshot_hash']})")
        field("artifacts", r["artifacts"])
        field("stores", r["stores"])
        field("graph", f"{r['graph']['nodes']} nodes / {r['graph']['edges']} edges")
        for section, count in r["pps"].items():
            field(f"pps.{section}", count)

    emit(as_json, {"command": "stats"}, result, text)


# ─────────────────────────────────────────────────────────────────
# entry point
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        pi(prog_name="pi")
    except InspectionError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
