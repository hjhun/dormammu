#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "error: ${PYTHON_BIN} is not available on PATH" >&2
  exit 2
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/pip" install -e "${ROOT_DIR}"

cat <<EOF
Installed dormammu into ${VENV_DIR}.

Next steps:
  ${VENV_DIR}/bin/dormammu doctor --repo-root "${ROOT_DIR}" --agent-cli /path/to/agent-cli
  ${VENV_DIR}/bin/dormammu init-state --repo-root "${ROOT_DIR}"
  ${VENV_DIR}/bin/dormammu run --repo-root "${ROOT_DIR}" --prompt "Inspect the repo and implement the requested change."
EOF
