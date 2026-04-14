# TASKS

## Prompt-Derived Implementation Plan

- [O] Phase 1. Restore the implementation path to the approved evaluator
  design and remove reliance on large hardcoded runtime prompt bodies
- [O] Phase 2. Add source and packaged runtime rule assets under `agents/rules/`
  and wire the loader into the pipeline/evaluator stages
- [O] Phase 3. Keep mandatory evaluator behavior scoped to post-plan and
  goals-only post-commit contexts
- [O] Phase 4. Execute full-repository validation, diagnose failures, and fix
  the install-script loop harness regression

## Resume Checkpoint

The active implementation task is complete. Resume only if the user asks for
commit preparation or additional follow-up changes.
