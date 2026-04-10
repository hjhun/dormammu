<p align="center">
  <img src="docs/svg/dormammu.svg" alt="DORMAMMU logo" width="180">
</p>

# DORMAMMU

`dormammu` is a CLI-first workflow loop orchestrator for coding agents. It runs
an external agent CLI, stores resumable state under `.dev/`, validates the
result with a supervisor, and helps you continue safely after interruption.

Start with the full guide at [docs/GUIDE.md](docs/GUIDE.md). Korean
documentation is available at [docs/ko/GUIDE.md](docs/ko/GUIDE.md).

## Highlights

- Supervised agent loops: run one-shot agent calls or a retry loop with
  required-path and worktree-change checks.
- Resumable execution: keep prompts, logs, session metadata, and machine state
  under `.dev/` so work can continue instead of restarting from scratch.
- CLI adapter support: inspect and drive external CLIs such as `codex`,
  `claude`, `gemini`, `cline`, and `aider` through a unified runtime.
- Operator-visible state: persist `DASHBOARD.md`, `PLAN.md`,
  `workflow_state.json`, and run artifacts for both humans and tooling.
- Guidance-aware prompting: embed repository guidance like `AGENTS.md` or
  explicit `--guidance-file` Markdown files into agent runs.
- Fallback backends: move to another configured agent CLI automatically when
  the primary backend hits quota or token-exhaustion patterns.
- Session management: start new sessions, list saved sessions, and restore old
  snapshots into the active `.dev` view.

## Supported Workflows

- `run-once`: invoke an external agent CLI a single time and persist artifacts.
- `run`: execute a supervised retry loop around an agent CLI.
- `daemonize`: watch a prompt directory from JSON config and process queued
  prompts sequentially.
- `resume`: continue the latest supervised run from saved state.
- `inspect-cli`: detect prompt mode, workdir support, and risky approval flags.
- `doctor`: verify Python, agent CLI availability, repository writability, and
  workspace structure.
- `init-state`, `start-session`, `sessions`, `restore-session`: bootstrap and
  manage `.dev` state over time.

If you are not sure which config file a command uses, start with:

```bash
dormammu --help
dormammu show-config --repo-root .
dormammu daemonize --help
```

The two config entry points are:

- General runtime config: `./dormammu.json`, or `DORMAMMU_CONFIG_PATH`, or
  `~/.dormammu/config`
- Daemon queue config: `dormammu daemonize --config daemonize.json`

## Installation

### Quick Install

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

The supported runtime target is Python `3.10+`.

## Quick Start

### 1. Check your environment

```bash
dormammu doctor --repo-root . --agent-cli codex
```

### 2. Bootstrap `.dev` state

```bash
dormammu init-state \
  --repo-root . \
  --goal "Implement the requested repository change safely."
```

During bootstrap, `init-state` also probes the local machine for supported
coding-agent CLIs and updates `active_agent_cli` to the highest-priority
available command in this order: `codex`, `claude`, `gemini`, `cline`.

### 3. Inspect the external CLI adapter

```bash
dormammu inspect-cli --repo-root . --agent-cli cline
```

### 3a. Confirm which JSON config Dormammu will load

```bash
dormammu show-config --repo-root .
```

Use this before real runs when you want to verify whether Dormammu is reading
`./dormammu.json`, `DORMAMMU_CONFIG_PATH`, or the global
`~/.dormammu/config`.

### 4. Run one agent pass

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli codex \
  --prompt "Read the repo guidance and summarize the next implementation step."
```

### 5. Run the supervised loop

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes \
  --max-iterations 50
```

If you do not set a loop budget explicitly, `dormammu run` now defaults to
`50` total attempts. As soon as the supervisor approves the work, Dormammu
exits immediately instead of consuming the remaining budget.

### 6. Resume later if needed

```bash
dormammu resume --repo-root .
```

### 7. Run daemonized prompt watching

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

Use [daemonize.json.example](daemonize.json.example) as the starting point for
the daemon config file. `daemonize --config` is separate from the general
runtime config in `dormammu.json`.

If you want both files at once, the pattern is:

```bash
DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json \
  dormammu daemonize --repo-root . --config ./ops/daemonize.prod.json
```

Each queued prompt now reuses the same supervised loop as
`dormammu run --prompt-file <path>`. When that loop reaches a terminal
outcome, daemonize writes the result report into `result_path` and removes the
source prompt file from `prompt_path`.

Additional daemon config examples are also available for different watch and
queue presets:

- [daemonize.json.example](daemonize.json.example)
- [daemonize.named-skill.example.json](daemonize.named-skill.example.json)
- [daemonize.mixed-skill-resolution.example.json](daemonize.mixed-skill-resolution.example.json)
- [daemonize.phase-specific-clis.example.json](daemonize.phase-specific-clis.example.json)

## What Gets Written

`dormammu` keeps the workflow inspectable and resumable with files such as:

- `.dev/DASHBOARD.md`: current operator-facing progress view
- `.dev/PLAN.md`: prompt-derived task checklist
- `.dev/workflow_state.json`: machine-readable workflow state
- `.dev/session.json`: active session metadata
- `.dev/logs/`: prompt, stdout, stderr, and metadata artifacts
- `DORMAMMU.log`: project-level execution log for `run`, `run-once`, and
  `resume`

## Common Usage Patterns

### Use repository guidance automatically

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt "Follow AGENTS.md and implement the requested change."
```

`dormammu` will use explicit `--guidance-file` inputs first, then repository
guidance such as `AGENTS.md` or `agents/AGENTS.md`, then installed fallback
guidance under `~/.dormammu/agents`, then packaged guidance assets.

### Run in a specific working directory

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli cline \
  --workdir ./subproject \
  --prompt "Inspect this subproject and report the failing test surface."
```

For supported CLIs, `dormammu` forwards the workdir through the adapter, such
as Cline's `--cwd <path>`.

### Pass through extra CLI arguments

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli gemini \
  --prompt "Summarize the repo." \
  --extra-arg=--approval-mode \
  --extra-arg=auto_edit
```

### Manage multiple sessions

```bash
dormammu start-session --repo-root . --goal "Phase 2 follow-up work"
dormammu sessions --repo-root .
dormammu restore-session --repo-root . --session-id your-session-id
```

## CLI Compatibility Notes

- `codex`: uses the `exec` command prefix and positional prompts.
- `claude`: uses print-mode style invocation and permission-mode detection.
- `gemini`: supports prompt flags, approval-mode defaults, and include-dir
  configuration.
- `cline`: supports positional prompts with `-y`, default `--verbose`,
  default `--timeout 1200`, and `--cwd <path>` forwarding when `--workdir`
  is set.
- `aider`: supports message-style prompt flags.

Use `dormammu inspect-cli` before real runs if you want to confirm prompt mode,
workdir support, matched preset, and approval-related hints.

For unattended daemon-style runs, Dormammu applies non-interactive defaults for
known CLIs when you do not pass explicit approval args:

- `codex`: `--dangerously-bypass-approvals-and-sandbox`, plus
  `--skip-git-repo-check` when the installed `codex exec` help advertises it
- `claude`: `--dangerously-skip-permissions`
- `gemini`: `--approval-mode yolo --include-directories /`

## Configuration

Without an explicit config file, the built-in fallback order is:

- `codex`
- `claude`
- `gemini`

Example `dormammu.json`:

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
  ]
}
```

By default, the global config path is `~/.dormammu/config` when no repository
local `dormammu.json` is present.

Runtime config resolution order is:

1. `DORMAMMU_CONFIG_PATH`
2. `<repo-root>/dormammu.json`
3. `~/.dormammu/config`

Quick examples:

```bash
dormammu show-config --repo-root .
DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json dormammu run --repo-root . --prompt-file PROMPT.md
```

`daemonize` no longer accepts phase-specific agent CLI settings. Configure the
coding agent once through `dormammu.json` or `~/.dormammu/config` with
`active_agent_cli`, and daemonize will reuse the same supervised run loop as
`dormammu run`.

## Repository Layout

```text
backend/     Python package, loop engine, adapters, state, supervisor
agents/      Distributable workflow and skill guidance bundle
templates/   Bootstrap templates for `.dev` state
docs/        User and operator documentation
docs/svg/    Brand assets
scripts/     Install and developer convenience scripts
tests/       Runtime, adapter, and workflow validation
```

## Release Packaging

`.github/workflows/release.yml` builds wheel and sdist artifacts on `v*` tag
pushes and on manual workflow dispatch. The release flow publishes `dist/*`
artifacts plus the root `install.sh`, and the packaged build includes the
guidance bundle used for installed fallback behavior.

## License

`dormammu` is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
