#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="${DORMAMMU_REPO:-hjhun/dormammu}"
DEFAULT_DORMAMMU_HOME="${HOME}/.dormammu"
DEFAULT_INSTALL_ROOT="${DEFAULT_DORMAMMU_HOME}"
INSTALL_ROOT="${DORMAMMU_INSTALL_ROOT:-${DEFAULT_INSTALL_ROOT}}"
BIN_DIR="${DORMAMMU_BIN_DIR:-${DEFAULT_DORMAMMU_HOME}/bin}"
LAUNCHER_DIR="${DORMAMMU_LAUNCHER_DIR:-${HOME}/.local/bin}"
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

ensure_build_backend() {
  "${VENV_DIR}/bin/python" -m pip install --upgrade "setuptools>=68" wheel
}

install_runtime_package() {
  local source_location="$1"
  # Force pip's modern PEP 517 path for release installs so source installs do
  # not fall back to legacy `setup.py bdist_wheel` behavior on older runtimes.
  "${VENV_DIR}/bin/python" -m pip install --use-pep517 --upgrade "${source_location}"
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
if "--verbose" not in extra_args:
    extra_args.append("--verbose")
if "--timeout" not in extra_args:
    extra_args.extend(["--timeout", "1200"])
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

install_launcher() {
  mkdir -p "${LAUNCHER_DIR}"
  cat > "${LAUNCHER_DIR}/dormammu" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/dormammu" "\$@"
EOF
  chmod 755 "${LAUNCHER_DIR}/dormammu"
}

install_agents_bundle() {
  local agents_dir="${INSTALL_ROOT}/agents"
  "${VENV_DIR}/bin/python" - "${agents_dir}" <<'PY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import dormammu

target_dir = Path(sys.argv[1])
source_dir = Path(dormammu.__file__).resolve().parent / "assets" / "agents"
if target_dir.exists():
    shutil.rmtree(target_dir)
shutil.copytree(source_dir, target_dir)
PY
}

path_contains_dir() {
  local target_dir="$1"
  case ":${PATH}:" in
    *":${target_dir}:"*) return 0 ;;
    *) return 1 ;;
  esac
}

update_bashrc_path_entries() {
  mkdir -p "$(dirname "${BASHRC_PATH}")"
  touch "${BASHRC_PATH}"

  local legacy_export_line="export PATH=\"${BIN_DIR}:\$PATH\""
  local launcher_export_line="export PATH=\"${LAUNCHER_DIR}:\$PATH\""
  local should_add_launcher="yes"

  if path_contains_dir "${LAUNCHER_DIR}"; then
    should_add_launcher="no"
  fi

  "${PYTHON_BIN}" - "${BASHRC_PATH}" "${legacy_export_line}" "${launcher_export_line}" "${should_add_launcher}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

bashrc_path = Path(sys.argv[1])
legacy_export_line = sys.argv[2]
launcher_export_line = sys.argv[3]
should_add_launcher = sys.argv[4] == "yes"

lines = bashrc_path.read_text(encoding="utf-8").splitlines()
updated_lines: list[str] = []
legacy_removed = False
launcher_present = False
i = 0

while i < len(lines):
    line = lines[i]
    next_line = lines[i + 1] if i + 1 < len(lines) else None

    if line == "# dormammu" and next_line == legacy_export_line:
        legacy_removed = True
        i += 2
        continue

    if line == legacy_export_line:
        legacy_removed = True
        i += 1
        continue

    if line == "# dormammu" and next_line == launcher_export_line:
        launcher_present = True
        updated_lines.append(line)
        updated_lines.append(next_line)
        i += 2
        continue

    if line == launcher_export_line:
        launcher_present = True

    updated_lines.append(line)
    i += 1

launcher_added = False
if should_add_launcher and not launcher_present:
    if updated_lines and updated_lines[-1] != "":
        updated_lines.append("")
    updated_lines.append("# dormammu")
    updated_lines.append(launcher_export_line)
    launcher_added = True

bashrc_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
print(json.dumps({"legacy_removed": legacy_removed, "launcher_added": launcher_added}))
PY
}

_tty_readable() {
  # Returns 0 (true) if the user can be prompted interactively.
  [ -t 0 ] && return 0
  [ -r /dev/tty ] && [ -w /dev/tty ] && return 0
  return 1
}

configure_telegram() {
  if ! _tty_readable; then
    return 0
  fi

  printf '\n=== Telegram Bot Setup (optional) ===\n'
  printf 'dormammu can receive commands and stream output via a Telegram bot.\n'
  printf 'You will need a bot token from @BotFather and your Telegram chat ID.\n'
  printf '\nSet up Telegram bot now? [y/N] '
  local setup_telegram
  read -r setup_telegram </dev/tty || return 0
  case "${setup_telegram}" in
    [yY]*) ;;
    *)
      log ''
      log 'Skipping Telegram setup. Configure it later with:'
      log "  dormammu set-config telegram.bot_token <TOKEN> --global"
      log "  dormammu set-config telegram.allowed_chat_ids --add <CHAT_ID> --global"
      log "  pip install 'dormammu[telegram]'"
      return 0
      ;;
  esac

  printf 'Bot token (from @BotFather): '
  local tg_token
  read -r tg_token </dev/tty || return 0
  if [[ -z "${tg_token}" ]]; then
    log 'No token entered. Skipping Telegram setup.'
    return 0
  fi

  if ! "${VENV_DIR}/bin/dormammu" set-config telegram.bot_token "${tg_token}" --global; then
    log 'warning: failed to write telegram.bot_token to config.'
    return 0
  fi

  printf 'Allowed chat ID (your Telegram user or group ID, Enter to skip): '
  local tg_chat_id
  read -r tg_chat_id </dev/tty || true
  if [[ -n "${tg_chat_id}" ]]; then
    if ! "${VENV_DIR}/bin/dormammu" set-config telegram.allowed_chat_ids --add "${tg_chat_id}" --global; then
      log 'warning: failed to write telegram.allowed_chat_ids to config.'
    fi
  fi

  log ''
  log "Telegram bot configured (stored in ${CONFIG_PATH})."
  log "Install the Telegram dependency with:"
  log "  pip install 'dormammu[telegram]'"
}

source_command_for_guidance() {
  if [[ "${BASHRC_PATH}" == "${HOME}/.bashrc" ]]; then
    printf 'source ~/.bashrc'
    return 0
  fi

  printf 'source %q' "${BASHRC_PATH}"
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
  ensure_build_backend

  if [[ -d "${source_location}" ]]; then
    log "Installing dormammu from local source directory: ${source_location}"
    install_runtime_package "${source_location}"
  else
    TMP_DIR="$(mktemp -d)"
    local archive_path="${TMP_DIR}/dormammu.tar.gz"
    log "Downloading dormammu (${source_label}) from ${source_location}"
    curl -fsSL "${source_location}" -o "${archive_path}"
    local source_dir
    source_dir="$(extract_archive "${archive_path}" "${TMP_DIR}")"
    install_runtime_package "${source_dir}"
  fi

  link_binary
  install_launcher
  install_agents_bundle
  local active_agent_cli=""
  if active_agent_cli="$(detect_active_agent_cli)"; then
    log "Detected active agent CLI: ${active_agent_cli}"
  else
    log "No supported agent CLI was auto-detected during install."
  fi
  write_runtime_config "${active_agent_cli}"
  configure_telegram

  local bashrc_update_json
  local legacy_path_removed
  local launcher_path_added
  bashrc_update_json="$(update_bashrc_path_entries)"
  legacy_path_removed="$("${PYTHON_BIN}" - "${bashrc_update_json}" <<'PY'
from __future__ import annotations

import json
import sys

payload = json.loads(sys.argv[1])
print("yes" if payload["legacy_removed"] else "no")
PY
)"
  launcher_path_added="$("${PYTHON_BIN}" - "${bashrc_update_json}" <<'PY'
from __future__ import annotations

import json
import sys

payload = json.loads(sys.argv[1])
print("yes" if payload["launcher_added"] else "no")
PY
)"

  cat <<EOF
Installed dormammu into ${INSTALL_ROOT}
Config file: ${CONFIG_PATH}
Binary directory: ${BIN_DIR}
Launcher directory: ${LAUNCHER_DIR}
Agents directory: ${INSTALL_ROOT}/agents
Active agent CLI: ${active_agent_cli:-not set}
Removed legacy ${BIN_DIR} PATH entry from ${BASHRC_PATH}: ${legacy_path_removed}
Added ${LAUNCHER_DIR} PATH entry to ${BASHRC_PATH}: ${launcher_path_added}

Next steps:
  $(source_command_for_guidance)
  dormammu doctor
  dormammu init-state
  dormammu run --prompt "Inspect the repo and implement the requested change."
EOF
}

main "$@"
