# DORMAMMU Guide

`dormammu` is a CLI-first workflow loop engine for coding agents. It runs an
external agent CLI, saves machine and human-readable state under `.dev/`, lets
a supervisor validate outcomes, and helps you resume safely after interruption.

## What DORMAMMU Does

At a high level, `dormammu` helps you manage repeated agent work in a safer
way.

It gives you:

- a terminal-only workflow surface
- resumable state saved under `.dev/`
- supervisor checks for required files and worktree changes
- continuation prompts when the first run is not enough
- fallback CLI support when the primary backend hits quota or token limits

## Core Ideas

### 1. CLI-first architecture

The important workflows work from Python modules and CLI entrypoints first and
only.

### 2. Saved state under `.dev/`

`dormammu` writes both human-readable and machine-readable state into `.dev/`
so a run can be inspected and resumed later.

### 3. Supervisor-driven validation

After a run finishes, the supervisor checks whether the expected result exists.
If not, `dormammu` can prepare continuation work instead of pretending the job
is done.

### 4. Resume instead of restart

If a process is interrupted, you can continue from saved state rather than
throwing away the whole session.

## Repository Layout

```text
backend/     Python package, loop engine, adapters, supervisor
templates/   Bootstrap templates for .dev state
docs/        Project documentation
scripts/     Install and developer convenience scripts
tests/       Runtime and workflow validation
```

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

Or for local development:

```bash
./scripts/install.sh
```

## Quick Start

```bash
dormammu doctor --repo-root . --agent-cli codex
dormammu init-state
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt "Inspect the repo and implement the requested change." \
  --required-path README.md
```

What each step does:

1. `doctor` checks whether your environment is ready.
2. `init-state` creates or merges the bootstrap `.dev` files.
3. `run` starts a supervised retry loop around the external agent CLI.

## Understanding The `.dev` Directory

These files matter most:

- `.dev/DASHBOARD.md`
- `.dev/TASKS.md`
- `.dev/workflow_state.json`
- `.dev/session.json`
- `.dev/logs/`

They keep the workflow inspectable, automatable, and resumable.

## The Main Commands

### `dormammu run`

Runs the supervised loop around your external agent CLI.

### `dormammu resume`

Resumes the most recent supervised loop from saved state.

### `dormammu doctor`

Checks whether the current environment is ready to run `dormammu`.

### `dormammu inspect-cli`

Inspects how an external CLI handles prompts and whether it shows risky
approval-skipping hints.
