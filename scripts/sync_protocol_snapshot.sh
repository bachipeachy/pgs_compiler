#!/usr/bin/env bash
set -euo pipefail

# ── Entry point guard ─────────────────────────────────────────
# This script is an internal step of the PGS build pipeline.
# It MUST NOT be invoked directly — it does not run conformance
# tests or write snapshot_status.json.
#
# Correct entry point:
#   python pgs_compiler/scripts/pgs_build.py --workspace /abs/path/to/pgs_workspace
if [[ "${PGS_INVOKED_BY_BUILD:-}" != "1" ]]; then
  echo ""
  echo "ERROR: sync_protocol_snapshot.sh must not be run directly."
  echo ""
  echo "  This script is an internal step of pgs_build.py."
  echo "  Running it directly skips conformance tests and"
  echo "  leaves the snapshot without a snapshot_status.json"
  echo "  validity marker."
  echo ""
  echo "  Use instead:"
  echo "    python pgs_build.py --workspace <output_dir>"
  echo ""
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."          # /Users/bp/pgs_compiler
BASE_DIR="$(cd "$ROOT/.." && pwd)"  # /Users/bp

# Governance compiled dir → snapshot/governance/artifacts/{type}/
GOVERNANCE_COMPILED="$BASE_DIR/pgs_governance/compiled"

# Domain compiled dirs → snapshot/artifacts/{type}/
DOMAIN_COMPILED=(
  "$BASE_DIR/pgs_capabilities/pgs_capabilities/compiled"
  "$BASE_DIR/pgs_capabilities/pgs_side_effects/compiled"
  "$BASE_DIR/pgs_capabilities/pgs_transforms/compiled"
  "$BASE_DIR/pgs_blockchain/pgs_blockchain/compiled"
  "$BASE_DIR/pgs_ai_governance/pgs_ai_governance/compiled"
)

DST_ROOT="${PGS_WORKSPACE:-$HOME/pgs_workspace}/protocol_snapshot"
ARTIFACTS_DST="$DST_ROOT/artifacts"
GOV_DST="$DST_ROOT/governance/artifacts"
CONFORMANCE_DST="$DST_ROOT/conformance"
VISUALIZATION_DST="$DST_ROOT/visualization"

# ── Clean and recreate destination ───────────────────────────
rm -rf "$ARTIFACTS_DST" "$GOV_DST" "$CONFORMANCE_DST" "$VISUALIZATION_DST"
mkdir -p "$ARTIFACTS_DST" "$GOV_DST" "$CONFORMANCE_DST" "$VISUALIZATION_DST"

# ── Helpers ──────────────────────────────────────────────────

# Copy artifacts/{type}/*.json preserving type subdir
copy_artifacts() {
  local src="$1/artifacts"
  local dst="$2"
  local count=0
  [ -d "$src" ] || { echo 0; return; }
  while IFS= read -r f; do
    rel="${f#$src/}"              # e.g. workflows/foo.json
    type_dir=$(dirname "$rel")
    mkdir -p "$dst/$type_dir"
    cp "$f" "$dst/$type_dir/"
    count=$((count + 1))
  done < <(find "$src" -type f -name "*.json")
  echo "$count"
}

# Copy conformance/*.json flat
copy_conformance() {
  local src="$1/conformance"
  local dst="$2"
  local count=0
  [ -d "$src" ] || { echo 0; return; }
  while IFS= read -r f; do
    cp "$f" "$dst/"
    count=$((count + 1))
  done < <(find "$src" -type f -name "*.json")
  echo "$count"
}

# Copy visualization preserving per-WF subdirs
copy_visualization() {
  local src="$1/visualization"
  local dst="$2"
  local count=0
  [ -d "$src" ] || { echo 0; return; }
  while IFS= read -r f; do
    rel="${f#$src/}"
    subdir=$(dirname "$rel")
    mkdir -p "$dst/$subdir"
    cp "$f" "$dst/$subdir/"
    count=$((count + 1))
  done < <(find "$src" -type f)
  echo "$count"
}

# ── Sync ─────────────────────────────────────────────────────
echo "==> Syncing MULTI-REPO snapshot"

total_artifacts=0
total_gov=0
total_conf=0
total_vis=0

# Governance (separate destination)
echo "==> governance: ../pgs_governance/compiled"
g=$(copy_artifacts "$GOVERNANCE_COMPILED" "$GOV_DST")
echo "   governance_artifacts=$g"
total_gov=$((total_gov + g))

# Domain repos
for compiled in "${DOMAIN_COMPILED[@]}"; do
  label="${compiled#$ROOT/../}"
  echo "==> $label"
  a=$(copy_artifacts   "$compiled" "$ARTIFACTS_DST")
  c=$(copy_conformance "$compiled" "$CONFORMANCE_DST")
  v=$(copy_visualization "$compiled" "$VISUALIZATION_DST")
  echo "   artifacts=$a  conformance=$c  visualization=$v"
  total_artifacts=$((total_artifacts + a))
  total_conf=$((total_conf + c))
  total_vis=$((total_vis + v))
done

total_all_artifacts=$((total_artifacts + total_gov))
echo "==> TOTAL"
echo "   artifacts=$total_all_artifacts  conformance=$total_conf  visualization=$total_vis"
