"""
wf_graph_generator.py — Workflow Graph Generation

Generates first-class graph artifacts from compiled workflows:
- JSON: Machine-readable execution graph
- PNG: Visual diagram (if graphviz available)
- Markdown: Human-readable summary

Governed by: STRUCTURE_BUILD_PLATFORM_CONFIG_V0

This is NOT debug-only output - graphs are first-class compiled artifacts
used for:
- Runtime trace correlation
- Workflow debugging
- Documentation generation
- IDE integration

**COMPILER-OWNED**: Self-sufficient graph construction, no external dependencies.
This is COMPILE-TIME graph generation (static WF structure).
Runtime trace visualization is separate (lives in pgs_tooling/visualization).
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class WorkflowGraphGenerator:
    """
    Generates execution graph artifacts from compiled workflows.

    Responsibilities:
    - Extract execution graph from WF node structure
    - Generate JSON graph artifact
    - Generate PNG visualization (if graphviz available)
    - Generate Markdown summary
    - Store in compiled/artifacts/workflow_graphs/
    """

    def __init__(self, output_root: Path):
        """
        Initialize graph generator.

        Args:
            output_root: Root directory for graph artifacts
                        (e.g., .../compiled/artifacts/workflow_graphs/)
        """
        self.output_root = output_root

    def generate(self, wf_artifact: Dict[str, Any], cc_artifacts: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate compile-time graph artifacts for a workflow.

        Persisted artifacts (two only):
        - {wf_code}.graph.json      — machine-readable DAG, CC nodes carry projection data
        - {wf_code}.projection.png  — visual DAG with CT/CS leaf nodes (best-effort)

        All other views (wf_only PNG, markdown) are derivable on demand from the JSON.

        Args:
            wf_artifact: Compiled workflow artifact
            cc_artifacts: Map of CC code → compiled CC artifact (for capability lookup)

        Returns:
            {
                "wf_code": str,
                "json_path": Path | None,
                "projection_png_path": Path | None,
                "status": "SUCCESS" | "PARTIAL" | "FAILED",
                "errors": list[str]
            }
        """
        errors = []

        # Extract WF code
        wf_code = wf_artifact.get("frontmatter", {}).get("wf_code")
        if not wf_code:
            return {
                "wf_code": "UNKNOWN",
                "status": "FAILED",
                "errors": ["Missing wf_code in frontmatter"]
            }

        # Build graph model (CC nodes carry projection data)
        try:
            graph = self._build_graph_model(wf_artifact, cc_artifacts)
        except Exception as e:
            return {
                "wf_code": wf_code,
                "status": "FAILED",
                "errors": [f"Failed to build graph model: {e}"]
            }

        # Create output directory
        wf_dir = self.output_root / wf_code
        wf_dir.mkdir(parents=True, exist_ok=True)

        # Artifact 1: JSON with projection data embedded in CC nodes
        json_path = wf_dir / f"{wf_code}.graph.json"
        try:
            self._generate_json(graph, json_path)
        except Exception as e:
            errors.append(f"Failed to generate JSON: {e}")

        # Artifact 2: projection PNG (best-effort)
        projection_png_path = None
        try:
            projection_png_path = self._generate_png(
                graph, wf_dir / f"{wf_code}.projection.png", dag_view="wf_cc_projection"
            )
        except Exception as e:
            errors.append(f"Projection PNG generation skipped: {e}")

        # Determine status
        if errors:
            status = "PARTIAL" if json_path.exists() else "FAILED"
        else:
            status = "SUCCESS"

        return {
            "wf_code": wf_code,
            "json_path": json_path if json_path.exists() else None,
            "projection_png_path": projection_png_path,
            "status": status,
            "errors": errors
        }

    def _build_graph_model(self, wf_artifact: Dict[str, Any], cc_artifacts: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build graph model from WF node structure.

        COMPILER-OWNED: Direct graph construction from WF nodes specification.

        Args:
            wf_artifact: Compiled workflow artifact
            cc_artifacts: Map of CC code → CC artifact

        Returns:
            {
                "wf_id": str,
                "entry": str,
                "nodes": list[dict],
                "edges": list[dict],
                "execution_paths": list[list[str]]
            }
        """
        frontmatter = wf_artifact.get("frontmatter", {})
        wf_code = frontmatter.get("wf_code")

        return self._build_graph(wf_artifact, cc_artifacts, wf_code)

    def _build_graph(self, wf_artifact: Dict[str, Any],
                     cc_artifacts: Dict[str, Any],
                     wf_code: str) -> Dict[str, Any]:
        """
        Build execution graph from WF node structure.

        Extracts nodes, edges, and execution paths from WF specification.
        Enriches CC nodes with capability binding information.

        Args:
            wf_artifact: Compiled workflow artifact
            cc_artifacts: Map of CC code → CC artifact
            wf_code: Workflow code

        Returns:
            Graph model dict
        """
        frontmatter = wf_artifact.get("frontmatter", {})
        core = frontmatter.get("core", {})

        start_node = core.get("start_node")
        nodes_spec = core.get("nodes", {})

        # Build node list with capability bindings
        nodes = []
        for node_id, node_spec in nodes_spec.items():
            node_type = node_spec.get("type")

            node = {
                "id": node_id,
                "type": node_type
            }

            # For CC nodes, resolve capability binding and projection
            if node_type == "CC":
                cc_code = node_spec.get("code")
                if cc_code:
                    node["cc_code"] = cc_code

                    # Look up CC artifact to find capability binding
                    cc_artifact = cc_artifacts.get(cc_code, {})
                    cc_frontmatter = cc_artifact.get("frontmatter", {})
                    cc_core = cc_frontmatter.get("core", {})
                    pipeline = cc_core.get("pipeline", [])

                    # Extract first capability binding (for node label)
                    if pipeline and len(pipeline) > 0:
                        first_step = pipeline[0]
                        capability_fqdn = first_step.get("transform") or first_step.get("side_effect")
                        if capability_fqdn:
                            node["capability"] = capability_fqdn
                            # Determine type
                            if "::CT_" in capability_fqdn or capability_fqdn.startswith("CT_"):
                                node["capability_type"] = "CT"
                            elif "::CS_" in capability_fqdn or capability_fqdn.startswith("CS_"):
                                node["capability_type"] = "CS"

                    # Attach full CT/CS projection (compile-time extracted in materialize phase)
                    cc_projection = cc_artifact.get("cc_projection")
                    if cc_projection:
                        node["projection"] = cc_projection

                # Attach WF-level input bindings — surfaces data-flow into this node
                # alongside routing edges, making binding bugs visible without opening CC artifacts.
                # Bindings are normalized to structural references (IN.*, NODE.*) — raw DSL
                # syntax ($.payload, $.results) is authoring-layer detail, not graph-layer truth.
                wf_inputs = node_spec.get("inputs")
                if wf_inputs:
                    node["input_bindings"] = {
                        "type": "wf_boundary",
                        "bindings": {k: self._normalize_binding(v) for k, v in wf_inputs.items()},
                    }

            nodes.append(node)

        # Build edge list from node transitions
        edges = []
        for node_id, node_spec in nodes_spec.items():
            next_transitions = node_spec.get("next", {})
            for condition, target_id in next_transitions.items():
                edges.append({
                    "from": node_id,
                    "to": target_id,
                    "condition": condition
                })

        # Extract all execution paths (DFS from start_node)
        paths = self._extract_paths(start_node, nodes_spec)

        return {
            "wf_id": wf_code,
            "entry": start_node,
            "nodes": nodes,
            "edges": edges,
            "execution_paths": paths
        }

    @staticmethod
    def _normalize_binding(value: Any) -> str:
        """
        Normalize a raw WF DSL binding expression to a structural reference.

        Rules (authoring DSL → graph layer):
          $.payload.<field>              → IN.<field>
          $.results.<NODE>.<field>       → <NODE>.<field>
          <literal>  (no $ prefix)       → unchanged (constant)

        The graph layer must not expose DSL syntax — only structural lineage.
        """
        if not isinstance(value, str):
            return value  # Non-string constants (booleans, ints) pass through
        if value.startswith("$.payload."):
            return "IN." + value[len("$.payload."):]
        if value.startswith("$.results."):
            return value[len("$.results."):]
        # Literal constant (e.g. "UNAUTHORIZED_TOOL", "AREQ") — no transformation
        return value

    def _extract_paths(self, start_node: str, nodes_spec: Dict[str, Any]) -> List[List[str]]:
        """
        Extract all execution paths from start_node to EXIT nodes.

        Args:
            start_node: Entry node ID
            nodes_spec: WF nodes specification

        Returns:
            List of paths (each path is list of node IDs)
        """
        paths = []
        visited = set()

        def dfs(node_id: str, path: List[str]):
            # Detect cycles
            if node_id in visited:
                return

            visited.add(node_id)
            path = path + [node_id]

            node_spec = nodes_spec.get(node_id, {})
            node_type = node_spec.get("type")

            # Terminal node
            if node_type == "EXIT" or not node_spec.get("next"):
                paths.append(path)
                visited.remove(node_id)
                return

            # Traverse next nodes
            next_transitions = node_spec.get("next", {})
            for condition, target_id in next_transitions.items():
                dfs(target_id, path)

            visited.remove(node_id)

        dfs(start_node, [])
        return paths

    def _generate_json(self, graph: Dict[str, Any], output_path: Path):
        """
        Generate JSON graph artifact.

        Args:
            graph: Graph model
            output_path: Output file path
        """
        with open(output_path, "w") as f:
            json.dump(graph, f, indent=2)

    def _generate_png(self, graph: Dict[str, Any], output_path: Path, dag_view: str = "wf_only") -> Optional[Path]:
        """
        Generate PNG visualization using graphviz.

        Args:
            graph: Graph model
            output_path: Output file path
            dag_view: "wf_only" or "wf_cc_projection"

        Returns:
            Path to PNG file if successful, None otherwise
        """
        # Check if graphviz is available
        try:
            subprocess.run(["dot", "-V"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("Graphviz not available (PNG generation skipped)")

        # Generate DOT file
        dot_content = self._generate_dot(graph, dag_view=dag_view)
        dot_path = output_path.with_suffix(".dot")

        with open(dot_path, "w") as f:
            f.write(dot_content)

        # Render to PNG
        try:
            subprocess.run(
                ["dot", "-Tpng", str(dot_path), "-o", str(output_path)],
                check=True,
                capture_output=True
            )
            dot_path.unlink()  # Clean up DOT file
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Graphviz rendering failed: {e.stderr.decode()}")

    def _generate_dot(self, graph: Dict[str, Any], dag_view: str = "wf_only") -> str:
        """
        Generate Graphviz DOT format from graph model.

        Args:
            graph: Graph model
            dag_view: "wf_only" or "wf_cc_projection"

        Returns:
            DOT format string
        """
        lines = [
            f'digraph "{graph["wf_id"]}" {{',
            '  rankdir=LR;',
            '  node [fontname="Arial"];',
            ''
        ]

        # Define WF nodes
        for node in graph["nodes"]:
            node_id = node["id"]
            node_type = node["type"]

            # Style by type
            if node_type == "IN":
                shape = "ellipse"
                color = "lightblue"
            elif node_type == "CC":
                shape = "box"
                color = "lightgreen"
            elif node_type == "EXIT":
                shape = "ellipse"
                color = "lightcoral"
            else:
                shape = "box"
                color = "white"

            # Add capability label for CC nodes
            label = node_id
            if node_type == "CC" and "capability" in node:
                cap_type = node.get("capability_type", "?")
                label = f"{node_id}\\n({cap_type})"

            lines.append(f'  "{node_id}" [label="{label}", shape={shape}, style=filled, fillcolor={color}];')

        lines.append('')

        # In projection mode: add CT/CS leaf nodes under each CC
        # Each node shows: declared inputs/outputs (signatures) + binding overlay
        # Granularity = CT/CS artifact boundary, never internal atom steps
        if dag_view == "wf_cc_projection":
            for node in graph["nodes"]:
                if node["type"] != "CC":
                    continue
                projection = node.get("projection", {})
                cc_id = node["id"]

                for step in projection.get("steps", []):
                    kind = step["kind"]
                    code = step["id"]
                    # Unique DOT node id (collision-safe across multiple CCs)
                    dot_id = f"{cc_id}__{kind}__{code}"

                    # PNG = minimal cognition: name + kind tag only
                    # Full signatures and bindings live in graph.json
                    color = "lightyellow" if kind == "CT" else "lightcyan"
                    label = f"{code}\\n({kind})"

                    lines.append(
                        f'  "{dot_id}" [label="{label}", shape=box, style="filled,dashed",'
                        f' fillcolor={color}, fontsize=8];'
                    )
                    lines.append(f'  "{cc_id}" -> "{dot_id}" [style=dotted, arrowhead=open];')

            lines.append('')

        # Define WF edges
        for edge in graph["edges"]:
            from_id = edge["from"]
            to_id = edge["to"]
            condition = edge["condition"]

            lines.append(f'  "{from_id}" -> "{to_id}" [label="{condition}"];')

        lines.append('}')

        return '\n'.join(lines)

    def _generate_markdown(self, graph: Dict[str, Any], output_path: Path, dag_view: str = "wf_only"):
        """
        Generate Markdown summary of execution graph.

        Args:
            graph: Graph model
            output_path: Output file path
            dag_view: "wf_only" or "wf_cc_projection"
        """
        view_label = "CC Projection View" if dag_view == "wf_cc_projection" else "Execution Graph"
        lines = [
            f"# {graph['wf_id']} {view_label}",
            "",
            f"**Entry**: {graph['entry']}",
            "",
            "## Nodes",
            ""
        ]

        # List nodes
        for node in graph["nodes"]:
            node_id = node["id"]
            node_type = node["type"]

            line = f"- `{node_id}` ({node_type})"

            if node_type == "CC" and "capability" in node:
                capability = node["capability"]
                cap_type = node.get("capability_type", "?")
                line += f" → {capability} ({cap_type})"

            lines.append(line)

            # In projection mode: show CT/CS with signatures and bindings under each CC
            if dag_view == "wf_cc_projection" and node_type == "CC":
                projection = node.get("projection", {})
                for step in projection.get("steps", []):
                    kind = step["kind"]
                    code = step["id"]
                    if kind == "CT":
                        inputs = step.get("inputs", [])
                        outputs = step.get("outputs", [])
                        bindings = step.get("bindings", {})
                        in_str = ", ".join(inputs) + (" ..." if step.get("inputs_truncated") else "")
                        out_str = ", ".join(outputs) + (" ..." if step.get("outputs_truncated") else "")
                        lines.append(f"    - `{code}` (CT)")
                        if in_str:
                            lines.append(f"      - in:  {in_str}")
                        if out_str:
                            lines.append(f"      - out: {out_str}")
                        for k, v in bindings.items():
                            lines.append(f"      - {k} <- {v}")
                    else:  # CS
                        ops = step.get("ops", [])
                        ops_str = ", ".join(ops) + (" ..." if step.get("ops_truncated") else "")
                        lines.append(f"    - `{code}` (CS)")
                        if ops_str:
                            lines.append(f"      - ops: {ops_str}")

        lines.extend(["", "## Execution Paths", ""])

        # List paths
        for idx, path in enumerate(graph["execution_paths"], 1):
            path_str = " → ".join(path)
            lines.append(f"{idx}. {path_str}")

        lines.append("")

        with open(output_path, "w") as f:
            f.write('\n'.join(lines))


def generate_workflow_graph(wf_artifact: Dict[str, Any],
                           cc_artifacts: Dict[str, Any],
                           output_root: Path) -> Dict[str, Any]:
    """
    Generate workflow graph artifacts.

    Args:
        wf_artifact: Compiled workflow artifact
        cc_artifacts: Map of CC code → CC artifact
        output_root: Root directory for graph artifacts

    Returns:
        Generation result dict
    """
    generator = WorkflowGraphGenerator(output_root)
    return generator.generate(wf_artifact, cc_artifacts)
