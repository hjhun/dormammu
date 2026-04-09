# DASHBOARD

## Workflow Summary

- Goal: Harden `dormammu` for multi-session execution without shared-state
  races in the root `.dev` view.
- Active delivery slice: Phase 7. Multi-session state model without root mirror
  writes
- Current workflow phase: test_and_review
- Last completed workflow phase: develop
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: Continue from validation or docs follow-up for the no-mirror
  multi-session slice

## Next Action

- Refresh operator docs for the new no-mirror multi-session model.
- Prepare the validated Phase 7 state-model slice for commit once docs are
  aligned.

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

## Active Roadmap Focus

- Phase 7. Hardening, Multi-Session, and Productization

## Risks And Watchpoints

- Existing tests assume root `.dev` contains the active session snapshot and
  will need to move toward explicit session-path assertions.
- Resume and restore flows must remain deterministic while the root `.dev`
  shape becomes thinner.
- Operator docs still need a pass so the new root index semantics are visible
  outside the tests and design notes.
