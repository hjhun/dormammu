# DASHBOARD

## Actual Progress

- Goal: Install the distributed `agents/` bundle into `~/.dormammu/agents`,
  let runs fall back to it, and add command options for custom guidance files.
- Prompt-driven scope: Add guidance-file command options, embed guidance into
  run prompts, and use the installed or packaged bundle when repo guidance is
  absent.
- Active roadmap focus:
- Phase 7. Hardening, Multi-Session, and Productization
- Current workflow phase: test_and_review
- Last completed workflow phase: build_and_deploy
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: Validation is complete for guidance installation and fallback.
  Resume from optional cleanup, commit preparation, or the next scope.

## In Progress

- The install flow now copies packaged guidance into `~/.dormammu/agents`.
- CLI commands can accept repeatable `--guidance-file` paths to use explicit
  rule or agent Markdown files.
- `run` and `run-once` now embed resolved guidance content into the prompt sent
  to the external coding-agent CLI.

## Progress Notes

- Guidance resolution prefers explicit `--guidance-file` inputs, then repo
  guidance, then `~/.dormammu/agents`, then packaged assets.
- The installed and packaged guidance paths are both covered by tests.
- Validation passed with `python3 -m unittest tests.test_config
  tests.test_state_repository tests.test_cli tests.test_install_script`.
- A wheel built with `python3 -m pip wheel . --no-deps` contains the expected
  packaged guidance files.

## Risks And Watchpoints

- Custom install roots still need explicit `DORMAMMU_AGENTS_DIR` if the runtime
  guidance directory should differ from `~/.dormammu/agents`.
- The machine workflow state and operator-facing Markdown must stay aligned
  while the guidance fallback behavior evolves.
