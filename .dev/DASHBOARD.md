# DASHBOARD

## Actual Progress

- Goal: Restore `daemonize` prompt discovery to `inotify`, add event-level
  watcher logs, preserve prompt files on `Ctrl+C`, gate completion on session
  `PLAN.md`, and allow requeued prompt filenames to replace stale completed
  result files.
- Prompt-driven scope: Revert the watcher back to `inotify` with per-event
  logging, fix the settle-window retry gap, preserve user prompts during
  interruption, expose `PLAN.md` completion in daemon result reports, and
  reprocess prompts when a matching completed result file already exists.
- Active roadmap focus:
- Phase 4. Supervisor Validation, Continuation Loop, and Resume
- Phase 5. CLI Operator Experience and Progress Visibility
- Phase 7. Hardening, Multi-Session, and Productization
- Current workflow phase: commit
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The `inotify`-based daemonize fix is implemented and validated.
  Resume from commit preparation and push for this daemon slice.

## In Progress

- `backend/dormammu/daemon/watchers.py` now uses `inotify` again for
  `auto`/`inotify` watcher selection on Linux, logs each raw watcher event,
  and keeps polling as the explicit compatibility fallback.
- `backend/dormammu/daemon/runner.py` now retries prompt scans after the
  settle window expires, replaces stale completed result files when the same
  prompt filename is requeued, keeps `PLAN.md` completion as the final
  completion gate, and preserves the source prompt file on `KeyboardInterrupt`.
- Focused validation passed with:
  `python3 -m unittest tests.test_daemon tests.test_tasks
  tests.test_supervisor`.
- Additional smoke validation passed with a real daemonize run under
  `~/samba/test/dormammu-daemonize-smoke`, including prompt detection,
  event-log output, settle-window retry, completed-result replacement, and
  `Ctrl+C` exit code `130`.

## Progress Notes

- Runtime watcher selection again prefers `inotify` on Linux when
  `watch.backend` is `auto`, and startup logs now report
  `replace_completed_result_on_requeued_prompt=yes`.
- Settle-window handling no longer deadlocks after `IN_CLOSE_WRITE`. When a
  prompt is too fresh, the daemon logs the defer reason, sleeps for the
  remaining window, and retries without requiring another filesystem event.
- Prompt completion is still not implied by phase exit codes alone. A daemon
  prompt is only marked `completed` when all configured phases exit cleanly and
  the synced session `PLAN.md` summary reports `all_completed=true`.
- A `Ctrl+C` raised during prompt processing now writes an `interrupted` result
  report, leaves the source prompt file in place, clears the in-progress
  marker, and re-raises so the CLI still exits with code `130`.

## Risks And Watchpoints

- Requeued prompts with the same filename now overwrite any stale completed
  result report before processing starts, so operators should not rely on the
  old result file remaining available once a replacement prompt is dropped.
- `waiting_for_plan` results are preserved in place so operators can inspect
  the pending PLAN task before deciding whether to rerun or continue the work
  manually.
