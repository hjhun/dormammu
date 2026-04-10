<p align="center">
  <img src="docs/svg/dormammu.svg" alt="DORMAMMU logo" width="180">
</p>

# DORMAMMU: CLI Workflow Loop Engine

`dormammu` is a CLI-first workflow loop engine for coding agents. It runs an
external agent CLI, records machine and human-readable state under `.dev/`,
lets a supervisor validate outcomes, and resumes safely after interruption.
The supported runtime target is Python `3.10+`.

Start with the full project guide at [docs/GUIDE.md](docs/GUIDE.md).

## Why DORMAMMU

- CLI-only runtime: the product surface is Python modules and terminal
  entrypoints only.
- Resumable by default: execution state, operator notes, prompts, and logs are
  written to `.dev/` so interrupted runs can continue instead of restarting.
- Supervisor-driven validation: required paths, worktree changes, and follow-up
  continuation prompts are handled as part of the loop.
- Operator-visible state: `DASHBOARD.md`, `PLAN.md`, and `PROMPT.md` remain
  readable for humans while JSON state stays available for tooling and
  automation.
- Fallback agent CLIs: configure failover when the primary coding agent hits a
  token or quota wall.

## Install

### User Install

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

### Local Repository Install

```bash
./scripts/install.sh
```

### Editable Development Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Quick Start

```bash
dormammu doctor --repo-root .
dormammu init-state
dormammu run \
  --repo-root . \
  --prompt-file PROMPT.md \
  --required-path README.md
```

## Core Commands

```bash
dormammu run --prompt "Do the work"
dormammu resume --session-id saved-session-id
dormammu start-session --goal "New workflow scope"
dormammu sessions
dormammu restore-session --session-id saved-session-id
dormammu inspect-cli
dormammu doctor
```

Command notes:

- `run` executes a supervised retry loop. Use `--max-retries -1` for infinite
  repetition.
- `resume` restores the saved session when `--session-id` is provided, then
  continues the standard recovery flow.
- `inspect-cli` reports prompt handling mode, matched presets, and risky
  approval-skipping candidates before you run real work.
- `--guidance-file path/to/file.md` can be repeated on `show-config`,
  `init-state`, `start-session`, `run`, `run-once`, and `resume` to point the
  run at custom rule or agent Markdown files.
- If no custom guidance file with content is supplied, `dormammu` falls back to
  repository guidance such as `AGENTS.md` or `agents/AGENTS.md`, then to the
  installed guidance bundle under `~/.dormammu/agents`, then to packaged
  guidance assets.
- Low-level compatibility commands such as `run-once`, `run-loop`, and
  `resume-loop` remain available.

## Fallback CLI Config

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
      "extra_args": ["-y", "--verbose"]
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

## Architecture At A Glance

```text
backend/     Python package, loop engine, adapters, supervisor
agents/      Distributable workflow and skill guidance bundle
templates/   Bootstrap templates for .dev state
docs/svg/    Brand assets, including the project logo
scripts/     Install and developer convenience scripts
tests/       Runtime and workflow validation
```

## Release Packaging

`.github/workflows/release.yml` builds wheel and sdist artifacts on `v*` tag
pushes and on manual workflow dispatch. The distributable `agents/` guidance
bundle is included alongside the packaged Python assets so workflow documents
ship with dormammu. Release runs attach `dist/*` plus the root `install.sh` to
the GitHub release.

The default install flow also copies the guidance bundle to
`~/.dormammu/agents` so installed runs can fall back to it when a repository
does not provide its own guidance files.

## License

`dormammu` is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
