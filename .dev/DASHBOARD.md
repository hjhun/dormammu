# DASHBOARD

## Actual Progress

- Goal: Make `dormammu` bootstrap new runs from `PROMPT.md`, generate
  `DASHBOARD.md` and `PLAN.md`, persist a prompt copy per session, and resume
  the previous session when only `resume` is provided.
- Prompt-driven scope: Replace legacy `TASKS.md` planning with `PLAN.md`,
  persist `PROMPT.md` into session state, mirror the prompt under
  `~/.dormammu/sessions/<session id>/.dev/`, and keep `resume` aligned with the
  saved active session.
- Active roadmap focus:
- Phase 4. Supervisor Validation, Continuation Loop, and Resume
- Phase 7. Hardening, Multi-Session, and Productization
- Current workflow phase: test_and_review
- Last completed workflow phase: build_and_deploy
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: Validation passed for the prompt-driven PLAN bootstrap slice.
  Resume from docs cleanup, commit preparation, or the next user-directed scope.

## In Progress

- `run` and `run-once` now derive initial bootstrap state from the incoming
  prompt, create `PLAN.md`, and persist `PROMPT.md` into the session state.
- Session prompt copies are mirrored under
  `~/.dormammu/sessions/<session id>/.dev/PROMPT.md`.
- Loop progress snapshots now show `PLAN.md` instead of `TASKS.md`, while
  legacy `TASKS.md` content is still migrated forward for compatibility.

## Progress Notes

- State schema advanced to version 5 so the operator-facing plan source now
  points at `PLAN.md`.
- The bootstrap repository layer can upgrade legacy `TASKS.md` snapshots into
  `PLAN.md` without losing prior checklist state.
- Validation passed with `python3 -m unittest tests.test_tasks
  tests.test_state_repository tests.test_cli tests.test_loop_runner
  tests.test_supervisor tests.test_agent_cli_adapter tests.test_config`.

## Risks And Watchpoints

- Older sessions may still contain legacy `TASKS.md`; the runtime now migrates
  them, but docs and guidance need to stay consistently on `PLAN.md`.
- JSON consumers that read the bootstrap artifacts may still rely on the legacy
  `tasks` key, so compatibility aliases remain in place for now.
