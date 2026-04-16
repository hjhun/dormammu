#!/usr/bin/env bash
# sync-agents.sh — Copy agents/ to backend/dormammu/assets/agents/
#
# Run this before every commit that modifies agents/.
# The packaged bundle must always mirror the source bundle.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO_ROOT/agents"
DST="$REPO_ROOT/backend/dormammu/assets/agents"

if [ ! -d "$SRC" ]; then
  echo "ERROR: source directory not found: $SRC" >&2
  exit 1
fi

rsync -a --delete "$SRC/" "$DST/"
echo "Synced $SRC → $DST"
