# Daemonize Mode Design

## Goal

Add a `daemonize` execution mode to Dormammu that:

- reads a dedicated JSON configuration file
- watches a prompt directory for newly created prompt files
- queues prompt files in deterministic ascending order based on a leading
  numeric or alphabetic prefix in the filename
- runs Dormammu workflow phases for each queued prompt
- writes one result report per prompt as `<PROMPT FILENAME>_RESULT.md`
- prefers inode-event-based monitoring and falls back to 60-second polling when
  such monitoring is unavailable

## Scope

This design covers:

- CLI surface for `daemonize`
- daemon-specific JSON schema
- watcher backend abstraction
- prompt queue ordering
- per-prompt execution model
- phase runner separation between Dormammu workflow skills and external agent
  CLI invocations
- result artifact shape
- test seams

This design does not cover:

- service-manager integration such as systemd units
- remote prompt sources
- concurrent multi-prompt execution
- non-Markdown result formats

## User-Facing Command

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

### CLI contract

- `daemonize` is a new subcommand in `backend/dormammu/cli.py`.
- `--config` is required and points to the daemon JSON file.
- `--repo-root` remains optional and defaults to repository discovery.
- The command runs continuously until interrupted or until a fatal config or
  runtime error occurs.
- The command writes lifecycle logs to `DORMAMMU.log` through the existing
  project log capture mechanism.

## Configuration Model

The daemon configuration is separate from the existing `dormammu.json`
application config. The existing config continues to describe Dormammu runtime
defaults. The daemon config describes one watched workflow.

Suggested filename examples:

- `dormammu-daemon.json`
- `ops/review-daemon.json`

## JSON Schema

The daemon config must be a JSON object with the following shape:

```json
{
  "schema_version": 1,
  "prompt_path": "./queue/prompts",
  "result_path": "./queue/results",
  "watch": {
    "backend": "auto",
    "poll_interval_seconds": 60,
    "settle_seconds": 2
  },
  "queue": {
    "allowed_extensions": [".md", ".txt"],
    "ignore_hidden_files": true
  },
  "phases": {
    "plan": {
      "skill_path": "~/.dormammu/agents/skills/planning-agent/SKILL.md",
      "agent_cli": {
        "path": "codex",
        "input_mode": "auto",
        "prompt_flag": null,
        "extra_args": []
      }
    },
    "design": {
      "skill_path": "~/.dormammu/agents/skills/designing-agent/SKILL.md",
      "agent_cli": {
        "path": "codex",
        "input_mode": "auto",
        "prompt_flag": null,
        "extra_args": []
      }
    },
    "develop": {
      "skill_path": "~/.dormammu/agents/skills/developing-agent/SKILL.md",
      "agent_cli": {
        "path": "codex",
        "input_mode": "auto",
        "prompt_flag": null,
        "extra_args": []
      }
    },
    "build_and_deploy": {
      "skill_path": "~/.dormammu/agents/skills/building-and-deploying/SKILL.md",
      "agent_cli": {
        "path": "codex",
        "input_mode": "auto",
        "prompt_flag": null,
        "extra_args": []
      }
    },
    "test_and_review": {
      "skill_path": "~/.dormammu/agents/skills/testing-and-reviewing/SKILL.md",
      "agent_cli": {
        "path": "codex",
        "input_mode": "auto",
        "prompt_flag": null,
        "extra_args": []
      }
    },
    "commit": {
      "skill_path": "~/.dormammu/agents/skills/committing-agent/SKILL.md",
      "agent_cli": {
        "path": "codex",
        "input_mode": "auto",
        "prompt_flag": null,
        "extra_args": []
      }
    }
  }
}
```

### Required fields

- `schema_version`
- `prompt_path`
- `result_path`
- `phases.plan`
- `phases.design`
- `phases.develop`
- `phases.build_and_deploy`
- `phases.test_and_review`
- `phases.commit`

### Field semantics

- `prompt_path`: directory watched for prompt files
- `result_path`: directory where result reports are written
- `watch.backend`: one of `auto`, `inotify`, `polling`
- `watch.poll_interval_seconds`: required fallback interval, default `60`
- `watch.settle_seconds`: delay used to avoid reading a file before the writer
  is finished, default `2`
- `queue.allowed_extensions`: optional filter for prompt files
- `queue.ignore_hidden_files`: whether dotfiles are skipped
- `phases.<phase>.skill_name`: skill directory name resolved from
  `repo_root/agents/skills/<name>/SKILL.md` and then
  `~/.dormammu/agents/skills/<name>/SKILL.md`
- `phases.<phase>.skill_path`: explicit path to a skill document
- `phases.<phase>.agent_cli`: external CLI invocation config for that phase

### Why both skill resolution and `agent_cli`

The request requires separating the Dormammu workflow skill from the external
agent CLI invocation, but the skill should be referenced by stable path or
name rather than duplicated as inline prompt text.

- `skill_name` or `skill_path` expresses which reusable Dormammu skill applies
  to that phase
- `agent_cli` expresses how Dormammu launches the selected external agent CLI

This allows:

- reusing the same external CLI across phases with different instructions
- changing only the instruction layer without changing runtime wiring
- changing only the CLI backend per phase without rewriting phase prompts

## Internal Data Model

Add daemon-specific models in a new module such as
`backend/dormammu/daemon/models.py`.

### Proposed dataclasses

- `PhaseCliConfig`
  - `path: Path`
  - `input_mode: str`
  - `prompt_flag: str | None`
  - `extra_args: tuple[str, ...]`
- `PhaseExecutionConfig`
  - `phase_name: str`
  - `skill_name: str | None`
  - `skill_path: Path`
  - `agent_cli: PhaseCliConfig`
- `WatchConfig`
  - `backend: str`
  - `poll_interval_seconds: int`
  - `settle_seconds: int`
- `QueueConfig`
  - `allowed_extensions: tuple[str, ...]`
  - `ignore_hidden_files: bool`
- `DaemonConfig`
  - `schema_version: int`
  - `config_path: Path`
  - `prompt_path: Path`
  - `result_path: Path`
  - `watch: WatchConfig`
  - `queue: QueueConfig`
  - `phases: dict[str, PhaseExecutionConfig]`
- `QueuedPrompt`
  - `path: Path`
  - `filename: str`
  - `sort_key: tuple[int, object, str]`
  - `detected_at: str`
- `DaemonRunRecord`
  - `prompt_path: Path`
  - `result_path: Path`
  - `status: str`
  - `started_at: str`
  - `completed_at: str | None`
  - `phase_runs: Sequence[dict[str, Any]]`
  - `error: str | None`

## Module Boundaries

Create a dedicated daemon package:

- `backend/dormammu/daemon/models.py`
- `backend/dormammu/daemon/config.py`
- `backend/dormammu/daemon/watchers.py`
- `backend/dormammu/daemon/queue.py`
- `backend/dormammu/daemon/runner.py`
- `backend/dormammu/daemon/reports.py`

### Responsibilities

- `daemon/config.py`
  - load and validate daemon JSON
  - resolve relative paths against the daemon config directory
- `daemon/watchers.py`
  - provide a watcher interface
  - expose `InotifyWatcher` and `PollingWatcher`
  - select backend through `auto`
- `daemon/queue.py`
  - filter prompt candidates
  - build stable sort keys
  - manage queued versus in-progress file paths
- `daemon/runner.py`
  - drive the continuous watch loop
  - call the per-prompt phase runner
  - ensure one prompt is processed at a time
- `daemon/reports.py`
  - render per-prompt result Markdown
  - optionally emit machine-readable sidecar data later

## Watcher Design

### Backend selection

- `auto`:
  - use inotify-backed monitoring when available on the current platform
  - fall back to polling otherwise
- `inotify`:
  - fail fast if the backend is unavailable
- `polling`:
  - always use directory scanning with a 60-second interval by default

### Inotify implementation strategy

Preferred order:

1. stdlib-compatible lightweight Linux implementation if practical
2. optional package-backed watcher if explicitly added as a dependency
3. fallback to polling

The current repository has no watcher dependency yet, so implementation should
initially favor minimal dependency growth. The design keeps the backend behind a
small interface so a dependency can be added later without changing the runner.

### Watcher interface

```python
class PromptWatcher(Protocol):
    def start(self) -> None: ...
    def close(self) -> None: ...
    def wait_for_changes(self) -> list[Path]: ...
```

Behavior:

- `wait_for_changes()` returns one or more candidate file paths
- watcher implementations may coalesce duplicate events
- the daemon runner re-scans the directory before selecting work so transient
  watcher noise does not break ordering guarantees

### Settle window

A prompt file should not be processed immediately on the first create event.
The daemon should wait until the file has remained unchanged for
`watch.settle_seconds` before enqueueing it for execution.

This avoids:

- partial reads while another process is still writing
- duplicate processing from write bursts

## Queue Ordering

Prompt files are sorted by filename, but with a parsed prefix-aware key.

### Parsing rule

Use the basename only.

1. If the filename begins with digits, parse the leading integer token.
2. Else if the filename begins with ASCII letters, parse the leading
   alphabetic token case-insensitively.
3. Else treat the file as an unprefixed item.

Examples:

- `001_fix_tests.md` -> numeric bucket, key `1`
- `12-refactor.md` -> numeric bucket, key `12`
- `A_design.md` -> alphabetic bucket, key `a`
- `b-commit.md` -> alphabetic bucket, key `b`
- `_manual.md` -> unprefixed bucket

### Global ordering

Ascending queue order:

1. numeric-prefixed files by integer value, then full filename
2. alphabetic-prefixed files by lowercase prefix, then full filename
3. unprefixed files by full filename

This makes the ordering deterministic even when prefixes collide.

### Duplicate prevention

The queue manager tracks:

- discovered files
- in-progress file
- completed file basenames within the current process lifetime

The daemon does not reprocess a prompt path that already has a successful
result file unless the original prompt file is deleted and recreated or the
daemon is restarted with an empty runtime cache.

## Execution Model

### High-level flow

1. load daemon config
2. ensure `prompt_path` and `result_path` exist
3. resolve watcher backend
4. scan for already-existing prompt files at startup
5. enqueue ready prompts using the ordering rules
6. process one prompt at a time
7. after the queue drains, wait for new watcher events

### Per-prompt flow

1. read prompt file contents
2. create a run context for this prompt
3. execute configured phases in this fixed order:
   - `plan`
   - `design`
   - `develop`
   - `build_and_deploy`
   - `test_and_review`
   - `commit`
4. capture each phase outcome
5. write `<PROMPT FILENAME>_RESULT.md`
6. continue with the next queued prompt

### Phase runner contract

Each phase uses:

- the configured `skill_prompt`
- the configured external `agent_cli`
- the prompt text for the current prompt file
- the shared repository root

The runner composes a phase-specific agent prompt like:

1. phase identity and expected workflow skill
2. the original prompt file contents
3. explicit instruction to keep `.dev` aligned
4. phase handoff expectations for the next phase

### Why not use one CLI for the whole prompt

The request explicitly wants per-phase CLI separation. Therefore the daemon
must treat each phase as its own agent invocation boundary rather than treating
the prompt as a single monolithic `run` call.

## Result Report

For a prompt file `001_feature.md`, write:

- result file: `001_feature_RESULT.md`

Location:

- `result_path / "<prompt filename stem>_RESULT.md"`

### Report contents

- original prompt filename
- prompt path
- result path
- started and completed timestamps
- watcher backend used
- sorted queue key
- phase-by-phase execution summary
- final overall status
- failure details when present
- pointers to relevant `.dev` and log artifacts when available

The result report is operator-facing Markdown, not a raw dump of CLI output.

## Failure Handling

### Config failures

- invalid config file
- unsupported backend value
- missing required phase entry
- invalid prompt or result path

Behavior:

- fail fast
- print a clear CLI error
- do not enter the watch loop

### Runtime prompt failures

- prompt file disappears before read
- prompt file cannot be decoded
- one phase CLI exits non-zero
- one phase produces an invalid or missing output artifact

Behavior:

- write a result report marked failed
- continue to the next prompt unless the daemon itself is corrupted

### Fatal daemon failures

- watcher backend crashes repeatedly
- result directory becomes unwritable
- config cannot be reloaded at startup

Behavior:

- exit with non-zero status after logging the fatal error

## State And Resumability

The daemon should reuse the existing `.dev` state machinery for each phase run,
but it should not invent a new persistent daemon-state database in the first
milestone.

First milestone behavior:

- rely on existing `.dev` files and logs for run traceability
- keep in-memory queue state only
- rebuild queue state by scanning `prompt_path` on process startup

This keeps the implementation small while remaining resumable enough for the
requested behavior.

## Integration With Existing Components

### Existing code to reuse

- `AppConfig.load()` for repository-level runtime config
- `CliAdapter` for external CLI execution
- project-level log capture in `cli.py`
- existing `.dev` state repository where phase prompts need to persist

### New phase execution helper

Add a helper in `daemon/runner.py` or a nearby module that:

- builds phase-specific `AgentRunRequest`
- chooses the phase-specific CLI path and invocation settings
- records phase results

This helper should not mutate global `AppConfig.active_agent_cli`. The daemon
config already specifies the exact CLI for each phase.

## Testing Strategy

### Unit tests

- daemon config parsing and path resolution
- invalid config rejection
- queue sort key generation
- queue filtering by extension
- watcher backend selection
- result report rendering

### Integration tests

- startup scan processes already-existing prompt files
- create-event flow enqueues and processes a new prompt
- polling backend processes prompts on the next scan interval
- per-phase CLI wiring uses the configured phase CLI instead of the global
  active CLI
- failed phase writes a failed result report and continues with the next prompt

### System tests

Not required for the current milestone unless the acceptance criteria later
require real OS-level watcher verification outside unit and integration seams.

## Tradeoffs

- Sequential prompt processing is simpler and more predictable than concurrent
  execution, at the cost of throughput.
- In-memory queue state keeps the first milestone small, at the cost of not
  preserving duplicate-detection cache across daemon restarts.
- Separate daemon config avoids overloading `dormammu.json`, at the cost of one
  more file to manage.
- Explicit per-phase CLI blocks reduce ambiguity, at the cost of a longer
  config file.

## Open Questions

- Should `test_authoring` be added as a seventh daemon phase later, or is the
  user-intended five-stage development split expected to fold test authoring
  into `develop` for now?
- Should successful prompt files be moved to an archive directory after
  processing, or should they remain in place and rely only on result files?
- Should the daemon support config reload on `SIGHUP`, or is restart-based
  reconfiguration sufficient for the first milestone?

## Recommended Next Step

Implement in this order:

1. daemon config loader and validation
2. queue sort key and startup scan
3. polling watcher backend and integration tests
4. inotify backend behind the same watcher interface
5. result report rendering and CLI wiring
