<p align="center">
  <img src="docs/svg/dormammu.svg" alt="DORMAMMU logo" width="180">
</p>

<h1 align="center">DORMAMMU</h1>

<p align="center">
  <strong>A supervised, resumable loop orchestrator for coding agents.</strong>
</p>

<p align="center">
  <a href="https://github.com/hjhun/dormammu/blob/main/LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/license-Apache%202.0-blue.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg"></a>
  <img alt="Version" src="https://img.shields.io/badge/version-0.4.0-green.svg">
</p>

<p align="center">
  <a href="docs/GUIDE.md">Full Guide</a> ·
  <a href="docs/ko/GUIDE.md">한국어 가이드</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#quick-start">Quick Start</a>
</p>

---

`dormammu` wraps any external coding-agent CLI — `codex`, `claude`, `gemini`,
`cline`, `aider`, or your own — in a loop that validates the result, generates
continuation context, retries on failure, and stores everything under `.dev/`
so work can be resumed at any point.

## Why DORMAMMU

Coding agents are powerful, but a single agent invocation is fragile:

- The run may be interrupted
- The result may be incomplete or wrong
- You may not know which step failed or why

DORMAMMU solves this by adding a **supervisor** layer and a **state machine**
around the agent call. Every run is logged, validated, and resumable. The
`.dev/` directory becomes your control surface — readable by humans and
automation alike.

## Highlights

| Feature | Description |
|---------|-------------|
| **Supervised retry loops** | The supervisor validates each agent result and generates continuation context for the next attempt |
| **Resumable execution** | Prompts, logs, session metadata, and machine state are persisted under `.dev/` — resume after any interruption |
| **Multi-CLI adapter** | Drive `codex`, `claude`, `gemini`, `cline`, and `aider` through a unified runtime with preset-aware command building |
| **Role-based pipeline** | Route goals through a `developer → tester → reviewer → committer` pipeline with automated feedback loops |
| **Daemonize mode** | Watch a prompt directory, queue incoming files in deterministic order, and run each through the supervised loop |
| **Goals automation** | Schedule periodic goals that are automatically promoted into the daemon queue; manageable via Telegram |
| **Fallback CLIs** | Automatically switch to a backup agent CLI when the primary hits quota or token exhaustion |
| **Guidance injection** | Embed repository guidance (`AGENTS.md`, custom `--guidance-file`) into every agent prompt |
| **Operator-visible state** | `DASHBOARD.md`, `PLAN.md`, and `workflow_state.json` keep progress visible at a glance |
| **Session management** | Start named sessions, list saved snapshots, and restore older sessions at any time |
| **Environment diagnostics** | `doctor` checks Python, CLI availability, repository writability, and workspace structure |

## Supported Agent CLIs

DORMAMMU ships preset-aware adapters for:

| CLI | Prompt style | Workdir | Auto-approval |
|-----|-------------|---------|---------------|
| `codex` | exec + positional | — | `--dangerously-bypass-approvals-and-sandbox` |
| `claude` | print-mode | — | `--dangerously-skip-permissions` |
| `gemini` | prompt flag | `--include-directories` | `--approval-mode yolo` |
| `cline` | positional + `-y` | `--cwd` | `-y` |
| `aider` | `--message` flag | — | `--yes` |

Any other CLI can be used with `--extra-arg` pass-through.

## Architecture Overview

```
dormammu run / daemonize
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │               Supervisor Loop               │
  │                                             │
  │  ┌──────────┐   ┌──────────┐  ┌─────────┐  │
  │  │  Agent   │──▶│Validator │─▶│Continua-│  │
  │  │  CLI     │   │(required │  │tion Gen │  │
  │  │ Adapter  │   │ paths,   │  │         │  │
  │  └──────────┘   │ worktree │  └────┬────┘  │
  │                 │ changes) │       │retry  │
  │                 └──────────┘       ▼       │
  │                              ┌──────────┐  │
  │                              │ .dev/ state│ │
  │                              │ DASHBOARD │  │
  │                              │ PLAN.md   │  │
  │                              │ logs/     │  │
  │                              └──────────┘  │
  └─────────────────────────────────────────────┘
```

For `daemonize` with role-based pipeline enabled:

```
goal file ──▶ developer ──▶ tester ──▶ reviewer ──▶ committer
                  ▲              │           │
                  └──── FAIL ────┘           │
                  ▲                          │
                  └──────── NEEDS_WORK ──────┘
```

## Installation

### Quick Install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

### From a Local Clone

```bash
./scripts/install.sh
```

### Editable Development Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Requires Python `3.10+`.

## Quick Start

### 1. Check your environment

```bash
dormammu doctor --repo-root . --agent-cli codex
```

### 2. Initialize `.dev` state

```bash
dormammu init-state \
  --repo-root . \
  --goal "Implement the requested repository change safely."
```

`init-state` also probes for installed coding-agent CLIs and sets
`active_agent_cli` to the highest-priority available command:
`codex` › `claude` › `gemini` › `cline`.

### 3. Run the supervised loop

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes \
  --max-iterations 50
```

### 4. Resume after interruption

```bash
dormammu resume --repo-root .
```

### 5. Run as a background daemon

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

See [daemonize.json.example](daemonize.json.example) for a starting config.

## Commands

| Command | Description |
|---------|-------------|
| `doctor` | Verify environment — Python, CLI path, repo writability, workspace structure |
| `init-state` | Bootstrap or refresh `.dev/` state for a repository |
| `run-once` | One bounded agent call with artifact capture, no retry loop |
| `run` | Full supervised retry loop with validation and continuation |
| `resume` | Continue a previous `run` from saved loop state |
| `daemonize` | Long-running daemon that processes a prompt queue |
| `inspect-cli` | Show resolved CLI adapter details — prompt mode, flags, preset match |
| `show-config` | Print the resolved runtime config and its source path |
| `start-session` | Begin a new named session under `.dev/` |
| `sessions` | List saved session snapshots |
| `restore-session` | Restore an older session into the active `.dev/` view |

Full reference: `dormammu --help` or `dormammu <command> --help`.

## Configuration

### Runtime config (`dormammu.json`)

Resolved in this order:

1. `DORMAMMU_CONFIG_PATH` env variable
2. `<repo-root>/dormammu.json`
3. `~/.dormammu/config`

```json
{
  "active_agent_cli": "/home/you/.local/bin/codex",
  "fallback_agent_clis": [
    "claude",
    { "path": "aider", "extra_args": ["--yes"] }
  ],
  "cli_overrides": {
    "cline": { "extra_args": ["-y", "--verbose", "--timeout", "1200"] }
  },
  "token_exhaustion_patterns": [
    "usage limit", "quota exceeded", "rate limit exceeded"
  ],
  "agents": {
    "developer":  { "cli": "claude", "model": "claude-opus-4-6" },
    "tester":     { "cli": "claude", "model": "claude-sonnet-4-6" },
    "reviewer":   { "cli": "claude", "model": "claude-sonnet-4-6" },
    "committer":  { "cli": "claude" }
  }
}
```

When `agents` is configured, `daemonize` uses the role-based pipeline
(`developer → tester → reviewer → committer`) instead of the default loop.

### Daemon queue config (`daemonize.json`)

Separate from `dormammu.json`. Controls prompt watching and queue behavior.

```json
{
  "schema_version": 1,
  "prompt_path": "./queue/prompts",
  "result_path": "./queue/results",
  "watch": { "poll_interval_seconds": 60, "settle_seconds": 0 },
  "queue": { "allowed_extensions": [".md", ".txt"] },
  "goals": { "path": "./goals", "interval_minutes": 60 }
}
```

Example files for different queue presets are included:

- [`daemonize.json.example`](daemonize.json.example) — default mixed `.md`/`.txt` watcher
- [`daemonize.named-skill.example.json`](daemonize.named-skill.example.json) — Markdown-only queue
- [`daemonize.mixed-skill-resolution.example.json`](daemonize.mixed-skill-resolution.example.json) — with file settle delay for editors that write in multiple passes
- [`daemonize.phase-specific-clis.example.json`](daemonize.phase-specific-clis.example.json) — shorter polling interval

## What Gets Written

Every run leaves behind inspectable artifacts:

| Path | Contents |
|------|----------|
| `.dev/DASHBOARD.md` | Operator-facing progress, active phase, next action, risks |
| `.dev/PLAN.md` | Prompt-derived task checklist (`[ ]` / `[O]` phase items) |
| `.dev/workflow_state.json` | Machine-readable workflow state (source of truth) |
| `.dev/session.json` | Active session metadata |
| `.dev/logs/` | Prompt, stdout, stderr, and run metadata artifacts |
| `DORMAMMU.log` | Project-level execution log (written with `--debug`) |

## Common Patterns

### Use repository guidance automatically

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt "Follow AGENTS.md and implement the requested change."
```

Guidance resolution order: `--guidance-file` flags › `AGENTS.md` / `agents/AGENTS.md` ›
`~/.dormammu/agents` › packaged fallback assets.

### Run in a subproject directory

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli cline \
  --workdir ./subproject \
  --prompt "Inspect this subproject and report the failing test surface."
```

### Pass extra flags to the agent CLI

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli gemini \
  --prompt "Summarize the repo." \
  --extra-arg=--approval-mode \
  --extra-arg=auto_edit
```

### Use an environment-specific config

```bash
DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json \
  dormammu daemonize --repo-root . --config ./ops/daemonize.prod.json
```

## Repository Layout

```text
backend/     Python package — loop engine, CLI adapters, state, supervisor, daemon
agents/      Distributable workflow and skill guidance bundle
templates/   Bootstrap templates for .dev/ state files
docs/        User and operator documentation
scripts/     Install and developer convenience scripts
tests/       Runtime, adapter, and workflow validation
```

## Release

`v*` tag pushes and manual workflow dispatches build wheel and sdist artifacts
via `.github/workflows/release.yml`. The packaged build includes the guidance
bundle used for installed fallback behavior.

## License

DORMAMMU is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE).
