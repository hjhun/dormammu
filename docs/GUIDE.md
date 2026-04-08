# DORMAMMU Guide

This guide introduces `dormammu` for first-time users and contributors.

`dormammu` is a terminal-first workflow loop engine for coding agents. It runs
an external agent CLI, saves machine and human-readable state under `.dev/`,
lets a supervisor validate outcomes, and helps you resume safely after
interruption.

If you want a coding-agent workflow that is more structured than "run the tool
and hope for the best," this project is designed for that job.

`dormammu` supports Python `3.10+`.

## Who This Guide Is For

This guide is for you if:

- you are new to `dormammu`
- you want to understand what problem the project solves
- you want copy-pasteable commands for your first run
- you want to understand the `.dev` files before editing or debugging them

## What DORMAMMU Does

At a high level, `dormammu` helps you manage repeated agent work in a safer
way.

Instead of treating a coding-agent run as a single one-off command, it gives
you:

- a terminal-first core that works without the web UI
- resumable state saved under `.dev/`
- supervisor checks for required files and worktree changes
- continuation prompts when the first run is not enough
- an optional local browser UI for visibility
- fallback CLI support when the primary backend hits quota or token limits

## Core Ideas

### 1. Terminal-first architecture

The important workflows work from Python modules and CLI entrypoints first.
The local web UI is helpful, but it is optional.

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

The main directories look like this:

```text
backend/     Python package, loop engine, adapters, supervisor, API
frontend/    Lightweight local UI assets
templates/   Bootstrap templates for .dev state
docs/        Project documentation
scripts/     Install and developer convenience scripts
tests/       Runtime and workflow validation
```

## Installation

Choose the path that matches how you want to use the project.

### Option 1: User install from the repository installer

This is the easiest way to get a runnable `dormammu` command.

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

By default, this installer:

- creates a runtime under `~/.dormammu`
- links `dormammu` into `~/.dormammu/bin`
- writes config to `~/.dormammu/config`
- updates `~/.bashrc` idempotently
- tries to detect an available agent CLI such as `codex`, `claude`, `gemini`,
  or `cline`

### Option 2: Local repository install

If you already cloned the repository and want a local development setup:

```bash
./scripts/install.sh
```

This script creates or reuses `.venv`, upgrades `pip`, and installs the project
in editable mode.

### Option 3: Editable manual install

If you prefer to manage the environment yourself:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

If your machine has multiple Python versions installed, pick any
`python3.10+` interpreter explicitly, such as `python3.10 -m venv .venv`.

## How To Run The CLI From Source

If you have not installed the package yet, you can still run it directly from
the repository:

```bash
PYTHONPATH=backend python3 -m dormammu --help
```

Throughout this guide, commands are shown with the installed `dormammu`
executable because that is the simplest operator experience. If you are working
from source only, replace `dormammu` with:

```bash
PYTHONPATH=backend python3 -m dormammu
```

## Before Your First Run

Make sure the repository contains either `.agent` or `.agents`. The `doctor`
command checks for one of those directories because they are part of the agent
workspace contract in this project.

Also make sure you have a coding-agent CLI available. You can pass it
explicitly with `--agent-cli`, or configure a default `active_agent_cli` in the
runtime config.

## Quick Start

This is the smallest useful first-run flow:

```bash
dormammu doctor --repo-root . --agent-cli codex
dormammu init-state
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt "Inspect the repo and implement the requested change." \
  --required-path README.md
dormammu ui
```

Then open `http://127.0.0.1:8000/` in your browser if you started the UI.

What each step does:

1. `doctor` checks whether your environment is ready.
2. `init-state` creates or merges the bootstrap `.dev` files.
3. `run` starts a supervised retry loop around the external agent CLI.
4. `ui` starts the optional browser view for logs and state.

## Understanding The `.dev` Directory

One of the most important ideas in `dormammu` is that state lives in files.

These files matter most:

- `.dev/DASHBOARD.md`
  Human-readable workflow summary, active phase, next action, and supervisor
  verdict.
- `.dev/TASKS.md`
  Human-readable task checklist for the active slice.
- `.dev/workflow_state.json`
  Machine-readable source of truth for workflow state.
- `.dev/session.json`
  Active session metadata, resume checkpoints, and recent loop details.
- `.dev/logs/`
  Prompt artifacts, stdout logs, stderr logs, and metadata for recorded runs.

Why this matters:

- humans can inspect progress without custom tooling
- automation can still read structured JSON
- interrupted sessions can be resumed with evidence

## The Main Commands

### `dormammu run`

Runs the supervised loop around your external agent CLI.

Example:

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt "Add a setup guide to the repo." \
  --required-path docs/GUIDE.md \
  --require-worktree-changes
```

Useful flags:

- `--prompt` or `--prompt-file`
- `--agent-cli`
- `--required-path`
- `--require-worktree-changes`
- `--max-retries`
- `--extra-arg`

Use `--max-retries -1` if you want infinite retries after the first attempt.

### `dormammu resume`

Resumes the most recent supervised loop from saved state.

Example:

```bash
dormammu resume --repo-root .
```

If you are using saved sessions, you can also restore a specific session before
resuming:

```bash
dormammu resume --repo-root . --session-id your-session-id
```

### `dormammu doctor`

Checks whether the current environment is ready to run `dormammu`.

It validates:

- Python version
- agent CLI availability
- presence of `.agent` or `.agents`
- repository write access

Example:

```bash
dormammu doctor --repo-root . --agent-cli codex
```

### `dormammu inspect-cli`

Inspects how an external CLI handles prompts and whether it shows risky
approval-skipping hints.

Example:

```bash
dormammu inspect-cli --repo-root . --agent-cli codex --include-help-text
```

### `dormammu ui`

Starts the optional local UI.

Example:

```bash
dormammu ui --repo-root .
```

### Session management commands

These commands help when you want to manage multiple saved workflow states:

- `dormammu start-session`
- `dormammu sessions`
- `dormammu restore-session`

## Configuration

`dormammu` can read configuration from three places, in this order:

1. `DORMAMMU_CONFIG_PATH`
2. `dormammu.json` in the repository root
3. `~/.dormammu/config`

That precedence matters because it lets you keep:

- a one-off override for a specific shell session
- a repo-local config committed or shared with a team
- a user-level default config for everyday use

### Example config

```json
{
  "active_agent_cli": "/home/you/.local/bin/codex",
  "fallback_agent_clis": [
    "claude",
    {
      "path": "aider",
      "extra_args": ["--yes"]
    }
  ],
  "cli_overrides": {
    "cline": {
      "extra_args": ["-y"]
    }
  },
  "token_exhaustion_patterns": [
    "usage limit",
    "quota exceeded",
    "rate limit exceeded",
    "token limit"
  ]
}
```

### What these fields mean

- `active_agent_cli`
  Default CLI used when `--agent-cli` is omitted.
- `fallback_agent_clis`
  Additional CLIs to try when the main backend is exhausted.
- `cli_overrides`
  Family-specific defaults, such as extra args.
  The built-in `cline` preset uses a positional prompt, so `extra_args: ["-y"]`
  produces invocations such as `cline -y "Inspect the repo"`.
- `token_exhaustion_patterns`
  Output patterns that tell `dormammu` when it should attempt fallback.

## Fallback CLI Behavior

When the primary coding-agent CLI hits quota or token exhaustion, `dormammu`
can try another configured CLI without consuming the supervised retry budget.

Important behavior:

- the explicitly requested CLI is always tried first
- fallback only happens when output matches a token exhaustion pattern
- fallback attempts do not consume the normal retry count
- if every configured CLI is exhausted, the run stops in a `blocked` state

## Suggested Beginner Workflow

If you are new to the project, this is a safe operating pattern:

1. Run `dormammu doctor`.
2. Run `dormammu inspect-cli` once for the CLI you plan to use.
3. Run `dormammu init-state`.
4. Start a small `dormammu run` with one or two `--required-path` checks.
5. Open `dormammu ui` if you want live visibility.
6. Use `dormammu resume` instead of manually recreating interrupted work.

## Troubleshooting

### `doctor` says the agent CLI is missing

Pass an explicit path:

```bash
dormammu doctor --repo-root . --agent-cli /full/path/to/codex
```

Or set `active_agent_cli` in config so you do not need to repeat the path.

### `doctor` says `.agent` or `.agents` is missing

Create or restore the agent workspace directory expected by the repository.
This project uses that directory as part of its workflow contract.

### `dormammu` is not found after install

Open a new shell, or confirm that `~/.dormammu/bin` is on your `PATH`.

You can also run the tool directly from source with:

```bash
PYTHONPATH=backend python3 -m dormammu --help
```

### The run stopped before the work was complete

Check:

- `.dev/DASHBOARD.md` for the next action
- `.dev/TASKS.md` for task progress
- `.dev/supervisor_report.md` for the last validation result
- `.dev/logs/` for prompt, stdout, stderr, and metadata artifacts

Then use:

```bash
dormammu resume --repo-root .
```

### The UI is not necessary for core workflows

This is expected. The core product is intentionally usable without the web UI.
If the UI is unavailable, the main terminal and `.dev` workflow can still
continue.

## Where To Go Next

After you are comfortable with the basics:

- read [README.md](../README.md) for the shorter project overview
- inspect `.dev/PROJECT.md` and `.dev/ROADMAP.md` if you are contributing to
  the product direction
- explore the tests under `tests/` to understand expected behavior
