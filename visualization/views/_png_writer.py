"""
Internal PNG writer — shared graphviz rendering utility for evidence views.

INTERNAL: Not part of the public visualization.views API.
Do not import from outside visualization/views/.

Converts a DOT string → PNG file using the system `dot` (graphviz) command.
DOT source is piped via stdin — never written to disk.
Only the PNG output is persisted.

Mirrors the approach in wf_graph_generator._generate_png but:
  - operates on in-memory DOT string (no temp files)
  - returns bool (caller decides how to handle failure)
"""

import subprocess
from pathlib import Path


def write_png_from_dot(dot_src: str, output_path: Path) -> bool:
    """
    Render a DOT string to PNG using graphviz (dot command).

    DOT source is passed via stdin — never written to disk.
    The PNG is the only persisted artifact.

    Args:
        dot_src:      DOT source as a string.
        output_path:  Destination path for the PNG file.

    Returns:
        True if the PNG was successfully written.
        False if graphviz is unavailable or rendering failed.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["dot", "-Tpng", "-o", str(output_path)],
            input=dot_src.encode(),
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
