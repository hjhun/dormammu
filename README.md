# dormammu

`dormammu` is a Python-based coding agent loop orchestrator with a terminal
first core, resumable `.dev/` state, supervisor-driven validation, and an
optional local web UI.

## Phase 1 Bootstrap

This repository currently bootstraps:

- a Python package under `backend/`
- a CLI entrypoint for config inspection, state initialization, run/resume/ui,
  and environment diagnostics
- `.dev` bootstrap helpers and Markdown templates
- a lightweight local UI served from `frontend/`

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
dormammu doctor --repo-root . --agent-cli /path/to/agent-cli
dormammu init-state
dormammu ui
# then open http://127.0.0.1:8000/
```

## Curl Install

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

The repository-root `install.sh` is the distribution bootstrapper for
user-local installs. By default it installs into `~/.local/share/dormammu`,
links `dormammu` into `~/.local/bin`, and installs from the latest GitHub
release when one exists or falls back to the `main` branch archive.

Useful overrides:

```bash
DORMAMMU_INSTALL_ROOT=/opt/dormammu \
DORMAMMU_BIN_DIR=/usr/local/bin \
PYTHON=python3.12 \
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

## Local Dev Install

```bash
./scripts/install.sh
```

That script is for a checked-out repository. It creates or reuses `.venv`,
upgrades `pip`, installs the package in editable mode, and prints the next
`doctor` and `ui` commands.

## Primary Commands

```bash
dormammu run --agent-cli /path/to/agent-cli --prompt "Do the work"
dormammu resume --session-id saved-session-id
dormammu start-session --goal "New workflow scope"
dormammu sessions
dormammu restore-session --session-id saved-session-id
dormammu inspect-cli --agent-cli /path/to/agent-cli
dormammu ui
dormammu doctor --agent-cli /path/to/agent-cli
```

Low-level compatibility commands such as `run-loop`, `resume-loop`, and
`serve` remain available.

`inspect-cli` prints the detected prompt handling mode, matched known preset,
and any approval-skipping candidates so operators can review risky flags before
running a real workflow.

`start-session` archives the current active `.dev` state into
`.dev/sessions/<session_id>/` and resets the root `.dev` files for a fresh
active session. `sessions` lists the saved session snapshots as JSON.

`restore-session` loads a saved snapshot back into the active root `.dev`
files, and `resume --session-id <id>` restores that saved session first and
then continues with the normal supervised recovery flow.

## Release Packaging

`.github/workflows/release.yml` packages the project on `v*` tag pushes and on
manual workflow dispatch. The workflow builds wheel and sdist artifacts, uploads
them as workflow artifacts, and attaches `dist/*` plus `install.sh` to the
GitHub release when the run is triggered by a version tag.

## Project Layout

```text
backend/     Python package and runtime services
frontend/    Lightweight local UI assets
templates/   Bootstrap templates for .dev state
scripts/     Developer convenience scripts
tests/       Bootstrap validation tests
```

## License

`dormammu` is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
