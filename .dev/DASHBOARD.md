# DASHBOARD

## Actual Progress

- Goal: Ensure repository-root `DORMAMMU.log` is created only for explicit
  debug runs.
- Prompt-driven scope: Add `--debug` gating for project log capture on runtime
  commands and update regression coverage plus docs to match.
- Active roadmap focus:
- Phase 5. CLI Operator Experience and Progress Visibility
- Current workflow phase: test_and_review
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `not_needed`
- Resume point: Runtime commands now gate project log capture behind `--debug`.
  Resume from commit preparation only if a follow-up asks for version-control
  finalization.

## In Progress

- `run-once`, `run`, `resume`, and `daemonize` now accept `--debug` to enable
  repository-root `DORMAMMU.log` capture.
- Default runtime behavior no longer creates `DORMAMMU.log` unless debug
  logging is requested.

## Progress Notes

- `.dev/logs/` session artifacts remain unchanged; this scope only targets the
  repository-root mirrored stderr log.
- Install-script regression coverage now opts into `--debug` so packaged smoke
  tests continue to exercise project-log creation intentionally.
- Validation passed with `python3 -m unittest tests.test_cli tests.test_install_script`.

## Risks And Watchpoints

- Existing operator habits may assume `DORMAMMU.log` appears automatically, so
  docs and help text need to stay explicit about the new `--debug` contract.
- Commands without `--debug` still print progress to stderr; only the mirrored
  repository-root log file is suppressed by default.
