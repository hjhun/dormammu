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

## Install Script

```bash
./scripts/install.sh
```

That script creates or reuses `.venv`, upgrades `pip`, installs the package in
editable mode, and prints the next `doctor` and `ui` commands.

## Primary Commands

```bash
dormammu run --agent-cli /path/to/agent-cli --prompt "Do the work"
dormammu resume
dormammu ui
dormammu doctor --agent-cli /path/to/agent-cli
```

Low-level compatibility commands such as `run-loop`, `resume-loop`, and
`serve` remain available.

## Project Layout

```text
backend/     Python package and runtime services
frontend/    Lightweight local UI assets
templates/   Bootstrap templates for .dev state
scripts/     Developer convenience scripts
tests/       Bootstrap validation tests
```
