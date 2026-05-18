"""Graphviz DOT rendering utilities."""

import subprocess
from pathlib import Path


def dot_to_png(dot_path: Path, png_path: Path) -> None:
    """Convert DOT file to PNG."""
    if not dot_path.exists():
        raise FileNotFoundError(f"DOT file not found: {dot_path}")

    png_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            ["dot", "-Tpng", str(dot_path), "-o", str(png_path)],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise RuntimeError("Graphviz 'dot' not found. Install: https://graphviz.org/download/")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Graphviz failed: {e.stderr.decode()}")


def dot_string_to_png(dot_content: str, png_path: Path) -> None:
    """Convert DOT string to PNG."""
    png_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            ["dot", "-Tpng", "-o", str(png_path)],
            input=dot_content.encode("utf-8"),
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise RuntimeError("Graphviz 'dot' not found. Install: https://graphviz.org/download/")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Graphviz failed: {e.stderr.decode()}")
