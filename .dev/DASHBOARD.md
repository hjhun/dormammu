# DASHBOARD

## Actual Progress

- Goal: Fix `daemonize` prompt watching so Linux `inotify` reliably notices a
  prompt once the writer closes it, with inode-backed readiness events as the
  primary mechanism.
- Prompt-driven scope: Root-cause the missed write-close detection, correct the
  watcher behavior, and add regression coverage for both close-write and
  move-into-place prompt delivery.
- Active roadmap focus:
- Phase 4. Supervisor Validation, Continuation Loop, and Resume
- Phase 5. CLI Operator Experience and Progress Visibility
- Current workflow phase: test_and_review
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The Linux `inotify` watcher fix is implemented and validated.
  Resume from commit preparation only if this daemon slice should be versioned
  now.

## In Progress

- `backend/dormammu/daemon/watchers.py` now watches only readiness events on
  Linux instead of waking early on `IN_CREATE`.
- The inotify event parser now filters emitted paths through the same readiness
  mask so only fully materialized prompts are surfaced to the runner.
- Focused validation passed with
  `python3 -m unittest tests.test_daemon.InotifyWatcherTests
  tests.test_daemon.DaemonRunnerTests tests.test_daemon.DaemonConfigTests`.

## Progress Notes

- Root cause: the watcher subscribed to `IN_CREATE`, `IN_MOVED_TO`, and
  `IN_CLOSE_WRITE`, but `wait_for_changes()` drained all queued events at once
  and returned immediately on creation. When `settle_seconds` was still active,
  the runner skipped the too-new file and then blocked again after the already
  consumed close-write event, leaving the prompt stranded until some unrelated
  future filesystem event arrived.
- Fix direction: Linux now prioritizes inode readiness signals only,
  specifically `IN_CLOSE_WRITE` for directly written files and `IN_MOVED_TO`
  for atomically renamed files.
- Targeted daemon validation now proves the watcher blocks until
  `IN_CLOSE_WRITE` and still accepts `IN_MOVED_TO` for atomically staged
  prompts.

## Risks And Watchpoints

- The new regression coverage is Linux-specific by design because the product
  explicitly runs on Linux, so non-Linux watcher semantics remain out of scope.
- Polling fallback behavior is unchanged; any future prompt-staleness issues in
  polling mode should be treated as a separate slice from this inode-event fix.
