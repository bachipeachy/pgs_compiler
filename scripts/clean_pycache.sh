#!/usr/bin/env bash

# -------------------------------------------------------------
# PGS Federated Cache Cleanup (ALL repos - deterministic)
# -------------------------------------------------------------

set -euo pipefail

ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/.. && pwd )"
PARENT="$( dirname "$ROOT" )"

echo ""
echo "=================================================="
echo "PGS Federated Cache Cleanup"
echo "Root: $PARENT"
echo "=================================================="
echo ""

# -------------------------------------------------------------
# Discover all repos with pgs_* prefix (no hardcoding)
# -------------------------------------------------------------
REPOS=()
while IFS= read -r dir; do
    REPOS+=("$dir")
done < <(find "$PARENT" -maxdepth 1 -type d -name "pgs_*" -not -path "*/.git/*")

if [[ ${#REPOS[@]} -eq 0 ]]; then
    echo "❌ No pgs_* repos found under $PARENT"
    exit 1
fi

# -------------------------------------------------------------
# Targets
# -------------------------------------------------------------
DIRS=(
  "__pycache__"
  ".pytest_cache"
  ".mypy_cache"
  ".ruff_cache"
  "build"
  "dist"
  ".eggs"
)

FILES=(
  "*.pyc"
  "*.pyo"
)

DIR_COUNT=0
FILE_COUNT=0

# -------------------------------------------------------------
# MAIN LOOP
# -------------------------------------------------------------
for REPO_PATH in "${REPOS[@]}"
do
    echo "→ Cleaning: $(basename "$REPO_PATH")"

    # ---- Remove directories ----
    for DIR in "${DIRS[@]}"
    do
        while IFS= read -r TARGET
        do
            rm -rf "$TARGET"
            DIR_COUNT=$((DIR_COUNT + 1))
        done < <(find "$REPO_PATH" \
                -type d \
                -name "$DIR" \
                -not -path "*/.git/*" \
                -not -path "*/.venv/*")
    done

    # ---- Remove files ----
    for FILE in "${FILES[@]}"
    do
        while IFS= read -r TARGET
        do
            rm -f "$TARGET"
            FILE_COUNT=$((FILE_COUNT + 1))
        done < <(find "$REPO_PATH" \
                -type f \
                -name "$FILE" \
                -not -path "*/.git/*" \
                -not -path "*/.venv/*")
    done

    # ---- Egg-info ----
    while IFS= read -r TARGET
    do
        rm -rf "$TARGET"
        DIR_COUNT=$((DIR_COUNT + 1))
    done < <(find "$REPO_PATH" \
            -type d \
            -name "*.egg-info" \
            -not -path "*/.git/*")

done

echo ""
echo "=================================================="
echo "Cleanup Summary"
echo ""
echo "Repositories scanned : ${#REPOS[@]}"
echo "Directories removed  : $DIR_COUNT"
echo "Files removed        : $FILE_COUNT"
echo ""
