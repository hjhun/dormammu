# DORMAMMU Guide

`dormammu` is a CLI-first workflow loop orchestrator for coding agents. It
wraps an external agent CLI with state management, supervision, resumability,
and operator-visible artifacts.

If you want the fast overview, read the main [README.md](../README.md) first.

## What DORMAMMU Is Good At

`dormammu` is designed for repositories where agent runs need to be:

- repeatable
- inspectable
- resumable
- safe to supervise
- easy to operate from a terminal

Instead of treating an agent call as a black box, `dormammu` keeps the prompt,
logs, session state, and validation context together under `.dev/`.

## Core Features

- External CLI orchestration for coding agents
- Single-run execution and supervised retry loops
- Resume support after interruption
- Session bootstrap, archival, listing, and restoration
- Markdown plus JSON state tracking under `.dev/`
- Guidance-file embedding for repository-specific operating rules
- Fallback agent CLIs for quota or token exhaustion
- CLI inspection for prompt mode, workdir support, and risky approval flags
- Environment diagnostics through `doctor`

## Supported Agent CLI Patterns

`dormammu` includes preset-aware behavior for common coding-agent CLIs:

- `codex`
- `claude`
- `gemini`
- `cline`
- `aider`

Preset support helps `dormammu` infer prompt style, command prefix, workdir
flags, and common approval-related options. You can inspect the resolved view
with:

```bash
dormammu inspect-cli --repo-root . --agent-cli codex
```

## Installation

### Install from the repository release script

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

### Install from a local clone

```bash
./scripts/install.sh
```

### Install for development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

`dormammu` requires Python `3.10+`.

## Quick Start

### 1. Verify the environment

```bash
dormammu doctor --repo-root . --agent-cli codex
```

This checks Python, the agent CLI path, repository writability, and whether
the repository contains an agent workspace directory such as `.agents`.

### 2. Create or merge `.dev` bootstrap state

```bash
dormammu init-state \
  --repo-root . \
  --goal "Implement the requested repository task."
```

This initializes or refreshes state such as:

- `.dev/DASHBOARD.md`
- `.dev/PLAN.md`
- `.dev/session.json`
- `.dev/workflow_state.json`

It also probes the local machine for supported coding-agent CLIs and updates
`active_agent_cli` to the highest-priority available command in this order:
`codex`, `claude`, `gemini`, `cline`.

### 3. Inspect how an external CLI will be driven

```bash
dormammu inspect-cli --repo-root . --agent-cli cline
```

This is especially useful when you want to confirm prompt handling, workdir
support, or approval-skipping hints before using a real run.

### 4. Execute one agent call

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli codex \
  --prompt "Read the repo guidance and summarize the next implementation step."
```

Use `run-once` when you want one bounded agent execution with artifact capture
but without a supervised retry loop.

### 5. Execute the supervised loop

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes \
  --max-iterations 50
```

Use `run` when you want `dormammu` to:

- execute the external agent
- validate the result
- generate continuation context when the result is incomplete
- retry according to your loop settings

If you do not set either `--max-iterations` or `--max-retries`, Dormammu
defaults to `50` total attempts. If the supervisor approves the work before
that limit, Dormammu exits immediately.

### 6. Resume later

```bash
dormammu resume --repo-root .
```

`resume` continues from the saved loop state instead of restarting the whole
workflow from the beginning.

## Understanding The Main Commands

### `dormammu doctor`

Checks:

- Python version
- agent CLI availability
- `.agent` or `.agents` workspace presence
- repository write access

### `dormammu init-state`

Creates or merges bootstrap state for the active repository. This is the
simplest way to prepare `.dev/` before the first real run. During bootstrap it
also refreshes `active_agent_cli` to the highest-priority available supported
CLI: `codex`, `claude`, `gemini`, then `cline`.

### `dormammu run-once`

Runs one external agent invocation and stores:

- the prompt artifact
- stdout and stderr logs
- metadata about the command and detected CLI capabilities
- the latest run reference in workflow state

### `dormammu run`

Runs the supervised loop. Common options include:

- `--max-iterations`
- `--required-path`
- `--require-worktree-changes`
- `--max-retries`
- `--workdir`
- `--extra-arg`
- `--guidance-file`

### `dormammu resume`

Reloads saved loop state and continuation context, then restarts the standard
recovery path.

### `dormammu inspect-cli`

Prints JSON describing:

- detected prompt mode
- known preset match
- command prefix
- workdir flag support
- approval-related hints

### Session commands

`dormammu` also supports:

- `start-session`
- `sessions`
- `restore-session`

These are useful when you want to branch workflow history or return to an older
saved session snapshot.

## The `.dev` Directory

`dormammu` uses `.dev/` as the shared control surface for humans and tooling.

The most important files are:

- `.dev/DASHBOARD.md`: operator-facing current status
- `.dev/PLAN.md`: prompt-derived implementation checklist
- `.dev/workflow_state.json`: machine-readable workflow truth
- `.dev/session.json`: active session metadata
- `.dev/logs/`: run artifacts and log files

`DORMAMMU.log` at the repository root captures command-level execution banners
and mirrored stderr output for `run`, `run-once`, and `resume`.

## Guidance File Behavior

Guidance files let you inject repository-specific operating rules into runs.

You can pass them explicitly:

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --guidance-file AGENTS.md \
  --guidance-file docs/agent-rules.md \
  --prompt "Implement the requested change."
```

Resolution order is:

1. explicit `--guidance-file`
2. repository guidance such as `AGENTS.md` or `agents/AGENTS.md`
3. installed fallback guidance under `~/.dormammu/agents`
4. packaged fallback guidance assets

## Working Directory And CLI Overrides

When you pass `--workdir`, `dormammu` always uses that directory as the process
working directory for the external CLI. If the adapter knows the CLI's workdir
flag, it forwards the value there too.

For example, the Cline preset supports:

- positional prompts
- `-y`
- default `--verbose`
- `--cwd <path>`

Example:

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli cline \
  --workdir ./subproject \
  --prompt "Inspect this subproject and summarize the next step."
```

## Fallback Agent CLIs

If the primary backend runs into token or quota problems, `dormammu` can try
another configured CLI. Without an explicit config, the fallback order is:

- `codex`
- `claude`
- `gemini`

Example config:

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
      "extra_args": ["-y", "--verbose"]
    }
  }
}
```

## Typical Operator Flow

```bash
dormammu doctor --repo-root . --agent-cli codex
dormammu init-state --repo-root . --goal "Ship the requested change safely"
dormammu inspect-cli --repo-root . --agent-cli codex
dormammu run --repo-root . --agent-cli codex --prompt-file PROMPT.md --required-path README.md
dormammu resume --repo-root .
```

## Repository Layout

```text
backend/     Python package, loop engine, adapters, state, supervisor
agents/      Distributable workflow and skill guidance bundle
templates/   Bootstrap templates for `.dev`
docs/        Documentation
scripts/     Install and developer helper scripts
tests/       Runtime and workflow validation
```
