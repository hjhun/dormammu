# DASHBOARD

## Actual Progress

- Goal: Make `daemonize` create a fresh session per newly started prompt file
  and keep later prompt files pending until the earlier prompt is completed.
- Prompt-driven scope: Serialize daemon prompt execution, treat
  `waiting_for_plan` prompts as queue blockers, and prevent same-second session
  ID collisions across prompt-driven sessions.
- Active roadmap focus:
- Phase 5. CLI Operator Experience and Progress Visibility
- Phase 4. Supervisor Validation, Continuation Loop, and Resume
- Current workflow phase: commit
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The daemon queue/session change is implemented and validated.
  Resume from commit finalization and push for this daemonize behavior slice.

## In Progress

- `backend/dormammu/daemon/runner.py` now keeps daemon prompt processing to a
  single active prompt at a time. If multiple prompt files are ready, the first
  one starts and later ones remain pending until it fully finishes.
- `backend/dormammu/daemon/runner.py` now tracks `waiting_for_plan` prompts as
  active queue blockers. Once that session's `PLAN.md` becomes fully completed,
  the runner finalizes the blocked prompt result, removes the source prompt,
  and releases the next queued prompt.
- `backend/dormammu/state/repository.py` now guarantees unique generated
  session IDs even when multiple sessions are created within the same second,
  so daemon prompt files no longer collide onto the same session directory.

## Progress Notes

- Queue behavior changed from "process every ready file in one scan" to
  "consume one prompt, leave the rest pending, then come back after the active
  prompt is completed," which matches the requested serialized work model.
- Prompt-local session isolation is now covered by regression tests that verify
  different prompt files produce different session IDs even when they start in
  the same second.
- Validation passed with `python3 -m unittest tests.test_daemon` and
  `python3 -m unittest tests.test_cli tests.test_loop_runner`.

## Risks And Watchpoints

- Queue release for `waiting_for_plan` depends on the blocked session syncing
  operator state to `all_completed=true`; future changes to that contract need
  to keep the daemon release logic aligned.
- The external `daemonize` smoke path now naturally takes longer because each
  phase still inherits the previously added 5-second CLI cooldown, so
  end-to-end daemon tests need a larger timeout budget than before.
