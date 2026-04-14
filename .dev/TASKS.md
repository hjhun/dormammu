# TASKS

## Prompt-Derived Implementation Plan

- [O] Phase 1. Capture the active bug report, current workflow stage, and
  manual repro target in the root `.dev` state
- [O] Phase 2. Reproduce the failure by sending `SIGTERM` to `daemonize` during
  an in-flight prompt
- [O] Phase 3. Wire the daemon shutdown event into the active agent execution
  path and preserve interrupted prompt state
- [O] Phase 4. Add automated regression coverage for prompt interruption during
  daemon shutdown
- [O] Phase 5. Re-run focused validation and the requested manual integration
  scenario in `~/samba/test`

## Resume Checkpoint

The active task list is complete. Resume only if the user expands the scope.
