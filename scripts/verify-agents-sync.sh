#!/usr/bin/env bash
# verify-agents-sync.sh — Fail if agents/ and assets/agents/ have diverged.
#
# Exits 0 when the two directories are identical.
# Exits 1 and prints a diff summary when they differ.
#
# Use in CI or as a pre-commit check.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO_ROOT/agents"
DST="$REPO_ROOT/backend/dormammu/assets/agents"

if [ ! -d "$SRC" ]; then
  echo "ERROR: source directory not found: $SRC" >&2
  exit 1
fi

if [ ! -d "$DST" ]; then
  echo "ERROR: packaged directory not found: $DST" >&2
  exit 1
fi

DIFF=$(diff -rq "$SRC" "$DST" 2>&1 || true)

if [ -n "$DIFF" ]; then
  echo "FAIL: agents/ and backend/dormammu/assets/agents/ have diverged."
  echo ""
  echo "$DIFF"
  echo ""
  echo "Run scripts/sync-agents.sh to fix."
  exit 1
fi

echo "OK: agents/ and backend/dormammu/assets/agents/ are in sync."
