# DASHBOARD

## Workflow Summary

- Goal: Harden `dormammu` for multi-session execution without shared-state
  races in the root `.dev` view.
- Active delivery slice: Phase 7. Multi-session state model without root mirror
  writes
- Current workflow phase: commit
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: Continue from workflow guidance and docs follow-up for the
  no-mirror multi-session slice

## Next Action

- Keep `.dev` and workflow state aligned with the new `test_authoring` phase
  and dedicated test-skill guidance.
- Refresh operator docs for the new no-mirror multi-session model.
- Latest commit for the workflow guidance update: `pending amend`.
- Prepare any remaining docs follow-up as a separate scope if needed.

## Notes

- This file is the operator-facing dashboard.
- `workflow_state.json` remains machine truth.
- The current mirror-based active root view is safe for one active session but
  becomes race-prone when multiple sessions write concurrently.
- The chosen design keeps session Markdown and machine state under
  `.dev/sessions/<session_id>/` and limits root `.dev` to pointers, summaries,
  and shared logs or indexes.
- Development should preserve backward-readable state where reasonable, but new
  writes should stop treating root `.dev/DASHBOARD.md` and `.dev/TASKS.md` as
  canonical session documents.
- The implementation now auto-creates a session during bootstrap, keeps
  per-session logs under session-local `logs/`, and switches `restore-session`
  by pointer instead of snapshot copy.
- Repository workflow guidance now treats test authoring as a dedicated phase
  between design and executed validation.
- Commit guidance now explicitly covers ignored `.dev` files, stored commit
  message verification, and post-commit state handling.

## Active Roadmap Focus

- Phase 7. Hardening, Multi-Session, and Productization

## Risks And Watchpoints

- Existing tests assume root `.dev` contains the active session snapshot and
  will need to move toward explicit session-path assertions.
- Resume and restore flows must remain deterministic while the root `.dev`
  shape becomes thinner.
- Operator docs still need a pass so the new root index semantics are visible
  outside the tests and design notes.
- The machine workflow state and operator-facing Markdown must stay aligned
  while the new test-authoring phase is introduced.
