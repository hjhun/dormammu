# PLAN

## Prompt-Derived Implementation Plan

- [O] Phase 1. Refresh the active `.dev` workflow view for the SIGTERM shutdown
  investigation and capture the repro target
- [O] Phase 2. Reproduce the daemon shutdown failure with a real `daemonize`
  process while an active prompt is still running
- [O] Phase 3. Propagate daemon shutdown to the active agent subprocess without
  breaking resumable prompt handling
- [O] Phase 4. Add focused regression coverage for the interrupted daemon run
  path
- [O] Phase 5. Run targeted validation and repeat the manual integration repro,
  including the requested project under `~/samba/test`

## Resume Checkpoint

Implementation and requested verification are complete. Resume only if the user
requests commit preparation or additional shutdown hardening.
