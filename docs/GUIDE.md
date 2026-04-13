# DORMAMMU — Full Guide

`dormammu` is a CLI-first loop orchestrator for coding agents. It wraps an
external agent CLI with a supervisor, resumable state management, and
operator-visible artifacts — so agent runs are repeatable, inspectable, and
safe to continue after any interruption.

For a quick overview read the main [README.md](../README.md) first. The
Korean-language guide is at [docs/ko/GUIDE.md](ko/GUIDE.md).

---

## Table of Contents

- [What DORMAMMU Does](#what-dormammu-does)
- [Core Concepts](#core-concepts)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands Reference](#commands-reference)
- [Configuration Reference](#configuration-reference)
- [Agent Roles](#agent-roles)
- [Workflow Pipeline](#workflow-pipeline)
- [Daemonize Mode](#daemonize-mode)
- [Role-Based Agent Pipeline](#role-based-agent-pipeline)
- [Goals Automation](#goals-automation)
- [Guidance Files](#guidance-files)
- [The `.dev` Directory](#the-dev-directory)
- [Session Management](#session-management)
- [Fallback Agent CLIs](#fallback-agent-clis)
- [Working Directory and CLI Overrides](#working-directory-and-cli-overrides)
- [Typical Operator Flow](#typical-operator-flow)
- [Repository Layout](#repository-layout)

---

## What DORMAMMU Does

Without DORMAMMU, running a coding agent looks like:

```mermaid
flowchart LR
    you([You]) --> agent[Agent CLI]
    agent --> hope["(hope it works)"]
```

With DORMAMMU:

```mermaid
flowchart TD
    you([You]) --> cmd["dormammu run"]
    cmd --> adapter[CLI Adapter]
    adapter --> agent["Agent CLI"]
    agent --> validator["Supervisor Validator\nrequired paths · worktree · output"]
    validator -- pass --> done([Done])
    validator -- fail --> cont[Continuation Context Generator]
    cont --> state[".dev/ State\nDASHBOARD · PLAN · logs"]
    state --> adapter
```

The supervisor checks:

- Did required files change?
- Did the worktree change?
- Did the agent produce a meaningful result?

If not, DORMAMMU generates continuation context and retries — up to your
configured limit. When the supervisor approves the work, the loop exits
immediately.

Everything the agent sees and produces is logged under `.dev/` for later
inspection or resumption.

---

## Core Concepts

### Supervised loop

`dormammu run` wraps an agent call in a retry loop. After each attempt, the
supervisor evaluates the result. On failure, it constructs a continuation
prompt with the previous output and submits another attempt.

### Resumable state

All workflow state — prompts, logs, session metadata, machine state — is
persisted under `.dev/`. If the process is interrupted, `dormammu resume`
picks up from the last saved state instead of starting over.

### CLI adapter

DORMAMMU translates its internal representation of a run request into the
correct invocation for the target CLI. Preset-aware adapters handle prompt
style, command prefix, workdir flags, and auto-approval arguments for each
known CLI.

### Role-based pipeline

When `agents` is configured in `dormammu.json`, the daemon routes each goal
through a `developer → tester → reviewer → committer` pipeline with automated
feedback loops between stages.

---

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

Requires Python `3.10+`. See [docs/ko/UBUNTU_PYTHON_310_PLUS.md](ko/UBUNTU_PYTHON_310_PLUS.md)
for Ubuntu setup notes.

---

## Quick Start

### 1. Verify the environment

```bash
dormammu doctor --repo-root . --agent-cli codex
```

Checks Python version, agent CLI availability, workspace directory presence,
and repository write access.

### 2. Initialize `.dev` state

```bash
dormammu init-state \
  --repo-root . \
  --goal "Implement the requested repository task."
```

Creates or refreshes:

- `.dev/DASHBOARD.md`
- `.dev/PLAN.md`
- `.dev/session.json`
- `.dev/workflow_state.json`

Also probes for installed coding-agent CLIs and sets `active_agent_cli` to the
highest-priority available command: `codex` › `claude` › `gemini` › `cline`.

### 3. Confirm which config file is loaded

```bash
dormammu show-config --repo-root .
```

Prints the resolved config as JSON, including which file was loaded
(`dormammu.json`, `DORMAMMU_CONFIG_PATH`, or `~/.dormammu/config`).

### 4. Inspect the CLI adapter

```bash
dormammu inspect-cli --repo-root . --agent-cli cline
```

Shows the resolved prompt mode, preset match, command prefix, workdir flag
support, and approval-related hints — useful before a real run.

### 5. Run one agent call

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli codex \
  --prompt "Read the repo guidance and summarize the next implementation step."
```

`run-once` executes a single bounded agent invocation with artifact capture
but without a supervised retry loop.

### 6. Run the supervised loop

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes \
  --max-iterations 50
```

The loop runs until the supervisor approves or the iteration limit is reached.
Default limit is `50` when neither `--max-iterations` nor `--max-retries` is
set.

### 7. Resume later

```bash
dormammu resume --repo-root .
```

Reloads the saved loop state and continuation context, then restarts from the
recovery path.

---

## Commands Reference

### `dormammu doctor`

Environment diagnostics. Checks:

- Python version (≥ 3.10)
- Agent CLI path and availability
- `.agent` or `.agents` workspace directory presence
- Repository root write access

```bash
dormammu doctor --repo-root . --agent-cli codex
```

### `dormammu init-state`

Bootstrap or refresh `.dev/` state. Use before the first run in any
repository, or to reset state after a goal change.

```bash
dormammu init-state \
  --repo-root . \
  --goal "Ship the requested change safely."
```

### `dormammu show-config`

Print the resolved runtime config and its source file.

```bash
dormammu show-config --repo-root .
```

### `dormammu set-config`

Set or modify a config value. Supports scalar assignment and list operations.

```bash
# Set a scalar value
dormammu set-config active_agent_cli claude

# Append to a list
dormammu set-config token_exhaustion_patterns "rate limit" --add

# Remove from a list
dormammu set-config fallback_agent_clis aider --remove

# Write to global config instead of project config
dormammu set-config active_agent_cli codex --global
```

### `dormammu inspect-cli`

Show the resolved CLI adapter details as JSON.

```bash
dormammu inspect-cli --repo-root . --agent-cli codex
```

Output includes:

- `prompt_mode`: how the prompt is passed (positional, flag, stdin)
- `preset_name`: matched known preset if any
- `command_prefix`: any prefix added before the prompt
- `workdir_flag`: the flag used to set working directory
- `approval_hints`: any auto-approval flags that will be injected

### `dormammu run-once`

Execute one agent invocation. Stores the prompt artifact, stdout, stderr, and
run metadata. Does not retry.

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli codex \
  --prompt "Summarize the repository."
```

### `dormammu run`

Execute the supervised retry loop.

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes \
  --max-iterations 50
```

Key options:

| Option | Default | Description |
|--------|---------|-------------|
| `--prompt` / `--prompt-file` | — | Inline prompt text or path to a prompt file |
| `--agent-cli` | from config | CLI to drive (overrides `active_agent_cli` in config) |
| `--input-mode` | `auto` | Prompt pass mode: `auto` `file` `arg` `stdin` `positional` |
| `--required-path` | — | File that must exist or change after the agent runs (repeatable) |
| `--require-worktree-changes` | off | Fail validation if the worktree has no changes |
| `--max-iterations` | `50` | Total attempt budget (`-1` for infinite) |
| `--max-retries` | — | Retry budget (alternative to `--max-iterations`) |
| `--workdir` | — | Working directory for the agent process |
| `--guidance-file` | — | Additional guidance files to embed in the prompt (repeatable) |
| `--extra-arg` | — | Pass-through flags to the agent CLI (repeatable) |
| `--run-label` | — | Human-readable label for this run (appears in logs) |
| `--debug` | off | Write `DORMAMMU.log` at the repository root |

### `dormammu resume`

Reload saved state and continue the previous run.

```bash
dormammu resume --repo-root .
```

### `dormammu daemonize`

Long-running daemon that watches a prompt directory and processes files
through the supervised loop one at a time.

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

See [Daemonize Mode](#daemonize-mode) for the full config reference.

---

## Configuration Reference

### Runtime config (`dormammu.json`)

Resolved in this order:

1. `DORMAMMU_CONFIG_PATH` environment variable
2. `<repo-root>/dormammu.json`
3. `~/.dormammu/config`

Full example:

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
      "extra_args": ["-y", "--verbose", "--timeout", "1200"]
    }
  },
  "token_exhaustion_patterns": [
    "usage limit",
    "quota exceeded",
    "rate limit exceeded",
    "token limit",
    "insufficient credits"
  ],
  "agents": {
    "developer":  { "cli": "claude", "model": "claude-opus-4-6" },
    "tester":     { "cli": "claude", "model": "claude-sonnet-4-6" },
    "reviewer":   { "cli": "claude", "model": "claude-sonnet-4-6" },
    "committer":  { "cli": "claude" }
  }
}
```

#### Fields

| Field | Description |
|-------|-------------|
| `active_agent_cli` | Primary agent CLI path or name |
| `fallback_agent_clis` | Ordered list of fallback CLIs for quota/token exhaustion |
| `cli_overrides` | Per-CLI extra arguments and settings |
| `token_exhaustion_patterns` | Patterns in agent output that trigger CLI fallback |
| `agents` | Role-based pipeline CLI and model assignments |

When `agents` is configured, `daemonize` uses the role-based pipeline instead
of the plain loop. See [Role-Based Agent Pipeline](#role-based-agent-pipeline).

### Daemon queue config (`daemonize.json`)

Separate from `dormammu.json`. Controls what the daemon watches and how it
queues prompts.

```json
{
  "schema_version": 1,
  "prompt_path": "./queue/prompts",
  "result_path": "./queue/results",
  "watch": {
    "backend": "auto",
    "poll_interval_seconds": 60,
    "settle_seconds": 0
  },
  "queue": {
    "allowed_extensions": [".md", ".txt"],
    "ignore_hidden_files": true
  },
  "goals": {
    "path": "./goals",
    "interval_minutes": 60
  }
}
```

#### Fields

| Field | Description |
|-------|-------------|
| `prompt_path` | Directory watched for incoming prompt files |
| `result_path` | Directory where result reports are written |
| `watch.poll_interval_seconds` | Seconds between directory scans (default `60`) |
| `watch.settle_seconds` | Wait time after file creation before reading (guards against partial writes) |
| `queue.allowed_extensions` | File extensions to accept (others are ignored) |
| `queue.ignore_hidden_files` | Skip dotfiles when scanning (default `true`) |
| `goals.path` | Directory containing scheduled goal files |
| `goals.interval_minutes` | How often to promote goal files into the prompt queue |

Relative paths are resolved relative to the daemon config file location, not
the current shell working directory.

---

## Agent Roles

DORMAMMU ships a bundled guidance framework under `agents/` that defines
specialized roles for each phase of development. The **Supervising Agent**
acts as the top-level controller, deciding which role acts next and when to
advance a phase transition.

### Supervising Agent

**Path:** `agents/skills/supervising-agent/SKILL.md`

The Supervising Agent is the controller for all multi-phase work. It:

- Decides which skill acts next based on the current `.dev/workflow_state.json`
- Enforces phase gates — transitions only when evidence exists (not just intent)
- Resumes safely after interruption by re-reading `.dev/` state
- Treats `.dev/workflow_state.json` as the machine truth and Markdown files as
  the operator-facing view

Phase gate rules:

| Transition | Required evidence |
|------------|------------------|
| planning → design | Tasks exist and next action is clear |
| design → develop | Active scope has interface or decision records |
| develop → test_author | Product code changes exist in intended files |
| test_author → build | Unit/integration test code exists |
| test_review → final_verify | Executed validation has clear results |
| final_verify → commit | Active slice passed final operational review |

### Planning Agent

**Path:** `agents/skills/planning-agent/SKILL.md`

Converts a goal into a concrete, outcome-focused phase plan.

- Produces 4–8 phases with clear completion signals
- Writes a phase checklist to `.dev/PLAN.md` (`[ ] Phase N. <title>`)
- Updates `.dev/DASHBOARD.md` with active phase and next action
- Used when: new scope starts, prompt needs expansion into actionable steps

### Designing Agent

**Path:** `agents/skills/designing-agent/SKILL.md`

Produces implementation-ready design decisions before broad coding begins.

- Documents module contracts, API interfaces, and schema decisions
- Records only decisions that affect implementation, recovery, testing, or deployment
- Does not write product code
- Used when: after planning, before implementation; design choices affect multiple files

### Developing Agent

**Path:** `agents/skills/developing-agent/SKILL.md`

Implements the active task slice.

- Writes product code for the current active phase only
- Keeps product-code ownership separate from test-code ownership
- Updates `.dev/` state after each meaningful change
- Each step is idempotent — safe to retry after interruption
- Used when: active phase is implementation

### Test Authoring Agent

**Path:** `agents/skills/test-authoring-agent/SKILL.md`

Writes and maintains automated tests for the active implementation slice.

- Default scope: unit tests + integration tests
- System tests only when explicitly requested
- Runs in parallel with the Developing Agent after design is complete
- Updates `.dev/` state when test code is ready
- Used when: after design, when a scope needs test coverage

### Building and Deploying Agent

**Path:** `agents/skills/building-and-deploying/SKILL.md`

Produces release artifacts and validates packaging or deployment flows.

- Runs only from current repo state — no speculative builds
- Captures build commands, output, and failures in `.dev/logs/`
- Used when: packaging is required, installation flows need validation, or
  deployment outputs need to be produced

### Testing and Reviewing Agent

**Path:** `agents/skills/testing-and-reviewing/SKILL.md`

Validates changes through executed tests and review-oriented analysis.

- Default scope: unit + integration tests
- Can add linters, build checks, and system tests as needed
- Produces execution evidence (not just test code) for the supervisor gate
- Used when: implementation is complete and proof of correctness is needed

### Committing Agent

**Path:** `agents/skills/committing-agent/SKILL.md`

Finalizes a validated scope into an intentional git commit.

- Stages only files within the active scope (no incidental changes)
- Enforces 80-character line limit on commit messages
- Updates `.dev/` commit status after a successful commit
- Used when: final verification has passed and the scope is ready to commit

### Evaluating Agent

**Path:** `agents/skills/evaluating-agent/SKILL.md`

Assesses goal achievement after a pipeline run completes.

- Reviews execution artifacts against the original goal
- Generates a structured evaluation report under `.dev/07-evaluator/`
- Can produce a follow-up goal for the Goals Scheduler to queue next
- Used when: goals automation is enabled and an evaluator stage is configured

### PRD Agent

**Path:** `agents/skills/prd-agent/SKILL.md`

Generates a structured Product Requirements Document before planning begins.

- Produces user stories, acceptance criteria, and success metrics
- Provides scope boundaries that inform the Planning Agent
- Used when: a new initiative needs formal requirements before a plan is made

---

## Workflow Pipeline

The bundled workflows (`agents/workflows/`) combine the agent roles above into
four composable sequences. The Supervising Agent controls which workflow is
active and when to advance.

```mermaid
flowchart TD
    Start([New Scope]) --> wf1["Workflow 1\nPlanning & Design"]
    wf1 --> plan[Planning Agent]
    plan --> design[Designing Agent]

    design --> wf2["Workflow 2\nDevelop & Test Authoring"]
    wf2 --> develop[Developing Agent]
    wf2 --> testauth[Test Authoring Agent]

    develop --> wf3["Workflow 3\nBuild, Deploy & Review"]
    testauth --> wf3
    wf3 --> build[Building & Deploying Agent]
    build --> review[Testing & Reviewing Agent]
    review -- "fail / needs rework" --> develop

    review -- pass --> wf4["Workflow 4\nCleanup & Commit"]
    wf4 --> finalverify[Final Verification\nSupervising Agent]
    finalverify -- fail --> develop
    finalverify -- pass --> commit[Committing Agent]
    commit --> Done([Done])

    supervisor[Supervising Agent] -. orchestrates all transitions .-> wf1
```

### Workflow 1 — Planning and Design

**Path:** `agents/workflows/planning-design.md`

Runs the Planning Agent then the Designing Agent in sequence. Enter this
workflow when a new scope starts or design decisions are needed before any
code changes.

**Outputs:** Phase checklist in `.dev/PLAN.md`, implementation-ready design
notes, updated `.dev/DASHBOARD.md`.

### Workflow 2 — Develop and Test Authoring

**Path:** `agents/workflows/develop-test-authoring.md`

Runs the Developing Agent and the Test Authoring Agent as parallel tracks after
design is complete. Both share the same active slice but own separate files.

**Outputs:** Product-code changes, matching unit/integration tests, updated
`.dev/` state.

### Workflow 3 — Build, Deploy, and Test Review

**Path:** `agents/workflows/build-deploy-test-review.md`

Runs the Building/Deploying Agent, then the Testing/Reviewing Agent, then Final
Verification. Failures at any stage route back to development.

**Outputs:** Build/packaging evidence, executed validation results, findings
written to `.dev/`.

### Workflow 4 — Cleanup and Commit

**Path:** `agents/workflows/cleanup-commit.md`

Runs the Committing Agent after final verification passes. Cleans up transient
files, stages only the active scope, and produces a scoped commit.

**Outputs:** Intentional git commit with `.dev/` commit status updated.

### Phase Gate Summary

```mermaid
stateDiagram-v2
    [*] --> planning
    planning --> design : tasks exist, next action clear
    design --> develop : interfaces or decisions documented
    design --> test_author : interfaces or decisions documented
    develop --> build : product code changes exist
    test_author --> build : test code exists
    build --> test_review : artifacts produced
    test_review --> final_verify : execution results exist
    test_review --> develop : fail / needs rework
    final_verify --> commit : operational review passed
    final_verify --> develop : fail
    commit --> [*]
```

---

## Daemonize Mode

`daemonize` turns DORMAMMU into a long-running queue worker. Drop a prompt
file into `prompt_path` and the daemon picks it up, runs it through the
supervised loop, and writes a result report to `result_path`.

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

### Queue ordering

Prompt files are sorted deterministically before processing:

1. Files with a leading numeric prefix — sorted by integer value (`001_`, `02_`, `10_`)
2. Files with a leading alphabetic prefix — sorted alphabetically (`A_`, `b-`, `C_`)
3. Unprefixed files — sorted by full filename

### Result reports

For each processed prompt file `001_feature.md`, the daemon writes
`001_feature_RESULT.md` to `result_path`. The report contains:

- Original prompt filename and paths
- Start and completion timestamps
- Execution outcome and phase summary
- Pointers to relevant `.dev/` and log artifacts

### Combined runtime and daemon config

```bash
DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json \
  dormammu daemonize --repo-root . --config ./ops/daemonize.prod.json
```

### Example config files

| Example | Use when |
|---------|----------|
| `daemonize.json.example` | Default — mixed `.md` and `.txt` prompt queue |
| `daemonize.named-skill.example.json` | Queue accepts only Markdown prompts |
| `daemonize.mixed-skill-resolution.example.json` | Editor writes files in multiple passes; add settle delay |
| `daemonize.phase-specific-clis.example.json` | Shorter polling interval for faster scan cadence |

---

## Role-Based Agent Pipeline

When `agents` is configured in `dormammu.json`, the daemon routes each goal
through a four-stage pipeline instead of the single-agent loop:

```mermaid
flowchart LR
    goal([Goal File]) --> dev[Developer]
    dev --> tester[Tester]
    tester -- "OVERALL: FAIL" --> dev
    tester -- "OVERALL: PASS" --> reviewer[Reviewer]
    reviewer -- "VERDICT: NEEDS_WORK" --> dev
    reviewer -- "VERDICT: APPROVED" --> committer[Committer]
    committer --> done([Done])
```

### Roles

| Role | Output slot | Verdict | Re-entry trigger |
|------|------------|---------|-----------------|
| developer | `.dev/01-developer/` | — | tester `FAIL` or reviewer `NEEDS_WORK` |
| tester | `.dev/04-tester/` | `OVERALL: PASS` / `OVERALL: FAIL` | — |
| reviewer | `.dev/05-reviewer/` | `VERDICT: APPROVED` / `VERDICT: NEEDS_WORK` | — |
| committer | `.dev/06-committer/` | — | — |

**Tester** runs as a black-box one-shot agent. It designs and executes test
cases against the observable behavior described in the goal, then appends
`OVERALL: PASS` or `OVERALL: FAIL` as its last output line. A `FAIL` verdict
sends the developer back with the tester report appended.

**Reviewer** performs a code review against the goal and any available
architect design document (`.dev/02-architect/<date>_<stem>.md`). It appends
`VERDICT: APPROVED` or `VERDICT: NEEDS_WORK` as its last line. `NEEDS_WORK`
sends the developer back for another round.

**Re-entry limit**: after three rounds in the tester or reviewer loop,
the pipeline advances unconditionally.

### CLI assignment per role

For each role, the CLI is resolved in order:

1. `agents.<role>.cli` from `dormammu.json`
2. `active_agent_cli` as the global fallback

---

## Goals Automation

When `goals` is configured in `daemonize.json`, a `GoalsScheduler` thread
runs alongside the daemon. At each `interval_minutes` tick it scans the
`goals.path` directory and promotes any `.md` files it finds into `prompt_path`
for the next pipeline run. Files already processed (matched by `<date>_<stem>`)
are skipped.

When an **Evaluating Agent** is configured, it runs after the committer stage
and can generate a follow-up goal — enabling fully continuous, self-scheduling
cycles.

The goals directory is also manageable via the Telegram bot integration using
`/goals` commands (list, add, delete).

---

## Guidance Files

Guidance files let you inject repository-specific operating rules into every
agent prompt. DORMAMMU resolves guidance in this order:

1. Explicit `--guidance-file` flags (in order given)
2. Repository guidance: `AGENTS.md` or `agents/AGENTS.md` at the repo root
3. Installed fallback guidance under `~/.dormammu/agents`
4. Packaged fallback guidance assets bundled with DORMAMMU

Example — pass multiple guidance files explicitly:

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --guidance-file AGENTS.md \
  --guidance-file docs/agent-rules.md \
  --prompt "Implement the requested change."
```

---

## The `.dev` Directory

`.dev/` is the shared control surface for humans and automation.

| File | Role |
|------|------|
| `.dev/DASHBOARD.md` | Current operator-facing status: active phase, next action, risks |
| `.dev/PLAN.md` | Prompt-derived phase checklist (`[ ]` pending, `[O]` complete) |
| `.dev/workflow_state.json` | Machine-readable workflow state — the source of truth |
| `.dev/session.json` | Active session metadata |
| `.dev/logs/` | Per-run prompt, stdout, stderr, and metadata artifacts |
| `.dev/sessions/` | Archived session snapshots |
| `.dev/07-evaluator/` | Evaluation reports from the Evaluating Agent (when goals are enabled) |

Debug logs:

- `run`, `run-once`, `resume` with `--debug` → `DORMAMMU.log` at repo root
- `daemonize --debug` → `<result_path>/../progress/<prompt>_progress.log`,
  recreated fresh for each new prompt session

---

## Session Management

DORMAMMU tracks work in sessions. Each session has an ID and a goal.

```bash
# Start a new named session
dormammu start-session --repo-root . --goal "Phase 2 follow-up work"

# List saved sessions
dormammu sessions --repo-root .

# Restore an older session
dormammu restore-session --repo-root . --session-id <id>
```

Sessions are useful when you want to branch workflow history or return to a
prior checkpoint without discarding later work.

---

## Fallback Agent CLIs

If the primary agent CLI hits token exhaustion or quota limits (matched by
`token_exhaustion_patterns`), DORMAMMU automatically switches to the next
configured fallback CLI.

Default fallback order when no config is present:

1. `codex`
2. `claude`
3. `gemini`

Configure fallbacks in `dormammu.json`:

```json
{
  "active_agent_cli": "codex",
  "fallback_agent_clis": [
    "claude",
    { "path": "aider", "extra_args": ["--yes"] }
  ],
  "token_exhaustion_patterns": [
    "usage limit", "quota exceeded", "rate limit exceeded"
  ]
}
```

---

## Working Directory and CLI Overrides

`--workdir` sets the process working directory for the external CLI. If the
adapter knows the CLI's workdir flag, it also forwards the value there.

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli cline \
  --workdir ./subproject \
  --prompt "Inspect this subproject and summarize the next step."
```

For the `cline` preset, DORMAMMU forwards `--workdir` as `--cwd <path>`.

To pass arbitrary extra flags:

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli gemini \
  --prompt "Summarize the repo." \
  --extra-arg=--approval-mode \
  --extra-arg=auto_edit
```

Per-CLI defaults can be set in `cli_overrides`:

```json
{
  "cli_overrides": {
    "cline": { "extra_args": ["-y", "--verbose", "--timeout", "1200"] }
  }
}
```

---

## Typical Operator Flow

```bash
# 1. Check the environment
dormammu doctor --repo-root . --agent-cli codex

# 2. Bootstrap state
dormammu init-state --repo-root . --goal "Ship the requested change safely"

# 3. Verify config and CLI adapter
dormammu show-config --repo-root .
dormammu inspect-cli --repo-root . --agent-cli codex

# 4. Run
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes

# 5. Resume if interrupted
dormammu resume --repo-root .
```

---

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
