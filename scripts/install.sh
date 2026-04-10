#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
LAUNCHER_DIR="${DORMAMMU_LAUNCHER_DIR:-${HOME}/.local/bin}"
BASHRC_PATH="${DORMAMMU_BASHRC_PATH:-${HOME}/.bashrc}"
PYTHON_BIN="${PYTHON:-python3}"

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

install_launcher() {
  mkdir -p "${LAUNCHER_DIR}"
  cat > "${LAUNCHER_DIR}/dormammu" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/dormammu" "\$@"
EOF
  chmod 755 "${LAUNCHER_DIR}/dormammu"
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

  local launcher_export_line="export PATH=\"${LAUNCHER_DIR}:\$PATH\""
  local should_add_launcher="yes"

  if path_contains_dir "${LAUNCHER_DIR}"; then
    should_add_launcher="no"
  fi

  "${PYTHON_BIN}" - "${BASHRC_PATH}" "${launcher_export_line}" "${should_add_launcher}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

bashrc_path = Path(sys.argv[1])
launcher_export_line = sys.argv[2]
should_add_launcher = sys.argv[3] == "yes"

lines = bashrc_path.read_text(encoding="utf-8").splitlines()
updated_lines: list[str] = []
launcher_present = False
i = 0

while i < len(lines):
    line = lines[i]
    next_line = lines[i + 1] if i + 1 < len(lines) else None

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
print(json.dumps({"launcher_added": launcher_added}))
PY
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

  if [[ ! -d "${VENV_DIR}" ]]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi

  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/pip" install -e "${ROOT_DIR}"
  install_launcher

  local bashrc_update_json
  local launcher_path_added
  bashrc_update_json="$(update_bashrc_path_entries)"
  launcher_path_added="$("${PYTHON_BIN}" - "${bashrc_update_json}" <<'PY'
from __future__ import annotations

import json
import sys

payload = json.loads(sys.argv[1])
print("yes" if payload["launcher_added"] else "no")
PY
)"

  cat <<EOF
Installed dormammu into ${VENV_DIR}.
Launcher directory: ${LAUNCHER_DIR}
Added ${LAUNCHER_DIR} PATH entry to ${BASHRC_PATH}: ${launcher_path_added}

Next steps:
  $(source_command_for_guidance)
  dormammu doctor --repo-root "${ROOT_DIR}" --agent-cli /path/to/agent-cli
  dormammu init-state --repo-root "${ROOT_DIR}"
  dormammu run --repo-root "${ROOT_DIR}" --prompt "Inspect the repo and implement the requested change."
EOF
}

main "$@"
