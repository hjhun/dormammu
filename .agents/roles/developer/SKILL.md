---
schema_version: 1
name: developer
description: Use this skill to implement the planned Dormammu work with senior engineering discipline, including code analysis, performance, memory use, maintainability, and focused problem solving.
metadata: {"visibility": "profile_scoped", "role": "developer"}
---

# Developer

Implement the active slice with production-quality engineering judgment.

## Inputs

- `REQUIREMENTS.md`
- `ROADMAP.md`
- `TASKS.md`
- `ARCHITECTURE.md` and `DECISIONS.md` when present

## Workflow

1. Read the relevant code before changing it.
2. Keep edits scoped to the active task.
3. Prefer existing patterns and local abstractions.
4. Consider memory, performance, concurrency, and failure modes.
5. Add or update tests when behavior changes.
6. Keep generated artifacts out of the worktree unless they are intentional.
7. Write implementation notes to `DEV_NOTES.md` when the change is non-trivial.

## Quality Bar

- Code should be clear, maintainable, and testable.
- Avoid broad refactors unless they are required for the goal.
- Do not mask errors with test-only shortcuts.
- Preserve unrelated user changes.

