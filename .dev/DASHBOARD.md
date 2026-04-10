# DASHBOARD

## Actual Progress

- Goal: Update `dormammu` so omitted `--cwd` work defaults to the current
  directory, and add a repo-level `.session` marker that links `run` and
  `resume` to the same session automatically.
- Prompt-driven scope: Default agent workdir resolution to `Path.cwd()`,
  create and maintain a repo `.session` marker, make `run` reuse that marker
  or start a new session when it is missing, and make `resume` honor the same
  marker before the root `.dev` active-session index.
- Active roadmap focus:
- Phase 3. Agent CLI Adapter and Single-Run Execution
- Phase 4. Supervisor Validation, Continuation Loop, and Resume
- Phase 5. CLI Operator Experience and Progress Visibility
- Current workflow phase: test_and_review
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The `.session` marker and current-directory workdir slice is
  implemented and validated. Resume from commit preparation or from follow-up
  operator docs around the new session marker flow.

## In Progress

- `run-once`, `run`, and `inspect-cli` now resolve external agent workdir to
  the current shell directory when users do not pass `--workdir`.
- `run`, `resume`, `init-state`, `start-session`, and `restore-session` now
  write the active session id to a repo-level `.session` file.
- `run` now starts a fresh session when `.session` is absent instead of
  silently reusing the root `.dev` active session, while `resume` prefers the
  repo marker before the root session index.

## Progress Notes

- The CLI now keeps the repo-local `.session` file aligned whenever the active
  session changes through bootstrap, session switching, or run/resume flows.
- Focused automated validation passed for `tests.test_agent_cli_adapter` and
  `tests.test_cli`.
- Added regression tests for default current-directory `cwd` forwarding, repo
  `.session` creation and reuse, new-session creation when the marker is
  missing, and `resume` preferring `.session` over the root `.dev` index.

## Risks And Watchpoints

- The repo `.session` file now becomes part of the operator-facing state, so
  we may want to document or ignore it explicitly if local session markers
  should stay untracked.
- Existing runs now persist the resolved current directory into loop request
  state, which changes the forwarded `--cwd` behavior for tools such as
  `cline` when `--workdir` was omitted previously.
