# PLAN

## Prompt-Derived Implementation Plan

- [O] Phase 1. Read `AGENTS.md` and `agents/AGENTS.md`, inspect the saved run
  artifacts, and identify the real verification failure for the current
  interactive-shell rollout
- [O] Phase 2. Re-validate the no-arg shell entrypoint, explicit subcommand
  bypass, and install-script expectations against the current worktree
- [O] Phase 3. Update operator-facing docs for the default `dormammu` shell
  startup behavior and the new explicit `dormammu shell` entrypoint
- [O] Phase 4. Replace the stale root `.dev` operator-state files so the
  repository reflects the validated interactive-shell ship state
- [ ] Phase 5. Create one intentional commit for the interactive-shell rollout
  and push `main` to `origin/main`

## Resume Checkpoint

Resume from Phase 5 unless validation uncovers a regression that requires a
return to development.
