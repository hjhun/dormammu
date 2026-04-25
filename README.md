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
  <a href="#installation">Installation</a> ·
  <a href="#quick-start">Quick Start</a>
</p>

---

`dormammu` wraps any external coding-agent CLI — `codex`, `claude`, `gemini`,
`cline`, or your own — in a supervisor-driven loop that validates results,
generates continuation context, retries on failure, and stores everything under
`.dev/` so work can be resumed at any point.

By default, runtime-authored state is projected into a workspace shadow under
`~/.dormammu/` instead of cluttering the repository working tree. For a project
at `~/samba/github/dormammu`, the workspace project root becomes
`~/.dormammu/workspace/samba/github/dormammu`, the operational `.dev/` root is
`~/.dormammu/workspace/samba/github/dormammu/.dev`, managed temp artifacts live
in `~/.dormammu/workspace/samba/github/dormammu/.tmp`, and daemon result
reports are written under `~/.dormammu/results/`.

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
| **Multi-CLI adapter** | Drive `codex`, `claude`, `gemini`, and `cline` through a unified runtime with preset-aware command building |
| **Refine & Plan stages** | A refining agent converts raw goals into `REQUIREMENTS.md`; a planning agent generates an adaptive `WORKFLOWS.md` checklist |
| **Role-based pipeline** | Route goals through `refiner → planner → developer → tester → reviewer → committer` with automated feedback loops |
| **Goals analysis experts** | Use `analyzer → planner → designer` to turn scheduled goals into stronger execution prompts before the normal runtime pipeline starts |
| **Daemonize mode** | Watch a prompt directory, queue incoming files in deterministic order, and run each through the supervised pipeline |
| **Goals automation** | Schedule periodic goals that are automatically promoted into the daemon queue; manageable via Telegram |
| **Fallback CLIs** | Automatically switch to a backup agent CLI when the primary hits quota or token exhaustion |
| **Guidance injection** | Embed repository guidance (`AGENTS.md`, custom `--guidance-file`) into every agent prompt |
| **Operator-visible state** | `DASHBOARD.md`, `PLAN.md`, `TASKS.md`, `WORKFLOWS.md`, and `workflow_state.json` keep progress visible at a glance |
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

Any other CLI can be used with `--extra-arg` pass-through.

## How It Works

### Interactive Shell

Running `dormammu` with no subcommand starts the default interactive shell. You
can also start it explicitly with `dormammu shell`.

- Upper area: logs, summaries, daemon status output
- Lower prompt: free-text requests and slash commands
- Free-text input: shorthand for a supervised `run`
- Slash commands: `/config`, `/run`, `/run-once`, `/resume`, `/sessions`,
  `/show-config`, `/daemon ...`, `/exit`

`daemonize` remains a worker-oriented queue processor. The interactive shell is
its operator control plane through `/daemon start`, `/daemon stop`,
`/daemon status`, `/daemon logs`, `/daemon enqueue <prompt>`, and
`/daemon queue`.

### Run Modes

DORMAMMU has four operator entry styles:

| Mode | Command | Description |
|------|---------|-------------|
| **interactive shell** | `dormammu` or `dormammu shell` | Default terminal shell with top log output, bottom input, and slash commands |
| **run-once** | `dormammu run-once` | One bounded agent call with artifact capture, no retry |
| **run** | `dormammu run` | Full supervised retry loop with validation and continuation |
| **daemonize** | `dormammu daemonize` | Long-running daemon that watches a prompt queue |

Every execution mode now begins with a mandatory `refine -> plan` prelude.
The post-plan evaluator is not part of normal `run` or `run-once` execution.
It is enabled only for goals-scheduler prompts, where evaluator output is used
to gate scheduled-goal progression. After the prelude:

- when `agents` is configured, DORMAMMU continues through the full
  **PipelineRunner**
- when `agents` is absent, `run` and `daemonize` continue through the
  single-agent **LoopRunner**
- when `agents` is absent, `run-once` continues through a single bounded
  **CliAdapter** call

### Single-Agent Loop

Without `agents` config, the runtime still starts with `refine -> plan`, then
the supervised loop works like this:

```mermaid
flowchart TD
    you([You]) --> cmd["dormammu run"]
    cmd --> adapter[CLI Adapter]
    adapter --> agent["Agent CLI<br/>codex · claude · gemini · cline"]
    agent --> validator["Supervisor Validator<br/>required paths · worktree changes · output"]
    validator -- pass --> done([Done])
    validator -- fail --> cont[Continuation Context Generator]
    cont --> state[".dev/ State<br/>DASHBOARD · PLAN · logs"]
    state --> adapter
```

### Role-Based Pipeline

When `agents` is configured, goals flow through a full multi-role pipeline:

```mermaid
flowchart TD
    prompt([Prompt / Goal]) --> refiner["Refiner (mandatory)<br/>writes REQUIREMENTS.md"]
    refiner --> planner["Planner (mandatory)<br/>writes WORKFLOWS.md"]
    planner --> developer[Developer]
    developer --> tester[Tester]
    tester -- "OVERALL: FAIL" --> developer
    tester -- "OVERALL: PASS" --> reviewer[Reviewer]
    reviewer -- "VERDICT: NEEDS_WORK" --> developer
    reviewer -- "VERDICT: APPROVED" --> committer[Committer]
    committer --> done([Done])
    planner -. "goals-scheduler prompts only" .-> planeval["Plan Evaluator"]
    planeval -- "DECISION: REWORK" --> planner
    planeval -- "DECISION: PROCEED" --> developer
```

The runtime role contract distinguishes mandatory runtime roles, goals-only
roles, and autonomous-only roles.

**Refiner** (mandatory): Converts the raw goal into a structured
`.dev/REQUIREMENTS.md` — clarifying scope, acceptance criteria, constraints,
and risks — before any code is written. It uses `agents.refiner.cli` when
configured and otherwise falls back to `active_agent_cli`.

**Planner** (mandatory): Reads `REQUIREMENTS.md` and produces `.dev/WORKFLOWS.md`,
an adaptive, task-specific stage checklist (`[ ] Phase N. Role — agent`).
Also updates `PLAN.md`, `TASKS.md`, and `DASHBOARD.md`. It uses `agents.planner.cli` when
configured and otherwise falls back to `active_agent_cli`.

**Plan Evaluator** (goals-scheduler prompts only): Runs after planning for
scheduled goals. It can return `DECISION: PROCEED` or `DECISION: REWORK`,
causing the planner to re-enter before development starts. Interactive
`run` and `run-once` commands skip this evaluator stage.

**Developer**: Implements the active scope, guided by `REQUIREMENTS.md` and
`WORKFLOWS.md` when available.

**Tester**: Black-box validation — appends `OVERALL: PASS` or `OVERALL: FAIL`
as its last output line. A `FAIL` routes the developer back with the report.

**Reviewer**: Code review against the goal and any design document.
Appends `VERDICT: APPROVED` or `VERDICT: NEEDS_WORK`. After the configured
iteration-max round-trips, unresolved review/test loops stop with
`manual_review_needed` instead of silently advancing.

**Committer**: Stages only the active scope and produces an intentional git
commit after the reviewer approves.

### Guidance Framework

DORMAMMU ships a bundled guidance framework (`agents/`) that routes multi-phase
work through specialized agent roles. The Supervising Agent controls all phase
transitions.

```mermaid
flowchart TD
    Start([New Scope]) --> prd["PRD Agent (optional)<br/>writes user stories / PRD"]
    prd --> refine[Refining Agent]
    Start -. skip PRD .-> refine
    refine --> plan[Planning Agent]
    plan --> design[Designing Agent]
    design --> develop[Developing Agent]
    design --> testauth[Test Authoring Agent]
    develop --> build[Building & Deploying Agent]
    testauth --> build
    build --> review[Testing & Reviewing Agent]
    review -- "fail / needs rework" --> develop
    review -- pass --> finalverify["Final Verification<br/>Supervising Agent"]
    finalverify -- fail --> develop
    finalverify -- pass --> commit[Committing Agent]
    commit --> Done([Done])

    supervisor[Supervising Agent] -. orchestrates .-> plan
    supervisor -. orchestrates .-> design
    supervisor -. orchestrates .-> develop
    supervisor -. orchestrates .-> testauth
    supervisor -. orchestrates .-> build
    supervisor -. orchestrates .-> review
    supervisor -. orchestrates .-> commit
```

**PRD Agent** (optional): Converts a rough feature idea into a structured PRD
with user stories sized for a single agent session. Invoke before refinement
when scope is unclear. Hands off to the Planning Agent once finalized.

The `agents/` bundle also ships five pre-composed **workflows** that group
related skills into common entry patterns:

| Workflow | Purpose |
|----------|---------|
| `refine-plan.md` | Refine requirements and generate an adaptive WORKFLOWS.md |
| `develop-test-authoring.md` | Parallel development and test authoring track |
| `build-deploy-test-review.md` | Build, deploy, validate, and review |
| `cleanup-commit.md` | Final cleanup and commit after validation passes |
| `supervised-downstream.md` | Continue downstream execution under supervisor contract after `refine → plan` has already completed |

Runtime skill discovery is a separate subsystem from guidance-file injection.
`AGENTS.md` remains repository guidance, `agents/workflows/*.md` define stage
flows, and `agents/skills/*/SKILL.md` are runtime skill documents discovered
from project, user, and built-in scopes and then filtered per effective agent
profile.

See [docs/GUIDE.md](docs/GUIDE.md) for a full description of each agent role.

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

### 4. Use the interactive shell

```bash
dormammu
```

Common shell commands:

```text
/config get active_agent_cli
/run Implement the next task in PLAN.md
/daemon status
/daemon enqueue Review the latest queued change
/exit
```

### 5. Resume after interruption

```bash
dormammu resume --repo-root .
```

### 6. Run as a background daemon

```bash
dormammu daemonize --repo-root .
```

By default this reads `~/.dormammu/daemonize.json`. Use `--config daemonize.json`
to override it. See [config/daemonize.json.example](config/daemonize.json.example)
for a starting config.

## Commands

### All Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `doctor` | — | Verify environment — Python version, CLI path, repo writability, workspace structure |
| `init-state` | — | Bootstrap or refresh `.dev/` state for a repository |
| `show-config` | — | Print the resolved runtime config and its source path |
| `set-config` | — | Set or modify a config value in `dormammu.json` or `~/.dormammu/config` |
| `inspect-cli` | — | Show resolved CLI adapter details — prompt mode, flags, preset match |
| `run-once` | — | One bounded agent call with artifact capture, no retry loop |
| `run` | `run-loop` | Full supervised retry loop with validation and continuation |
| `resume` | `resume-loop` | Continue a previous `run` from saved loop state |
| `shell` | — | Start the interactive shell explicitly |
| `daemonize` | — | Long-running daemon that watches a prompt directory and processes a queue |
| `start-session` | — | Archive the current session and begin a new named session |
| `sessions` | — | List all saved session snapshots |
| `restore-session` | — | Restore an older session into the active `.dev/` view |

Full reference: `dormammu --help` or `dormammu <command> --help`.

### Interactive Shell Commands

| Command | Description |
|---------|-------------|
| free text | Submit a supervised `/run` request |
| `/run <prompt>` | Run the supervised loop explicitly |
| `/run-once <prompt>` | Run one bounded execution |
| `/resume` | Resume the last interrupted run |
| `/show-config` | Print the resolved runtime config |
| `/config ...` | Get or mutate supported config keys |
| `/sessions` | List sessions |
| `/daemon start` | Start the daemon worker in the background |
| `/daemon stop` | Request graceful daemon shutdown |
| `/daemon status` | Show daemon pid, heartbeat, queue depth, and paths |
| `/daemon logs` | Show the latest daemon log tail |
| `/daemon enqueue <prompt>` | Queue a prompt file for daemon processing |
| `/daemon queue` | List queued prompt files |
| `/exit` | Leave the interactive shell |

### `run` Options

| Option | Default | Description |
|--------|---------|-------------|
| `--repo-root` | `.` | Repository root directory |
| `--agent-cli` | from config | Agent CLI to use (overrides `active_agent_cli`; bypasses PipelineRunner) |
| `--prompt` | — | Inline prompt text (mutually exclusive with `--prompt-file`) |
| `--prompt-file` | — | Path to a prompt file (mutually exclusive with `--prompt`) |
| `--input-mode` | `auto` | How the prompt is passed: `auto` `file` `arg` `stdin` `positional` |
| `--max-iterations` | `50` | Total attempt budget (`-1` for infinite) |
| `--max-retries` | — | Retry budget (alternative to `--max-iterations`) |
| `--required-path` | — | File that must exist after the run (repeatable) |
| `--require-worktree-changes` | off | Fail validation if the worktree has no changes |
| `--workdir` | — | Working directory for the agent process |
| `--guidance-file` | — | Additional guidance files to embed in the prompt (repeatable) |
| `--extra-arg` | — | Pass-through flags to the agent CLI (repeatable) |
| `--run-label` | — | Human-readable label for this run (appears in logs) |
| `--session-id` | — | Attach run to a specific session |
| `--prompt-flag` | — | Override the flag used to pass the prompt to the CLI |
| `--debug` | off | Write `DORMAMMU.log` at the repository root |

> **Note:** When `--agent-cli` is explicitly provided, DORMAMMU still runs the
> mandatory `refine -> plan` prelude first, then uses the single-agent runtime
> path for that invocation. This lets you bypass specialist downstream roles
> without skipping the planning contract.

### `set-config` Options

| Option | Description |
|--------|-------------|
| `key` | Config key to set (e.g. `active_agent_cli`) |
| `value` | Value to assign |
| `--add` | Append value to a list field |
| `--remove` | Remove value from a list field |
| `--unset` | Remove the key entirely |
| `--global` | Write to `~/.dormammu/config` instead of project-level `dormammu.json` |

### `daemonize` Options

| Option | Description |
|--------|-------------|
| `--repo-root` | Repository root directory |
| `--config` | Path to the daemon queue config file. Defaults to `~/.dormammu/daemonize.json` |
| `--guidance-file` | Additional guidance files (repeatable) |
| `--debug` | Write per-prompt progress logs under `result_path/../progress/` |

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
    "gemini"
  ],
  "cli_overrides": {
    "cline": { "extra_args": ["-y", "--timeout", "1200"] }
  },
  "token_exhaustion_patterns": [
    "usage limit", "quota exceeded", "rate limit exceeded"
  ],
  "agents": {
    "refiner":   { "cli": "claude", "model": "claude-sonnet-4-6" },
    "analyzer":  { "cli": "claude", "model": "claude-sonnet-4-6" },
    "planner":   { "cli": "claude", "model": "claude-sonnet-4-6" },
    "designer": { "cli": "claude", "model": "claude-sonnet-4-6" },
    "developer": { "cli": "claude", "model": "claude-opus-4-6" },
    "tester":    { "cli": "claude", "model": "claude-sonnet-4-6" },
    "reviewer":  { "cli": "claude", "model": "claude-sonnet-4-6" },
    "committer": { "cli": "claude" },
    "evaluator": { "cli": "claude", "model": "claude-sonnet-4-6" }
  }
}
```

When `agents` is configured, all run modes (`run`, `run-once`, `daemonize`)
use the role-based pipeline. Providing `--agent-cli` on the command line reverts
to the single-agent downstream path for that invocation after the mandatory
`refine -> plan` prelude completes.

`analyzer` is goals/autonomous-only. Goals automation may use
`analyzer -> planner -> designer` to turn a scheduled goal into a stronger
execution prompt before runtime starts. The runtime pipeline still begins with
mandatory `refiner -> planner`; `designer` is not an interactive runtime stage,
though reviewer prompts can read a goals-generated designer document when one
exists. `evaluator` is mandatory for goals-scheduler prompts (plan checkpoint
and post-commit review) and is skipped for interactive `run` and `run-once`
commands. `architect` is not a supported role alias; use `designer`.

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

`result_path` remains a required daemon config field for compatibility and
validation, but runtime-authored result reports are written under
`~/.dormammu/results/`.

Example configs under `config/`:

| File | Use when |
|------|----------|
| `daemonize.json.example` | Default — mixed `.md` and `.txt` prompt queue |
| `daemonize.named-skill.example.json` | Markdown-only queue |
| `daemonize.mixed-skill-resolution.example.json` | Editor writes files in multiple passes; add settle delay |
| `daemonize.phase-specific-clis.example.json` | Shorter polling interval for faster scan cadence |

## What Gets Written

Runtime paths are separated from source-editing paths:

- Real project root: the repository being edited
- Workspace project root: `~/.dormammu/workspace/<home-relative-project-path>`
- Operational state root: `<workspace project root>/.dev`
- Managed temp root: `<workspace project root>/.tmp`
- Result reports: `~/.dormammu/results/`

If the repository is outside `HOME`, DORMAMMU uses a deterministic fallback
mapping under `~/.dormammu/workspace/_external/<safe-name>-<hash>/`.

Every run leaves behind inspectable artifacts:

| Path | Contents |
|------|----------|
| `.dev/REQUIREMENTS.md` | Structured requirements produced by the refining agent |
| `.dev/WORKFLOWS.md` | Adaptive stage checklist produced by the planning agent |
| `.dev/DASHBOARD.md` | Operator-facing progress, active phase, next action, risks |
| `.dev/PLAN.md` | Prompt-derived task checklist (`[ ]` / `[O]` phase items) |
| `.dev/TASKS.md` | Prompt-derived development queue used for task sync and resume targeting |
| `.dev/workflow_state.json` | Machine-readable workflow state (source of truth) |
| `.dev/session.json` | Active session metadata |
| `.dev/logs/` | Prompt, stdout, stderr, run metadata, and all stage output documents (analyzer, designer, tester, reviewer, committer, evaluator) |
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
config/      Example configuration files
docs/        User and operator documentation
scripts/     Install and developer convenience scripts
tests/       Runtime, adapter, and workflow validation
```

## Development Baseline

Before starting roadmap refactors, run the quick baseline:

```bash
scripts/verify-baseline.sh quick
```

Before handing off a completed phase, run the full baseline:

```bash
scripts/verify-baseline.sh full
```

Keep the quick and full baseline commands as the release gate for roadmap
refactors.

## Release

`v*` tag pushes and manual workflow dispatches build wheel and sdist artifacts
via `.github/workflows/release.yml`. The packaged build includes the guidance
bundle used for installed fallback behavior.

## License

DORMAMMU is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE).
