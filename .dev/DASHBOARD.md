# DASHBOARD

## Actual Progress

- Goal: Improve `daemonize` runtime visibility so operators can tell how prompt
  files are detected and where child CLI output is surfaced when the queue
  worker starts.
- Prompt-driven scope: Add startup and execution logs that explain prompt
  detection rules, watcher settings, and stdout/stderr behavior for daemonized
  CLI runs.
- Active roadmap focus:
- Phase 5. CLI Operator Experience and Progress Visibility
- Phase 6. Installer, Commands, and Environment Diagnostics
- Current workflow phase: commit
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The daemonize visibility slice is implemented and validated.
  Resume from optional commit preparation or a docs follow-up if the startup
  logs should also be documented.

## In Progress

- `daemonize` now emits a startup banner that shows the repo root, daemon
  config path, watched prompt/result directories, resolved watcher backend, and
  prompt detection rules.
- Each detected prompt now logs its queue sort key, and each phase launch logs
  the CLI path, workdir, concrete command, and prompt/stdout/stderr artifacts
  before execution.
- The runtime messaging explicitly states that child CLI stdout and stderr are
  mirrored live to parent `stderr` and also archived under `.dev/logs/`.

## Progress Notes

- Runtime inspection shows prompt candidates are discovered from `prompt_path`,
  filtered by `queue.allowed_extensions` and `ignore_hidden_files`, skipped when
  a matching result file already exists, and delayed by `watch.settle_seconds`
  before execution.
- Prompt processing order is already deterministic: leading numeric prefixes are
  processed first, then alphabetic prefixes, then the remaining names.
- Focused validation passed for `python3 -m unittest tests.test_daemon`.
- Regression coverage now asserts both the startup banner content and the
  prompt/phase execution logs written to stderr.

## Risks And Watchpoints

- New progress logs need to stay faithful to runtime behavior, otherwise the
  daemon could become more confusing rather than less.
- Startup messaging should help operators quickly, but it should avoid flooding
  stderr on every idle poll loop.
- If prompt detection rules change later, the new banner text and regression
  tests will need to be updated together.
