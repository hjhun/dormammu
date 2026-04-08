<p align="center">
  <img src="docs/svg/dormammu.svg" alt="DORMAMMU logo" width="180">
</p>

# DORMAMMU: Workflow Loop Engine

`dormammu` is a terminal-first workflow loop engine for coding agents. It runs
an external agent CLI, records machine and human-readable state under `.dev/`,
lets a supervisor validate outcomes, and resumes safely after interruption.
The supported runtime target is Python `3.10+`.

If you want something more durable than "run an agent and hope for the best,"
this project is built for that gap.

Start with the full project guide at [docs/GUIDE.md](docs/GUIDE.md).

## Why DORMAMMU

- Terminal-first core: the essential workflow works from Python modules and CLI
  entrypoints without depending on the web UI.
- Resumable by default: execution state, operator notes, prompts, and logs are
  written to `.dev/` so interrupted runs can continue instead of restarting.
- Supervisor-driven validation: required paths, worktree changes, and follow-up
  continuation prompts are handled as part of the loop.
- Operator-visible state: Markdown files remain readable for humans while JSON
  state stays available for tooling and automation.
- Optional local UI: run `dormammu ui` for a browser view of progress, logs,
  and key state files.
- Fallback agent CLIs: configure failover when the primary coding agent hits a
  token or quota wall.

## What It Looks Like In Practice

1. Start a supervised run against your preferred coding-agent CLI.
2. Persist prompts, logs, and workflow state into `.dev/`.
3. Let the supervisor check whether the run actually produced the expected
   outcome.
4. Resume from saved state when the process is interrupted or additional work
   is needed.

## Install

### User Install

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

The repository-root `install.sh` installs the runtime under `~/.dormammu`,
links `dormammu` into
`~/.dormammu/bin`, writes runtime config to `~/.dormammu/config`, updates
`~/.bashrc` idempotently, and prefers the latest GitHub release when one
exists.

During install, the script tries to detect an active agent CLI with `whereis`
in this order:

- `codex`
- `claude`
- `gemini`
- `cline`

If one is found, it is stored as `active_agent_cli` in `~/.dormammu/config`.
You can edit that file later at any time.

Useful overrides:

```bash
DORMAMMU_INSTALL_ROOT=/opt/dormammu \
DORMAMMU_BIN_DIR=/opt/dormammu/bin \
PYTHON=python3.12 \
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

### Local Repository Install

```bash
./scripts/install.sh
```

That script creates or reuses `.venv`, upgrades `pip`, installs the project in
editable mode, and prints the next `doctor` and `ui` commands.

### Editable Development Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

If your system has multiple Python interpreters, use any `python3.10+`
interpreter explicitly, for example `python3.10 -m venv .venv`.

## Quick Start

```bash
dormammu doctor --repo-root .
dormammu init-state
dormammu run \
  --repo-root . \
  --prompt "Inspect the repo and implement the requested change." \
  --required-path README.md
dormammu ui
```

Then open `http://127.0.0.1:8000/` to watch progress in the local UI.

## Core Commands

```bash
dormammu run --prompt "Do the work"
dormammu resume --session-id saved-session-id
dormammu start-session --goal "New workflow scope"
dormammu sessions
dormammu restore-session --session-id saved-session-id
dormammu inspect-cli
dormammu ui
dormammu doctor
```

Command notes:

- `run` executes a supervised retry loop. Use `--max-retries -1` for infinite
  repetition.
- `resume` restores the saved session when `--session-id` is provided, then
  continues the standard recovery flow.
- `inspect-cli` reports prompt handling mode, matched presets, and risky
  approval-skipping candidates before you run real work.
- `ui` starts the optional local web app without changing the terminal-first
  architecture.
- Low-level compatibility commands such as `run-once`, `run-loop`,
  `resume-loop`, and `serve` remain available.

## Fallback CLI Config

When the primary coding-agent CLI hits token or quota exhaustion, `dormammu`
can fail over to additional CLIs from `~/.dormammu/config` or a repo-local
`dormammu.json`.

Without an explicit config, the built-in fallback order is:

- `codex`
- `claude`
- `gemini`

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

Behavior notes:

- the CLI passed to `dormammu run --agent-cli ...` is always tried first
- fallback CLIs are tried in order only when output matches a configured token
  exhaustion pattern
- fallback attempts do not consume supervised loop retry budget
- if every configured CLI is exhausted, the loop stops in a `blocked` state so
  you can wait for quota recovery or update the config before `resume`
- `active_agent_cli` provides the default backend for `run`, `run-once`,
  `inspect-cli`, and `doctor` when `--agent-cli` is omitted
- `cli_overrides` lets you attach CLI-family defaults such as the `cline`
  `-y` flag, while still allowing later manual edits
- the built-in `cline` preset treats the prompt as a positional argument, so a
  typical invocation becomes `cline -y "Inspect the repo"`

## Architecture At A Glance

```text
backend/     Python package, loop engine, adapters, supervisor, API
frontend/    Lightweight local UI assets
templates/   Bootstrap templates for .dev state
docs/svg/    Brand assets, including the project logo
scripts/     Install and developer convenience scripts
tests/       Runtime and workflow validation
```

## Release Packaging

`.github/workflows/release.yml` builds wheel and sdist artifacts on `v*` tag
pushes and on manual workflow dispatch. Release runs attach `dist/*` plus the
root `install.sh` to the GitHub release.

## License

`dormammu` is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
