#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_DIR="$(cd "$REPO_ROOT/.." && pwd)"

WS_ROOT="$BASE_DIR/pgs_workspace"
WS_DATA="$WS_ROOT/data"
WS_TRACES="$WS_ROOT/traces"
WS_SEEDS="$WS_ROOT/seeds"

echo ""
echo "PGS Cleanup"
echo "============================================="
echo ""

# -----------------------------------------------
# 1. pgs_compiler — remove all outputs/ directories
# -----------------------------------------------

echo "[ pgs_compiler ] Scanning for outputs/ directories..."
echo ""

DIR_COUNT=0
FILE_COUNT=0
SIZE_TOTAL=0

while IFS= read -r TARGET; do
    if [[ -d "$TARGET" ]]; then
        FILES=$(find "$TARGET" -type f | wc -l | xargs)
        SIZE=$(du -sk "$TARGET" | awk '{print $1}')

        echo "  Removing: $TARGET"
        echo "    files: $FILES"
        echo "    size:  ${SIZE} KB"
        echo ""

        FILE_COUNT=$((FILE_COUNT + FILES))
        SIZE_TOTAL=$((SIZE_TOTAL + SIZE))
        DIR_COUNT=$((DIR_COUNT + 1))

        rm -rf "$TARGET"
    fi
done < <(find "$REPO_ROOT" -type d -name "outputs")

if [[ $DIR_COUNT -eq 0 ]]; then
    echo "  No outputs/ directories found."
    echo ""
fi

echo "  outputs/ removed : $DIR_COUNT  |  files: $FILE_COUNT  |  reclaimed: ${SIZE_TOTAL} KB"
echo ""

# -----------------------------------------------
# 2. pgs_workspace — clear data/ and traces/
# -----------------------------------------------

echo "[ pgs_workspace ] Clearing runtime state..."
echo ""

if [[ ! -d "$WS_ROOT" ]]; then
    echo "  WARNING: pgs_workspace not found at $WS_ROOT — skipping."
    echo ""
else
    # Guard: seeds/ must exist before touching data/
    if [[ ! -d "$WS_SEEDS" ]]; then
        echo "  ERROR: seeds/ directory missing: $WS_SEEDS" >&2
        echo "  Aborting workspace cleanup — data/ left untouched." >&2
        exit 1
    fi

    # Clear data subdirectories
    for dir in "$WS_DATA/events" "$WS_DATA/registry" "$WS_DATA/state"; do
        if [[ -d "$dir" ]]; then
            rm -f "$dir"/*
            echo "  Cleared: $dir/"
        fi
    done

    # Remove all stray files directly in data/
    find "$WS_DATA" -maxdepth 1 -type f -delete

    # Clear traces
    if [[ -d "$WS_TRACES" ]]; then
        rm -rf "$WS_TRACES"/*/
        echo "  Cleared: $WS_TRACES/"
    fi

    # Restore seed data so workspace is immediately ready
    cp "$WS_SEEDS/license_facts.json" "$WS_DATA/license_facts.json"
    echo "  Restored: seeds/license_facts.json → data/"
fi

echo ""
echo "============================================="
echo "Done."
echo ""
