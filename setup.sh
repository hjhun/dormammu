#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DORMAMMU_HOME="${HOME:-${USERPROFILE:-.}}/.dormammu"
INSTALL_ROOT="${DORMAMMU_INSTALL_ROOT:-${DEFAULT_DORMAMMU_HOME}}"
VENV_DIR="${DORMAMMU_VENV_DIR:-${INSTALL_ROOT}/venv}"
BIN_DIR="${DORMAMMU_BIN_DIR:-${INSTALL_ROOT}/bin}"
LAUNCHER_DIR="${DORMAMMU_LAUNCHER_DIR:-${HOME:-${USERPROFILE:-.}}/.local/bin}"
CONFIG_PATH="${DORMAMMU_CONFIG_PATH:-${DEFAULT_DORMAMMU_HOME}/config}"
BASHRC_PATH="${DORMAMMU_BASHRC_PATH:-${HOME:-${USERPROFILE:-.}}/.bashrc}"
PYTHON_BIN="${PYTHON:-python3}"
RUN_DIR="${ROOT_DIR}/.run"
WEB_PID_FILE="${RUN_DIR}/web.pid"
WEB_LOG_FILE="${RUN_DIR}/web.log"

WITH_TELEGRAM=0
WITH_WEB=0
SKIP_FRONTEND_BUILD=0
SKIP_NPM_INSTALL=0
START_WEB=0
SHUTDOWN_WEB=0
WEB_HOST="0.0.0.0"
WEB_PORT="9001"
WEB_TOKEN="${DORMAMMU_WEB_TOKEN:-}"
WEB_ALLOWED_ROOTS="${DORMAMMU_WEB_ALLOWED_ROOTS:-${ROOT_DIR}}"

log() {
  printf '[dormammu-setup] %s\n' "$*"
}

warn() {
  printf '[dormammu-setup] warning: %s\n' "$*" >&2
}

fail() {
  printf '[dormammu-setup] error: %s\n' "$*" >&2
  exit 2
}

usage() {
  cat <<'EOF'
Usage: ./setup.sh [options]

Prepare a local Dormammu checkout.

Options:
  --with-telegram              Install Telegram dependencies and offer interactive bot setup
  --with-web                   Install web dependencies for `dormammu web`
  --skip-frontend-build        Do not build frontend/ static assets
  --skip-npm-install           Do not run npm install in frontend/ or runtime/
  --start-web                  Start `dormammu web` after setup
  --shutdown-web               Stop a web server started by this setup script and exit
  --host <addr>                Web host for --start-web (default: 0.0.0.0)
  --port <n>                   Web port for --start-web (default: 9001)
  --token <token>              Web token for --start-web
  --allowed-root <path>        Add a web.allowed_roots entry; repeatable
  -h, --help                   Show this help

Environment:
  DORMAMMU_INSTALL_ROOT        Install root (default: ~/.dormammu)
  DORMAMMU_VENV_DIR            Python virtualenv path (default: ~/.dormammu/venv)
  DORMAMMU_LAUNCHER_DIR        Launcher directory (default: ~/.local/bin)
  DORMAMMU_WEB_TOKEN           Web token used by --start-web
  DORMAMMU_WEB_ALLOWED_ROOTS   Colon-separated web.allowed_roots default

Examples:
  ./setup.sh --with-web
  ./setup.sh --with-web --start-web --token "$(openssl rand -hex 24)"
  ./setup.sh --with-telegram --with-web --allowed-root ~/samba/github/dormammu
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-telegram)
      WITH_TELEGRAM=1
      shift
      ;;
    --with-web)
      WITH_WEB=1
      shift
      ;;
    --skip-frontend-build)
      SKIP_FRONTEND_BUILD=1
      shift
      ;;
    --skip-npm-install)
      SKIP_NPM_INSTALL=1
      shift
      ;;
    --start-web)
      START_WEB=1
      WITH_WEB=1
      shift
      ;;
    --shutdown-web)
      SHUTDOWN_WEB=1
      shift
      ;;
    --host)
      [[ $# -ge 2 ]] || fail "--host requires a value"
      WEB_HOST="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || fail "--port requires a value"
      WEB_PORT="$2"
      shift 2
      ;;
    --token)
      [[ $# -ge 2 ]] || fail "--token requires a value"
      WEB_TOKEN="$2"
      shift 2
      ;;
    --allowed-root)
      [[ $# -ge 2 ]] || fail "--allowed-root requires a value"
      if [[ -z "${WEB_ALLOWED_ROOTS}" ]]; then
        WEB_ALLOWED_ROOTS="$2"
      else
        WEB_ALLOWED_ROOTS="${WEB_ALLOWED_ROOTS}:$2"
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

require_command() {
  local name="$1"
  command -v "${name}" >/dev/null 2>&1 || fail "${name} is required but was not found on PATH"
}

path_contains_dir() {
  local target_dir="$1"
  case ":${PATH}:" in
    *":${target_dir}:"*) return 0 ;;
    *) return 1 ;;
  esac
}

ensure_build_backend() {
  "${VENV_DIR}/bin/python" -m pip install --upgrade "setuptools>=68" wheel
}

editable_spec() {
  local extras=()
  [[ "${WITH_TELEGRAM}" -eq 1 ]] && extras+=("telegram")
  [[ "${WITH_WEB}" -eq 1 ]] && extras+=("web")
  if [[ "${#extras[@]}" -eq 0 ]]; then
    printf '%s\n' "${ROOT_DIR}"
    return
  fi
  local joined
  joined="$(IFS=,; printf '%s' "${extras[*]}")"
  printf '%s[%s]\n' "${ROOT_DIR}" "${joined}"
}

install_launcher() {
  mkdir -p "${BIN_DIR}" "${LAUNCHER_DIR}"
  ln -sf "${VENV_DIR}/bin/dormammu" "${BIN_DIR}/dormammu"
  cat > "${LAUNCHER_DIR}/dormammu" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/dormammu" "\$@"
EOF
  chmod 755 "${LAUNCHER_DIR}/dormammu"

  local runtime_cli="${ROOT_DIR}/runtime/dist/agent/runnerCli.js"
  if [[ -f "${runtime_cli}" ]] && command -v node >/dev/null 2>&1; then
    cat > "${BIN_DIR}/dormammu-agent-runner" <<EOF
#!/usr/bin/env bash
exec node "${runtime_cli}" "\$@"
EOF
    chmod 755 "${BIN_DIR}/dormammu-agent-runner"
    cat > "${LAUNCHER_DIR}/dormammu-agent-runner" <<EOF
#!/usr/bin/env bash
exec "${BIN_DIR}/dormammu-agent-runner" "\$@"
EOF
    chmod 755 "${LAUNCHER_DIR}/dormammu-agent-runner"
  fi
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
updated: list[str] = []
legacy_removed = False
present = False
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
        present = True
        updated.extend([line, next_line])
        i += 2
        continue
    if line == launcher_export_line:
        present = True
    updated.append(line)
    i += 1
added = False
if should_add_launcher and not present:
    if updated and updated[-1] != "":
        updated.append("")
    updated.extend(["# dormammu", launcher_export_line])
    added = True
bashrc_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
print(json.dumps({"legacy_removed": legacy_removed, "launcher_added": added}))
PY
}

detect_active_agent_cli() {
  local explicit="${DORMAMMU_ACTIVE_AGENT_CLI:-}"
  local name
  if [[ -n "${explicit}" ]] && command -v "${explicit}" >/dev/null 2>&1; then
    command -v "${explicit}"
    return 0
  fi
  for name in codex claude gemini cline; do
    if command -v "${name}" >/dev/null 2>&1; then
      command -v "${name}"
      return 0
    fi
  done
  return 1
}

write_runtime_config() {
  local active_cli="${1:-}"
  local allowed_roots="${2:-}"
  local typescript_runner_cli="${3:-}"
  mkdir -p "$(dirname "${CONFIG_PATH}")"
  "${VENV_DIR}/bin/python" - "${CONFIG_PATH}" "${active_cli}" "${allowed_roots}" "${WEB_HOST}" "${WEB_PORT}" "${typescript_runner_cli}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
active_cli = sys.argv[2]
allowed_roots = [item for item in sys.argv[3].split(":") if item]
web_host = sys.argv[4]
web_port = int(sys.argv[5])
typescript_runner_cli = sys.argv[6]
if config_path.exists():
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit(f"error: existing config must be a JSON object: {config_path}")
    payload = loaded
else:
    payload = {}
if active_cli and not payload.get("active_agent_cli"):
    payload["active_agent_cli"] = active_cli
if typescript_runner_cli and not payload.get("typescript_agent_runner_cli"):
    payload["typescript_agent_runner_cli"] = typescript_runner_cli
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
if "--timeout" not in extra_args:
    extra_args.extend(["--timeout", "1200"])
cline_override["extra_args"] = extra_args
cli_overrides["cline"] = cline_override
payload["cli_overrides"] = cli_overrides
if allowed_roots:
    web = payload.get("web")
    if not isinstance(web, dict):
        web = {}
    existing = web.get("allowed_roots")
    roots = existing if isinstance(existing, list) else []
    for root in allowed_roots:
        if root not in roots:
            roots.append(root)
    web["allowed_roots"] = roots
    web.setdefault("host", web_host)
    web.setdefault("port", web_port)
    payload["web"] = web
config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
PY
}

install_agents_bundle() {
  local agents_dir="${INSTALL_ROOT}/.agents"
  "${VENV_DIR}/bin/python" - "${agents_dir}" <<'PY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import dormammu

target_dir = Path(sys.argv[1])
source_dir = Path(dormammu.__file__).resolve().parent / "assets" / ".agents"
if target_dir.exists():
    shutil.rmtree(target_dir)
shutil.copytree(source_dir, target_dir)
PY
}

build_frontend_if_available() {
  local frontend_dir="${ROOT_DIR}/frontend"
  [[ -f "${frontend_dir}/package.json" ]] || return 0
  if [[ "${SKIP_FRONTEND_BUILD}" -eq 1 ]]; then
    log "skipping frontend build"
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    warn "npm was not found; skipping frontend build"
    return 0
  fi
  (
    cd "${frontend_dir}"
    if [[ "${SKIP_NPM_INSTALL}" -eq 0 && ! -d node_modules ]]; then
      npm install
    fi
    npm run build
  )
  rm -rf "${ROOT_DIR}/backend/dormammu/web/static"
  mkdir -p "${ROOT_DIR}/backend/dormammu/web/static"
  cp -R "${frontend_dir}/dist/." "${ROOT_DIR}/backend/dormammu/web/static/"
}

build_runtime_if_available() {
  local runtime_dir="${ROOT_DIR}/runtime"
  [[ -f "${runtime_dir}/package.json" ]] || return 0
  if ! command -v npm >/dev/null 2>&1; then
    warn "npm was not found; skipping TypeScript runtime build"
    return 0
  fi
  if ! command -v node >/dev/null 2>&1; then
    warn "node was not found; skipping TypeScript runtime build"
    return 0
  fi
  (
    cd "${runtime_dir}"
    if [[ "${SKIP_NPM_INSTALL}" -eq 0 && ! -d node_modules ]]; then
      npm install
    fi
    if [[ ! -d node_modules ]]; then
      warn "runtime/node_modules is missing; skipping TypeScript runtime build"
      return 0
    fi
    npm run build
  )
}

_tty_readable() {
  [ -t 0 ] && return 0
  [ -r /dev/tty ] && [ -w /dev/tty ] && return 0
  return 1
}

configure_telegram() {
  [[ "${WITH_TELEGRAM}" -eq 1 ]] || return 0
  _tty_readable || return 0
  printf '\n=== Telegram Bot Setup (optional) ===\n'
  printf 'Set up Telegram bot now? [y/N] '
  local answer
  read -r answer </dev/tty || return 0
  case "${answer}" in
    [yY]*) ;;
    *) return 0 ;;
  esac
  printf 'Bot token (from @BotFather): '
  local token
  read -r token </dev/tty || return 0
  [[ -n "${token}" ]] || return 0
  "${VENV_DIR}/bin/dormammu" set-config telegram.bot_token "${token}" --global || warn "failed to write telegram.bot_token"
  printf 'Allowed chat ID (Enter to skip): '
  local chat_id
  read -r chat_id </dev/tty || true
  if [[ -n "${chat_id}" ]]; then
    "${VENV_DIR}/bin/dormammu" set-config telegram.allowed_chat_ids --add "${chat_id}" --global || warn "failed to write telegram.allowed_chat_ids"
  fi
}

shutdown_web() {
  if [[ ! -f "${WEB_PID_FILE}" ]]; then
    log "web pid file not found: ${WEB_PID_FILE}"
    return 0
  fi
  local pid
  pid="$(cat "${WEB_PID_FILE}")"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}" || true
    log "stopped web server pid=${pid}"
  fi
  rm -f "${WEB_PID_FILE}"
}

start_web() {
  [[ "${START_WEB}" -eq 1 ]] || return 0
  mkdir -p "${RUN_DIR}"
  if [[ -f "${WEB_PID_FILE}" ]]; then
    local old_pid
    old_pid="$(cat "${WEB_PID_FILE}")"
    if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" >/dev/null 2>&1; then
      kill "${old_pid}" || true
    fi
  fi
  DORMAMMU_WEB_TOKEN="${WEB_TOKEN}" \
    nohup "${VENV_DIR}/bin/dormammu" web --repo-root "${ROOT_DIR}" --host "${WEB_HOST}" --port "${WEB_PORT}" \
    > "${WEB_LOG_FILE}" 2>&1 < /dev/null &
  local pid="$!"
  printf '%s\n' "${pid}" > "${WEB_PID_FILE}"
  log "web server started: http://${WEB_HOST}:${WEB_PORT} pid=${pid} log=${WEB_LOG_FILE}"
}

source_command_for_guidance() {
  if [[ "${BASHRC_PATH}" == "${HOME:-}/.bashrc" ]]; then
    printf 'source ~/.bashrc'
  else
    printf 'source %q' "${BASHRC_PATH}"
  fi
}

main() {
  if [[ "${SHUTDOWN_WEB}" -eq 1 ]]; then
    shutdown_web
    exit 0
  fi

  require_command "${PYTHON_BIN}"
  mkdir -p "${INSTALL_ROOT}"
  if [[ ! -d "${VENV_DIR}" ]]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  ensure_build_backend
  build_frontend_if_available
  build_runtime_if_available
  "${VENV_DIR}/bin/python" -m pip install --use-pep517 --upgrade "$(editable_spec)"
  install_launcher
  install_agents_bundle

  local active_cli=""
  if active_cli="$(detect_active_agent_cli)"; then
    log "detected active agent CLI: ${active_cli}"
  else
    warn "no supported agent CLI was auto-detected"
  fi
  local typescript_runner_cli=""
  if [[ -x "${BIN_DIR}/dormammu-agent-runner" ]]; then
    typescript_runner_cli="${BIN_DIR}/dormammu-agent-runner"
  fi
  write_runtime_config "${active_cli}" "${WEB_ALLOWED_ROOTS}" "${typescript_runner_cli}"
  configure_telegram
  local bashrc_update_json
  bashrc_update_json="$(update_bashrc_path_entries)"
  local legacy_path_removed
  local launcher_path_added
  legacy_path_removed="$("${PYTHON_BIN}" - "${bashrc_update_json}" <<'PY'
import json, sys
print("yes" if json.loads(sys.argv[1])["legacy_removed"] else "no")
PY
)"
  launcher_path_added="$("${PYTHON_BIN}" - "${bashrc_update_json}" <<'PY'
import json, sys
print("yes" if json.loads(sys.argv[1])["launcher_added"] else "no")
PY
)"
  start_web

  cat <<EOF
Installed dormammu into ${VENV_DIR}.
Installed Dormammu from ${ROOT_DIR}
Virtualenv: ${VENV_DIR}
Binary directory: ${BIN_DIR}
Launcher: ${LAUNCHER_DIR}/dormammu
Launcher directory: ${LAUNCHER_DIR}
TypeScript runner: $(if [[ -x "${LAUNCHER_DIR}/dormammu-agent-runner" ]]; then printf '%s' "${LAUNCHER_DIR}/dormammu-agent-runner"; else printf 'not installed'; fi)
Config: ${CONFIG_PATH}
Config file: ${CONFIG_PATH}
Agents directory: ${INSTALL_ROOT}/.agents
Active agent CLI: ${active_cli:-not set}
PATH update: ${bashrc_update_json}
Removed legacy ${BIN_DIR} PATH entry from ${BASHRC_PATH}: ${legacy_path_removed}
Added ${LAUNCHER_DIR} PATH entry to ${BASHRC_PATH}: ${launcher_path_added}

Next steps:
  $(source_command_for_guidance)
  dormammu doctor --repo-root "${ROOT_DIR}"
  dormammu web --repo-root "${ROOT_DIR}" --token <token>
EOF
}

main "$@"
