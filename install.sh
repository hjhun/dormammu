#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="${DORMAMMU_REPO:-hjhun/dormammu}"
DEFAULT_INSTALL_ROOT="${HOME}/.local/share/dormammu"
INSTALL_ROOT="${DORMAMMU_INSTALL_ROOT:-${DEFAULT_INSTALL_ROOT}}"
BIN_DIR="${DORMAMMU_BIN_DIR:-${HOME}/.local/bin}"
VENV_DIR="${INSTALL_ROOT}/venv"
PYTHON_BIN="${PYTHON:-python3}"
INSTALL_SOURCE="${DORMAMMU_INSTALL_SOURCE:-}"
INSTALL_REF="${DORMAMMU_INSTALL_REF:-}"
TMP_DIR=""

cleanup() {
  if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
}

trap cleanup EXIT

log() {
  printf '%s\n' "$*"
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    fail "${command_name} is required but was not found on PATH"
  fi
}

latest_release_source() {
  "${PYTHON_BIN}" - "${REPO_SLUG}" <<'PY'
from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

repo_slug = sys.argv[1]
request = Request(
    f"https://api.github.com/repos/{repo_slug}/releases/latest",
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "dormammu-install-script",
    },
)

try:
    with urlopen(request) as response:
        payload = json.load(response)
except (HTTPError, URLError):
    sys.exit(1)

tag_name = payload.get("tag_name")
tarball_url = payload.get("tarball_url")
if not tag_name or not tarball_url:
    sys.exit(1)

print(tag_name)
print(tarball_url)
PY
}

resolve_source() {
  if [[ -n "${INSTALL_SOURCE}" ]]; then
    printf 'custom\n%s\n' "${INSTALL_SOURCE}"
    return 0
  fi

  if [[ -n "${INSTALL_REF}" ]]; then
    printf '%s\n' "${INSTALL_REF}"
    printf 'https://github.com/%s/archive/%s.tar.gz\n' "${REPO_SLUG}" "${INSTALL_REF}"
    return 0
  fi

  if release_info="$(latest_release_source 2>/dev/null)"; then
    printf '%s\n' "${release_info}"
    return 0
  fi

  printf 'main\nhttps://github.com/%s/archive/refs/heads/main.tar.gz\n' "${REPO_SLUG}"
}

extract_archive() {
  local archive_path="$1"
  local destination_dir="$2"
  local top_level

  top_level="$(tar -tzf "${archive_path}" | head -n 1 | cut -d/ -f1)"
  tar -xzf "${archive_path}" -C "${destination_dir}"
  printf '%s/%s\n' "${destination_dir}" "${top_level}"
}

link_binary() {
  mkdir -p "${BIN_DIR}"
  ln -sf "${VENV_DIR}/bin/dormammu" "${BIN_DIR}/dormammu"
}

print_path_guidance() {
  case ":${PATH}:" in
    *":${BIN_DIR}:"*) return 0 ;;
  esac

  cat <<EOF

Add ${BIN_DIR} to your PATH if it is not already available in new shells:
  export PATH="${BIN_DIR}:\$PATH"
EOF
}

main() {
  require_command "${PYTHON_BIN}"
  require_command curl
  require_command tar

  mapfile -t source_info < <(resolve_source)
  local source_label="${source_info[0]}"
  local source_location="${source_info[1]}"

  mkdir -p "${INSTALL_ROOT}"
  if [[ ! -d "${VENV_DIR}" ]]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi

  "${VENV_DIR}/bin/python" -m pip install --upgrade pip

  if [[ -d "${source_location}" ]]; then
    log "Installing dormammu from local source directory: ${source_location}"
    "${VENV_DIR}/bin/pip" install --upgrade "${source_location}"
  else
    TMP_DIR="$(mktemp -d)"
    local archive_path="${TMP_DIR}/dormammu.tar.gz"
    log "Downloading dormammu (${source_label}) from ${source_location}"
    curl -fsSL "${source_location}" -o "${archive_path}"
    local source_dir
    source_dir="$(extract_archive "${archive_path}" "${TMP_DIR}")"
    "${VENV_DIR}/bin/pip" install --upgrade "${source_dir}"
  fi

  link_binary

  cat <<EOF
Installed dormammu into ${INSTALL_ROOT}

Next steps:
  ${BIN_DIR}/dormammu doctor --agent-cli /path/to/agent-cli
  ${BIN_DIR}/dormammu ui
EOF
  print_path_guidance
}

main "$@"
