"""
structure_tree.py — Structure Tree Governance Loader.

Single source of truth for package structure, build order, and registry discovery.
All paths derived from STRUCTURE_FQDN_TREE_V0.md.
"""

import hashlib
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml


class StructureTreeError(Exception):
    """Structure tree loading or validation failed."""


@dataclass(frozen=True)
class PackageRoots:
    """Dual roots for role-aware path resolution."""
    engine_root: Path       # Core/capability_pack packages
    workspace_root: Path    # Domain-pack packages


DOMAIN_PACK_ROLES = frozenset({"domain_pack"})


@dataclass(frozen=True)
class Registry:
    """Declared registry within a package."""
    path: str
    artifact_types: tuple[str, ...]


@dataclass(frozen=True)
class Package:
    """Declared package in the structure tree."""
    package: str
    role: str
    authority: str
    build_order: int
    physical_root: str
    module_root: str
    contains: tuple[str, ...]
    registries: tuple[Registry, ...]
    depends_on: tuple[str, ...]
    conformance_generation: bool = True


@dataclass(frozen=True)
class ArtifactPattern:
    """Pattern for an artifact type."""
    file_pattern: str
    code_key: str
    exclude_patterns: tuple[str, ...] = ()
    enforce_code_match: bool = True


class StructureTree:
    """Immutable structure tree. No scanning — everything explicit."""

    __slots__ = ("code", "version", "content_hash", "packages", "artifact_patterns",
                 "role_artifact_rules", "_packages_sorted")

    def __init__(
        self,
        code: str,
        version: str,
        content_hash: str,
        packages: tuple[Package, ...],
        artifact_patterns: dict[str, ArtifactPattern],
        role_artifact_rules: dict[str, tuple[str, ...]] | None = None,
    ):
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "packages", packages)
        object.__setattr__(self, "artifact_patterns", artifact_patterns)
        object.__setattr__(self, "role_artifact_rules", role_artifact_rules or {})
        object.__setattr__(self, "_packages_sorted",
                           tuple(sorted(packages, key=lambda p: p.build_order)))

    def packages_by_order(self) -> tuple[Package, ...]:
        """Packages sorted by build_order (cached)."""
        return self._packages_sorted

    def get_package(self, name: str) -> Package | None:
        """Get package by name."""
        for p in self.packages:
            if p.package == name:
                return p
        return None

    def resolve_root(self, pkg: Package, roots: PackageRoots) -> Path:
        """Resolve the correct root for a package based on its role."""
        if pkg.role in DOMAIN_PACK_ROLES:
            return roots.workspace_root
        return roots.engine_root

    def registry_paths(self, artifact_type: str, roots: PackageRoots) -> list[Path]:
        """All registry paths for an artifact type."""
        paths = []
        for pkg in self.packages_by_order():
            root = self.resolve_root(pkg, roots)
            for reg in pkg.registries:
                if artifact_type in reg.artifact_types:
                    paths.append(root / reg.path / artifact_type)
        return paths

    def artifacts_dir(self, pkg: Package, roots: PackageRoots) -> Path:
        """Artifacts output directory for a package."""
        root = self.resolve_root(pkg, roots)
        return root / pkg.physical_root.lstrip("./") / "protocol" / "artifacts"

    def ct_ir_dir(self, pkg: Package, roots: PackageRoots) -> Path:
        """CT-IR output directory for compiled molecules."""
        root = self.resolve_root(pkg, roots)
        return root / pkg.physical_root.lstrip("./") / "protocol" / "artifacts" / "ct_ir"


def parse_machine_block(content: str) -> dict:
    """Extract and parse ## Machine YAML block from markdown."""
    match = re.search(
        r"^## Machine\s*\n+```(?:yaml|json)?\s*\n(.+?)```",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise StructureTreeError("No ## Machine block found")
    return yaml.safe_load(match.group(1))


def load(path: Path) -> StructureTree:
    """Load and validate structure tree."""
    if not path.exists():
        raise StructureTreeError(f"Structure tree not found: {path}")

    content = path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    machine = parse_machine_block(content)

    # Validate required fields
    required = ["fqdn_tree_code", "version", "packages", "artifact_patterns"]
    missing = [f for f in required if f not in machine]
    if missing:
        raise StructureTreeError(f"Missing required fields: {missing}")

    # Parse packages
    packages = tuple(
        Package(
            package=p["package"],
            role=p["role"],
            authority=p["authority"],
            build_order=p["build_order"],
            physical_root=p["physical_root"],
            module_root=p.get("module_root", p["physical_root"].lstrip("./").replace("/", ".")),
            contains=tuple(p.get("contains", [])),
            registries=tuple(
                Registry(path=r["path"], artifact_types=tuple(r.get("artifact_types", [])))
                for r in p.get("registries", [])
            ),
            depends_on=tuple(p.get("depends_on", [])),
            conformance_generation=p.get("conformance_generation", True),
        )
        for p in machine["packages"]
    )

    # Parse artifact patterns
    patterns = {
        name: ArtifactPattern(
            file_pattern=p["file_pattern"],
            code_key=p["code_key"],
            exclude_patterns=tuple(p.get("exclude_patterns", [])),
            enforce_code_match=p.get("enforce_code_match", True),
        )
        for name, p in machine["artifact_patterns"].items()
    }

    # Parse role artifact rules (domain isolation enforcement)
    role_rules: dict[str, tuple[str, ...]] | None = None
    raw_rules = machine.get("role_artifact_rules")
    if raw_rules and isinstance(raw_rules, dict):
        role_rules = {
            role: tuple(types) for role, types in raw_rules.items()
        }

    # Validate dependencies
    names = {p.package for p in packages}
    for pkg in packages:
        for dep in pkg.depends_on:
            if dep not in names:
                raise StructureTreeError(f"Package '{pkg.package}' depends on unknown '{dep}'")
            dep_pkg = next(p for p in packages if p.package == dep)
            if dep_pkg.build_order >= pkg.build_order:
                raise StructureTreeError(
                    f"Package '{pkg.package}' (order {pkg.build_order}) "
                    f"depends on '{dep}' (order {dep_pkg.build_order})"
                )

    return StructureTree(
        code=machine["fqdn_tree_code"],
        version=machine["version"],
        content_hash=content_hash,
        packages=packages,
        artifact_patterns=patterns,
        role_artifact_rules=role_rules,
    )
