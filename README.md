# dormammu

`dormammu` is a Python-based coding agent loop orchestrator with a terminal
first core, resumable `.dev/` state, supervisor-driven validation, and an
optional local web UI.

## Phase 1 Bootstrap

This repository currently bootstraps:

- a Python package under `backend/`
- a CLI entrypoint for config inspection, state initialization, and local serve
- `.dev` bootstrap helpers and Markdown templates
- a lightweight local UI served from `frontend/`

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m dormammu show-config
python -m dormammu init-state
python -m dormammu serve
# then open http://127.0.0.1:8000/
```

## Project Layout

```text
backend/     Python package and runtime services
frontend/    Lightweight local UI assets
templates/   Bootstrap templates for .dev state
scripts/     Developer convenience scripts
tests/       Bootstrap validation tests
```
