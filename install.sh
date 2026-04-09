#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="${DORMAMMU_REPO:-hjhun/dormammu}"
DEFAULT_DORMAMMU_HOME="${HOME}/.dormammu"
DEFAULT_INSTALL_ROOT="${DEFAULT_DORMAMMU_HOME}"
INSTALL_ROOT="${DORMAMMU_INSTALL_ROOT:-${DEFAULT_INSTALL_ROOT}}"
BIN_DIR="${DORMAMMU_BIN_DIR:-${DEFAULT_DORMAMMU_HOME}/bin}"
CONFIG_PATH="${DORMAMMU_CONFIG_PATH:-${DEFAULT_DORMAMMU_HOME}/config}"
BASHRC_PATH="${DORMAMMU_BASHRC_PATH:-${HOME}/.bashrc}"
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

resolve_cli_path() {
  local cli_name="$1"
  local whereis_output token

  whereis_output="$(whereis -b "${cli_name}" 2>/dev/null || true)"
  for token in ${whereis_output}; do
    if [[ "${token}" == *"/${cli_name}" && -x "${token}" ]]; then
      printf '%s\n' "${token}"
      return 0
    fi
  done

  if command -v "${cli_name}" >/dev/null 2>&1; then
    command -v "${cli_name}"
    return 0
  fi
  return 1
}

detect_active_agent_cli() {
  local explicit_cli="${DORMAMMU_ACTIVE_AGENT_CLI:-}"
  local resolved

  if [[ -n "${explicit_cli}" ]]; then
    if [[ -x "${explicit_cli}" ]]; then
      printf '%s\n' "${explicit_cli}"
      return 0
    fi
    if resolved="$(resolve_cli_path "${explicit_cli}")"; then
      printf '%s\n' "${resolved}"
      return 0
    fi
  fi

  local cli_name
  for cli_name in codex claude gemini cline; do
    if resolved="$(resolve_cli_path "${cli_name}")"; then
      printf '%s\n' "${resolved}"
      return 0
    fi
  done
  return 1
}

write_runtime_config() {
  local active_cli="${1:-}"
  mkdir -p "$(dirname "${CONFIG_PATH}")"
  "${VENV_DIR}/bin/python" - "${CONFIG_PATH}" "${active_cli}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
active_cli = sys.argv[2]

payload: dict[str, object]
if config_path.exists():
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: failed to parse existing config: {config_path}: {exc}")
    if not isinstance(loaded, dict):
        raise SystemExit(f"error: existing config must be a JSON object: {config_path}")
    payload = loaded
else:
    payload = {}

if active_cli and not payload.get("active_agent_cli"):
    payload["active_agent_cli"] = active_cli

cli_overrides = payload.get("cli_overrides")
if not isinstance(cli_overrides, dict):
    cli_overrides = {}

cline_override = cli_overrides.get("cline")
if not isinstance(cline_override, dict):
    cline_override = {}

extra_args = cline_override.get("extra_args")
if not isinstance(extra_args, list):
    extra_args = []
if "-y" not in extra_args:
    extra_args.append("-y")
cline_override["extra_args"] = extra_args
cli_overrides["cline"] = cline_override
payload["cli_overrides"] = cli_overrides

config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
PY
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

ensure_bashrc_path() {
  mkdir -p "$(dirname "${BASHRC_PATH}")"
  touch "${BASHRC_PATH}"

  local export_line="export PATH=\"${BIN_DIR}:\$PATH\""
  if grep -Fqs "${BIN_DIR}" "${BASHRC_PATH}"; then
    return 1
  fi

  printf '\n# dormammu\n%s\n' "${export_line}" >> "${BASHRC_PATH}"
  return 0
}

source_bashrc() {
  if [[ -f "${BASHRC_PATH}" ]]; then
    # shellcheck disable=SC1090
    source "${BASHRC_PATH}" || true
  fi
}

main() {
  require_command "${PYTHON_BIN}"
  require_command curl
  require_command tar
  require_command whereis

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
  local active_agent_cli=""
  if active_agent_cli="$(detect_active_agent_cli)"; then
    log "Detected active agent CLI: ${active_agent_cli}"
  else
    log "No supported agent CLI was auto-detected during install."
  fi
  write_runtime_config "${active_agent_cli}"

  local bashrc_updated="no"
  if ensure_bashrc_path; then
    bashrc_updated="yes"
  fi
  source_bashrc

  cat <<EOF
Installed dormammu into ${INSTALL_ROOT}
Config file: ${CONFIG_PATH}
Binary directory: ${BIN_DIR}
Active agent CLI: ${active_agent_cli:-not set}
Updated ${BASHRC_PATH}: ${bashrc_updated}

Next steps:
  ${BIN_DIR}/dormammu doctor
  ${BIN_DIR}/dormammu init-state
  ${BIN_DIR}/dormammu run --prompt "Inspect the repo and implement the requested change."
EOF
}

main "$@"
