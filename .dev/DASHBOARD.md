# DASHBOARD

## Actual Progress

- Goal: Repair `codex` CLI execution so dormammu can run in non-trusted
  working directories without failing before the agent starts.
- Prompt-driven scope: Diagnose the `Not inside a trusted directory and
  --skip-git-repo-check was not specified.` failure, update the Codex preset to
  pass the skip flag only when supported, and add regression coverage.
- Active roadmap focus:
- Phase 3. Agent CLI Adapter and Single-Run Execution
- Phase 5. CLI Operator Experience and Progress Visibility
- Phase 7. Hardening, Multi-Session, and Productization
- Current workflow phase: test_and_review
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The Codex trusted-directory fix is implemented and validated.
  Resume from commit preparation or from broader Codex compatibility follow-up.

## In Progress

- The Codex preset now injects `--skip-git-repo-check` only when the installed
  `codex` binary advertises support for that flag in `codex exec --help`.
- Default preset arguments are now applied after CLI capability inspection so
  dormammu can gate Codex-specific compatibility flags on the real installed
  CLI version.
- Regression coverage now verifies both the supported-flag path and the
  explicit no-duplication path for Codex invocations.

## Progress Notes

- Focused automated validation passed for `python3 -m unittest
  tests.test_agent_cli_adapter tests.test_command_builder tests.test_help_parser`.
- Broader CLI/config regression validation passed for `python3 -m unittest
  tests.test_cli tests.test_config`.
- Manual Codex reproduction confirmed the failure without
  `--skip-git-repo-check` and confirmed that `codex exec --skip-git-repo-check`
  proceeds past the trusted-directory guard.

## Risks And Watchpoints

- Older Codex builds that do not advertise `--skip-git-repo-check` still run
  through the legacy path because dormammu now gates that flag on the help
  output instead of assuming universal support.
- This slice fixes the startup guard only; any later Codex runtime warnings
  from local user state such as OAuth/keyring or state DB migration issues
  remain outside dormammu's command-building layer.
