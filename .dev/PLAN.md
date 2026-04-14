# PLAN

## Prompt-Derived Implementation Plan

- [O] Phase 1. Review the current evaluator, supervisor, and goals-scheduler
  roles and confirm the approved checkpoint architecture
- [O] Phase 2. Move one-shot runtime stage contracts into `agents/rules/` and
  mirror them into packaged assets
- [O] Phase 3. Implement the mandatory post-plan evaluator checkpoint and keep
  the goals-only post-commit evaluator aligned with the rules-based contract
- [O] Phase 4. Run the full repository test suite, fix regressions, and leave
  `.dev` state synchronized with the completed work

## Resume Checkpoint

Implementation and full validation are complete. Resume only if the user wants
commit preparation or additional hardening beyond this evaluator/rules scope.
