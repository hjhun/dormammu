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

## Config Entry Points At A Glance

Dormammu uses two different JSON config entry points:

- general runtime config for commands like `run`, `run-once`, `resume`,
  `doctor`, and `inspect-cli`
- daemon queue config for `dormammu daemonize`

General runtime config resolution order is:

1. `DORMAMMU_CONFIG_PATH`
2. `<repo-root>/dormammu.json`
3. `~/.dormammu/config`

Use this to verify the resolved runtime config:

```bash
dormammu show-config --repo-root .
```

Use this to start a daemon queue worker:

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

If you need both at once, set the runtime config explicitly and pass the daemon
workflow file separately:

```bash
DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json \
  dormammu daemonize --repo-root . --config ./ops/daemonize.prod.json
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

### 3a. Confirm which runtime JSON config Dormammu resolved

```bash
dormammu show-config --repo-root .
```

This prints the resolved config as JSON, including the `config_file` path when
Dormammu loaded `dormammu.json`, `DORMAMMU_CONFIG_PATH`, or the global
`~/.dormammu/config`.

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

### `dormammu daemonize`

Watches a prompt directory from a daemon JSON config and processes prompts one
at a time in deterministic queue order.

Example:

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

Use `daemonize` when you want Dormammu to behave like a long-running operator
loop:

- watch `prompt_path` for incoming prompt files
- rescan `prompt_path` every 60 seconds using the daemon polling loop
- sort prompt files by leading numeric prefix first, then alphabetic prefix,
  then plain filename
- execute configured workflow phases for each prompt
- write an in-progress result report to `result_path` before phase execution
  completes, then finalize that report when processing ends
- remove the processed prompt file from `prompt_path` only after the prompt run
  finishes with `PLAN.md` fully completed

Use [daemonize.json.example](../daemonize.json.example) as the starting point
for the config. This daemon file is separate from the general runtime config
used by `show-config`, `run`, `run-once`, and `resume`.

The combined pattern looks like:

```bash
DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json \
  dormammu daemonize --repo-root . --config ./ops/daemonize.prod.json
```

For known interactive CLIs, `daemonize` also injects non-interactive defaults
when a phase leaves `agent_cli.extra_args` empty:

- `codex`: `--dangerously-bypass-approvals-and-sandbox`, plus
  `--skip-git-repo-check` when supported by the installed `codex exec`
- `claude`: `--dangerously-skip-permissions`
- `gemini`: `--approval-mode yolo --include-directories /`

Set explicit phase `extra_args` when you want to override those defaults.

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

## Daemonize Config Rules

`daemonize` uses a separate JSON file from `dormammu.json`.

- `dormammu.json` remains the general Dormammu runtime config
- `daemonize.json` describes one watched prompt-processing workflow

That distinction is easy to miss, so a good operator check is:

```bash
dormammu show-config --repo-root .
dormammu daemonize --help
```

The most important fields are:

- `prompt_path`
- `result_path`
- `watch`
- `queue`
- `phases`

### Phase Skill Resolution

Each phase must define exactly one of:

- `skill_name`
- `skill_path`

Do not set both in the same phase entry.

#### `skill_name`

`skill_name` is the preferred reusable form when the phase should point at a
named skill bundle such as `planning-agent` or `developing-agent`.

Resolution order is:

1. `repo_root/agents/skills/<skill_name>/SKILL.md`
2. `~/.dormammu/agents/skills/<skill_name>/SKILL.md`

If the skill cannot be found in either location, `daemonize` fails fast during
config loading before the watch loop starts.

Example:

```json
{
  "skill_name": "planning-agent",
  "agent_cli": {
    "path": "codex",
    "input_mode": "auto",
    "extra_args": []
  }
}
```

Leaving `extra_args` empty is enough for unattended `daemonize` runs with the
built-in presets above. Add explicit args only when you need a different
approval or sandbox policy.

Use `skill_name` when:

- the skill is part of the repository's `agents/skills/`
- the skill is installed under `~/.dormammu/agents/skills/`
- you want the config to stay portable across machines with the same skill
  layout

#### `skill_path`

`skill_path` is the explicit file-path form. Use it when the skill file lives
outside the standard named-skill lookup layout or when you want the config to
pin one exact file.

Relative paths are resolved relative to the daemon config file directory, not
the current shell working directory.

Example:

```json
{
  "skill_path": "./custom-skills/release-checklist.md",
  "agent_cli": {
    "path": "codex",
    "input_mode": "auto",
    "extra_args": []
  }
}
```

Use `skill_path` when:

- the skill file is custom to one repository
- the skill is not organized under `agents/skills/<name>/SKILL.md`
- you want the daemon config to lock to one exact skill document

### Skill Rule Summary

- Every phase needs one skill reference.
- `skill_name` and `skill_path` are mutually exclusive.
- `skill_name` is resolved through repository-local skills first, then the
  installed `~/.dormammu/agents` bundle.
- `skill_path` must point to an existing file.
- Missing or ambiguous skill configuration is treated as a startup error.

### Recommended Default Mapping

For the current built-in workflow bundle, the usual phase mapping is:

- `plan` -> `planning-agent`
- `design` -> `designing-agent`
- `develop` -> `developing-agent`
- `build_and_deploy` -> `building-and-deploying`
- `test_and_review` -> `testing-and-reviewing`
- `commit` -> `committing-agent`

### Installed Skill Paths Under `~/.dormammu/agents`

If you prefer explicit `skill_path` values instead of `skill_name`, the
installed skill bundle typically uses these paths:

- `plan` -> `~/.dormammu/agents/skills/planning-agent/SKILL.md`
- `design` -> `~/.dormammu/agents/skills/designing-agent/SKILL.md`
- `develop` -> `~/.dormammu/agents/skills/developing-agent/SKILL.md`
- `build_and_deploy` -> `~/.dormammu/agents/skills/building-and-deploying/SKILL.md`
- `test_and_review` -> `~/.dormammu/agents/skills/testing-and-reviewing/SKILL.md`
- `commit` -> `~/.dormammu/agents/skills/committing-agent/SKILL.md`

Example:

```json
{
  "phases": {
    "plan": {
      "skill_path": "~/.dormammu/agents/skills/planning-agent/SKILL.md",
      "agent_cli": {
        "path": "codex",
        "input_mode": "auto",
        "extra_args": []
      }
    }
  }
}
```

Use explicit `skill_path` values when:

- you want the config to pin the exact installed skill file
- you are operating without a repository-local `agents/skills/` directory
- you want to make the daemon config's dependency on the installed bundle
  obvious during review

### Example Config Files

Dormammu now ships multiple daemon config examples so you can start from the
closest operating model instead of editing one generic file from scratch.

- `daemonize.json.example`
  - uses explicit installed `skill_path` values under `~/.dormammu/agents`
  - good when you want reviewable, fully expanded phase-to-skill paths
- `daemonize.named-skill.example.json`
  - uses `skill_name` for every phase
  - good when you want the most portable config across machines and repos
- `daemonize.mixed-skill-resolution.example.json`
  - mixes `skill_name` and `skill_path`
  - good when most phases use standard skills but one or two phases need a
    repository-local custom skill file
- `daemonize.phase-specific-clis.example.json`
  - keeps standard skills but varies the external `agent_cli` per phase
  - good when planning, implementation, review, and packaging should run
    through different agent backends

### Which Example Should I Start From?

Use this quick chooser when you are not sure which file to copy first.

- Start from `daemonize.json.example`
  - when you want the safest review surface with fully expanded installed
    `skill_path` values
- Start from `daemonize.named-skill.example.json`
  - when you want the most portable config and expect repository or installed
    skill lookup to work consistently
- Start from `daemonize.mixed-skill-resolution.example.json`
  - when most phases use standard skills but one or more phases need a custom
    repository-local skill file
- Start from `daemonize.phase-specific-clis.example.json`
  - when you already know that different phases should run through different
    external agent CLIs

Typical operator choices:

- team-wide installed workflow bundle -> `daemonize.json.example`
- portable repo template -> `daemonize.named-skill.example.json`
- repo with one custom release or review skill -> `daemonize.mixed-skill-resolution.example.json`
- split planning/review/implementation backends -> `daemonize.phase-specific-clis.example.json`

### Why This Rule Exists

Dormammu separates:

- which skill contract defines the phase behavior
- which external agent CLI is used to execute that phase

That separation keeps configs maintainable:

- you can keep the same skill but switch from `codex` to another CLI
- you can keep the same CLI but point one phase at a different skill
- you do not have to duplicate skill text inline in the JSON config

## Working Directory And CLI Overrides

When you pass `--workdir`, `dormammu` always uses that directory as the process
working directory for the external CLI. If the adapter knows the CLI's workdir
flag, it forwards the value there too.

For example, the Cline preset supports:

- positional prompts
- `-y`
- default `--verbose`
- default `--timeout 1200`
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
      "extra_args": ["-y", "--verbose", "--timeout", "1200"]
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
