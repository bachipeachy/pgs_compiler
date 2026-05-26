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
# pgs_workspace — clear data/ and traces/
# -----------------------------------------------

echo "[ pgs_workspace ] Clearing runtime state..."
echo ""

if [[ ! -d "$WS_ROOT" ]]; then
    echo "  WARNING: pgs_workspace not found at $WS_ROOT — skipping."
    echo ""
else
    if [[ -d "$WS_DATA" ]]; then
        rm -rf "$WS_DATA"
        echo "  Cleared: $WS_DATA"
    else
        echo "  Skip: data/ not found"
    fi

    if [[ -d "$WS_TRACES" ]]; then
        rm -rf "$WS_TRACES"
        echo "  Cleared: $WS_TRACES"
    else
        echo "  Skip: traces/ not found"
    fi

    # Restore read-only seed data — CS implementations auto-create their own dirs
    # on first workflow run, but seeds/ files are read-only input that must exist.
    if [[ -d "$WS_SEEDS" ]]; then
        mkdir -p "$WS_DATA/ai_governance/ai_licensing"
        cp "$WS_SEEDS/license_facts.json" "$WS_DATA/ai_governance/ai_licensing/license_facts.json"
        echo "  Restored: seeds/license_facts.json → data/ai_governance/ai_licensing/"
    else
        echo "  WARNING: seeds/ not found at $WS_SEEDS — ai_governance workflows will fail until seeded."
    fi
fi

echo ""
echo "============================================="
echo "Done. Workspace ready — run any workflow without bootstrapping."
echo ""
