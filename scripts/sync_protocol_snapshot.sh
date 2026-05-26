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

# Copy canonical/{type}/*.json preserving type subdir
copy_artifacts() {
  local src="$1/canonical"
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

# ── Vocabulary (per-structure address space projections) ─────
VOCAB_DST="${PGS_WORKSPACE:-$HOME/pgs_workspace}/vocabulary_snapshot"
rm -rf "$VOCAB_DST"
mkdir -p "$VOCAB_DST"

total_vocab=0

# Platform vocabulary (governance repo)
PLATFORM_VOCAB="$BASE_DIR/pgs_governance/compiled/vocabulary/platform"
if [ -d "$PLATFORM_VOCAB" ]; then
  cp -r "$PLATFORM_VOCAB" "$VOCAB_DST/platform"
  total_vocab=$((total_vocab + 1))
fi

# Domain vocabularies (domain repos — now under compiled/vocabulary/)
for compiled in "${DOMAIN_COMPILED[@]}"; do
  for vocab_dir in "$compiled/vocabulary"/*; do
    [ -d "$vocab_dir" ] || continue
    structure_scope=$(basename "$vocab_dir")
    cp -r "$vocab_dir" "$VOCAB_DST/$structure_scope"
    total_vocab=$((total_vocab + 1))
  done
done

echo "==> vocabulary: $total_vocab structures synced to vocabulary_snapshot/"

# ── Tokenized topology (per-structure machine-oriented projections) ──
TOK_DST="${PGS_WORKSPACE:-$HOME/pgs_workspace}/tokenized_snapshot"
rm -rf "$TOK_DST"
mkdir -p "$TOK_DST"

total_tokenized=0

# Platform tokenized (governance repo)
PLATFORM_TOK="$BASE_DIR/pgs_governance/compiled/tokenized/platform"
if [ -d "$PLATFORM_TOK" ]; then
  cp -r "$PLATFORM_TOK" "$TOK_DST/platform"
  total_tokenized=$((total_tokenized + 1))
fi

# Domain tokenized (domain repos — now under compiled/tokenized/)
for compiled in "${DOMAIN_COMPILED[@]}"; do
  for tok_dir in "$compiled/tokenized"/*; do
    [ -d "$tok_dir" ] || continue
    structure_scope=$(basename "$tok_dir")
    cp -r "$tok_dir" "$TOK_DST/$structure_scope"
    total_tokenized=$((total_tokenized + 1))
  done
done

echo "==> tokenized: $total_tokenized structures synced to tokenized_snapshot/"

# ── Evidence (per-structure dual-form execution topology) ──
EVI_DST="${PGS_WORKSPACE:-$HOME/pgs_workspace}/evidence_snapshot"
rm -rf "$EVI_DST"
mkdir -p "$EVI_DST"

total_evidence=0

# Platform evidence (governance repo)
PLATFORM_EVI="$BASE_DIR/pgs_governance/compiled/evidence/platform"
if [ -d "$PLATFORM_EVI" ]; then
  cp -r "$PLATFORM_EVI" "$EVI_DST/platform"
  total_evidence=$((total_evidence + 1))
fi

# Domain evidence (domain repos — now under compiled/evidence/)
for compiled in "${DOMAIN_COMPILED[@]}"; do
  for evi_dir in "$compiled/evidence"/*; do
    [ -d "$evi_dir" ] || continue
    structure_scope=$(basename "$evi_dir")
    cp -r "$evi_dir" "$EVI_DST/$structure_scope"
    total_evidence=$((total_evidence + 1))
  done
done

echo "==> evidence: $total_evidence structures synced to evidence_snapshot/"

# ── Trust attestations (per-structure cryptographic binding) ────
TRUST_DST="${PGS_WORKSPACE:-$HOME/pgs_workspace}/trust_snapshot"
rm -rf "$TRUST_DST"
mkdir -p "$TRUST_DST"

total_trust=0

# Platform trust (governance repo)
PLATFORM_TRUST="$BASE_DIR/pgs_governance/compiled/trust/platform"
if [ -d "$PLATFORM_TRUST" ]; then
  cp -r "$PLATFORM_TRUST" "$TRUST_DST/platform"
  total_trust=$((total_trust + 1))
fi

# Domain trust (domain repos — now under compiled/trust/)
for compiled in "${DOMAIN_COMPILED[@]}"; do
  for trust_dir in "$compiled/trust"/*; do
    [ -d "$trust_dir" ] || continue
    structure_scope=$(basename "$trust_dir")
    cp -r "$trust_dir" "$TRUST_DST/$structure_scope"
    total_trust=$((total_trust + 1))
  done
done

echo "==> trust: $total_trust structures synced to trust_snapshot/"
