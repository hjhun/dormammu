# DASHBOARD

## Actual Progress

- Goal: Add explicit regression coverage for `daemonize` when phases run
  through Claude so Claude-specific failures are caught before operators hit
  them in queue mode.
- Prompt-driven scope: Verify that `daemonize` applies Claude's non-interactive
  defaults correctly, then use `~/samba/test` for a smoke-style verification
  path against the installed Claude CLI environment.
- Active roadmap focus:
- Phase 4. Supervisor Validation, Continuation Loop, and Resume
- Phase 5. CLI Operator Experience and Progress Visibility
- Current workflow phase: test_and_review
- Last completed workflow phase: develop
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: Claude-specific daemon invocation coverage is implemented and
  validated. Resume with a deeper daemon slice only if you want real
  authenticated Claude execution coverage beyond preset wiring.

## In Progress

- `tests/test_daemon.py` now includes a fake-Claude daemon regression that
  fails unless each daemon phase is launched with both `--print` and
  `--dangerously-skip-permissions`.
- Focused daemon validation passes with the new Claude coverage included, so
  daemon queue execution now has backend-specific regression protection for
  both Codex and Claude defaults.
- A smoke workspace was prepared at
  `/home/hjhun/samba/test/dormammu-daemonize-claude-smoke`, and `inspect-cli`
  there confirms the installed Claude binary is still recognized as the
  `claude_code` preset with `--print` command prefix support.

## Progress Notes

- Existing adapter tests already covered Claude preset behavior in isolation,
  and the new daemon regression closes the gap at the phase-runner layer where
  per-phase prompts and preset defaults are combined.
- `PYTHONPATH=backend python3 -m dormammu inspect-cli --repo-root
  /home/hjhun/samba/test/dormammu-daemonize-claude-smoke --agent-cli claude`
  reports `command_prefix=["--print"]` and the `claude_code` preset in the
  current environment.
- Focused validation passed with
  `python3 -m unittest tests.test_daemon.DaemonConfigTests.test_daemonize_claude_defaults_avoid_interactive_approval_when_extra_args_are_empty tests.test_daemon`.

## Risks And Watchpoints

- A fake-Claude regression test can prove command assembly, but it still will
  not guarantee real Claude authentication or quota health during daemon runs.
- A smoke path under `~/samba/test` can verify environment wiring, but it
  should stay lightweight enough not to depend on a paid long-running Claude
  session for every validation pass.
- The broader 50-iteration daemon continuation question remains separate from
  this Claude invocation coverage work.
