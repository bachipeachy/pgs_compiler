#!/usr/bin/env python3

import os
import re
import sys

# -------------------------------------------------------------
# PGS Declarative vs Imperative Analyzer (Grouped)
# -------------------------------------------------------------

REPO_PATHS = {
    "pgs_governance": "pgs_governance",
    "pgs_compiler": "pgs_compiler",
    "pgs_transport": "pgs_transport",
    "pgs_capabilities": "pgs_capabilities",
    "pgs_blockchain": "pgs_blockchain",
    "pgs_ai_governance": "pgs_ai_governance",
}

# 🔥 GROUP CLASSIFICATION (THIS IS THE KEY UPGRADE)
GROUPS = {
    "INFRASTRUCTURE": [
        "pgs_governance",    # constitutional governance + structure
        "pgs_compiler",      # compiler pipeline + tooling
        "pgs_transport",     # ingress/egress adapters
    ],
    "CAPABILITIES": [
        "pgs_capabilities"
    ],
    "DOMAINS": [
        "pgs_blockchain",
        "pgs_ai_governance"
    ]
}

YAML_PATTERN = re.compile(
    r'##\s*Machine.*?```yaml\s*\n(.*?)\n```',
    re.DOTALL | re.IGNORECASE
)


# -------------------------------------------------------------
# YAML COUNT
# -------------------------------------------------------------
def count_yaml_lines(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        matches = YAML_PATTERN.findall(content)

        total = 0
        for block in matches:
            lines = [l for l in block.splitlines() if l.strip()]
            total += len(lines)

        return total

    except Exception as e:
        raise RuntimeError(f"YAML read failed: {file_path}: {e}")


# -------------------------------------------------------------
# PY COUNT
# -------------------------------------------------------------
def count_py_lines(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception as e:
        raise RuntimeError(f"PY read failed: {file_path}: {e}")


# -------------------------------------------------------------
# SCAN REPO
# -------------------------------------------------------------
def scan_repo(repo_path):
    yaml_lines = 0
    py_lines = 0

    for root, dirs, files in os.walk(repo_path):

        dirs[:] = [
            d for d in dirs
            if not d.startswith(".")
            and d not in ("__pycache__", "compiled", ".venv")
        ]

        for file in files:
            full = os.path.join(root, file)

            if file.endswith(".md"):
                yaml_lines += count_yaml_lines(full)

            elif file.endswith(".py"):
                py_lines += count_py_lines(full)

    return yaml_lines, py_lines


# -------------------------------------------------------------
# MAIN
# -------------------------------------------------------------
def main():
    cwd = os.getcwd()
    parent = os.path.dirname(cwd)

    print("\nPGS Declarative vs Imperative Analysis (Grouped)")
    print(f"Root: {parent}")
    print("=" * 90)

    repo_results = {}
    total_yaml = 0
    total_py = 0

    # ---- Scan repos ----
    for repo, rel_path in REPO_PATHS.items():
        repo_path = os.path.join(parent, rel_path)

        if not os.path.exists(repo_path):
            print(f"❌ Missing repo: {repo_path}")
            sys.exit(1)

        yaml_lines, py_lines = scan_repo(repo_path)

        repo_results[repo] = (yaml_lines, py_lines)

        total_yaml += yaml_lines
        total_py += py_lines

    # ---------------------------------------------------------
    # PER-REPO
    # ---------------------------------------------------------
    print("\n📊 Per-Repo Breakdown")
    print("-" * 90)
    print(f"{'Repo':<22} {'YAML':>10} {'PY':>10} {'YAML/PY':>12}")

    for repo, (y, p) in repo_results.items():
        ratio = (y / p) if p > 0 else 0
        print(f"{repo:<22} {y:>10} {p:>10} {ratio:>12.2f}")

    # ---------------------------------------------------------
    # GROUPED ANALYSIS
    # ---------------------------------------------------------
    print("\n" + "=" * 90)
    print("📦 Grouped Analysis")
    print("-" * 90)
    print(f"{'Group':<20} {'YAML':>10} {'PY':>10} {'YAML/PY':>12}")

    group_results = {}

    for group, repos in GROUPS.items():
        g_yaml = sum(repo_results[r][0] for r in repos)
        g_py = sum(repo_results[r][1] for r in repos)

        ratio = (g_yaml / g_py) if g_py > 0 else 0

        group_results[group] = (g_yaml, g_py, ratio)

        print(f"{group:<20} {g_yaml:>10} {g_py:>10} {ratio:>12.2f}")

    # ---------------------------------------------------------
    # GLOBAL
    # ---------------------------------------------------------
    print("\n" + "=" * 90)

    total_ratio = (total_yaml / total_py) if total_py > 0 else 0

    print("📈 GLOBAL TOTALS")
    print(f"YAML lines : {total_yaml}")
    print(f"PY lines   : {total_py}")
    print(f"Ratio      : {total_ratio:.2f}")

    # ---------------------------------------------------------
    # INTERPRETATION (CORRECTED)
    # ---------------------------------------------------------
    print("\n🧠 Interpretation")

    infra_ratio = group_results["INFRASTRUCTURE"][2]
    domain_ratio = group_results["DOMAINS"][2]

    print(f"\nINFRASTRUCTURE ratio: {infra_ratio:.2f}")
    print("  (Expected: low — engine is imperative)")

    print(f"\nDOMAINS ratio: {domain_ratio:.2f}")
    if domain_ratio > 3:
        print("  🔥 Excellent — domains are declarative-dominant")
    elif domain_ratio > 1:
        print("  ✅ Healthy — mostly declarative")
    else:
        print("  ⚠️ Warning — domain logic leaking into code")

    print("\n📌 Key Insight:")
    print("Infrastructure PY is fixed cost; domain YAML should dominate growth")

    print("\n📌 What matters:")
    print("ΔYAML (domains) >> ΔPY over time")

    print("")


# -------------------------------------------------------------
if __name__ == "__main__":
    main()
