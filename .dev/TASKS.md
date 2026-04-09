# TASKS

## Current Workflow

- [O] Re-open planning for the Phase 7 multi-session hardening slice and align
  `.dev` state with the new goal
- [O] Capture the design decision that per-session state lives only under
  `.dev/sessions/<session_id>/`
- [O] Refactor state writes so session runs never mirror `DASHBOARD.md`,
  `TASKS.md`, `session.json`, or `workflow_state.json` back into root `.dev`
- [O] Redefine root `.dev` as an index layer with active/default session
  pointers and multi-session summaries
- [O] Update CLI and recovery flows so commands resolve an explicit session
  target before reading or writing state
- [O] Add the dedicated `test_authoring` workflow skill and route repository
  guidance through it
- [ ] Refresh tests, operator docs, and `.dev` guidance for the no-mirror
  multi-session model

## Resume Checkpoint

Resume from docs follow-up and any extra validation gaps around the new
no-mirror multi-session model, keeping the `test_authoring` workflow stage
aligned across machine and operator state.

## Completion Rule

Do not mark a task complete until the implementation, `DASHBOARD.md`, and
`workflow_state.json` agree.
