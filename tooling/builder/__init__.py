"""
builder — Structure tree loader and FQDN-driven package discovery utilities.

Compiler-adjacent: provides StructureTree for compiler and conformance generator.
"""

from pgs_compiler.tooling.builder.structure_tree import StructureTree, Package, PackageRoots, Registry, load

__all__ = ["StructureTree", "Package", "PackageRoots", "Registry", "load"]
