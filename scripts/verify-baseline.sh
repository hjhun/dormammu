#!/usr/bin/env bash
# verify-baseline.sh - Run the remediation-roadmap baseline checks.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-quick}"
PYTEST_BIN="${PYTEST_BIN:-pytest}"

usage() {
  cat <<'EOF'
Usage: scripts/verify-baseline.sh [quick|full]

Modes:
  quick  Run guidance sync plus the fast Phase 0 regression baseline.
  full   Run quick checks, then the full pytest suite.

Environment:
  PYTEST_BIN  pytest executable to use; defaults to "pytest".
EOF
}

run_step() {
  local label="$1"
  shift
  local start end elapsed
  start="$(date +%s)"
  echo "==> ${label}"
  "$@"
  end="$(date +%s)"
  elapsed="$((end - start))"
  echo "==> ${label} completed in ${elapsed}s"
}

case "${MODE}" in
  quick|full)
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

cd "${ROOT_DIR}"

run_step "agents bundle sync" scripts/verify-agents-sync.sh
run_step "phase 0 quick regression baseline" \
  "${PYTEST_BIN}" -q tests/test_packaging_sync.py tests/test_results.py tests/test_supervisor.py

if [[ "${MODE}" == "full" ]]; then
  run_step "full pytest suite" "${PYTEST_BIN}" -q
fi
