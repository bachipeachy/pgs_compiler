#!/usr/bin/env bash

# -------------------------------------------------------------
# PGS Federated Artifact Cleanup (ALL repos)
# Run from pgs_compiler repo
# -------------------------------------------------------------

set -euo pipefail

ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/.. && pwd )"
PARENT="$( dirname "$ROOT" )"

echo ""
echo "PGS Federated Artifact Cleanup"
echo "Root: $PARENT"
echo "---------------------------------------------"

# 🔥 Explicit repo list (NO guessing)
REPOS=(
  "pgs_governance"
  "pgs_capabilities"
  "pgs_blockchain"
  "pgs_ai_governance"
)

# Output trees written by the compiler into domain repos
OUTPUT_DIRS=(
  "compiled"
  "evidence"
  "vocabulary"
  "tokenized"
)

DIR_COUNT=0
FILE_COUNT=0
SIZE_TOTAL=0

for repo in "${REPOS[@]}"
do
    REPO_PATH="$PARENT/$repo"

    if [[ ! -d "$REPO_PATH" ]]; then
        echo "❌ Missing repo: $REPO_PATH"
        exit 1
    fi

    echo ""
    echo "Scanning: $repo"

    for DIR_NAME in "${OUTPUT_DIRS[@]}"
    do
        while IFS= read -r DIR
        do
            if [[ -d "$DIR" ]]; then

                FILES=$(find "$DIR" -type f | wc -l | xargs)
                SIZE=$(du -sk "$DIR" | awk '{print $1}')

                echo "  Removing: $DIR"
                echo "    files: $FILES"
                echo "    size:  ${SIZE} KB"

                FILE_COUNT=$((FILE_COUNT + FILES))
                SIZE_TOTAL=$((SIZE_TOTAL + SIZE))
                DIR_COUNT=$((DIR_COUNT + 1))

                rm -rf "$DIR"
            fi

        done < <(find "$REPO_PATH" \
                -type d \
                -name "$DIR_NAME" \
                -not -path "*/.git/*" \
                -not -path "*/.venv/*")
    done

done

echo ""
echo "---------------------------------------------"
echo "Cleanup Summary"
echo ""
echo "Compiled directories removed : $DIR_COUNT"
echo "Total files removed          : $FILE_COUNT"
echo "Total disk space reclaimed   : ${SIZE_TOTAL} KB"
echo ""
