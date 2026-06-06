---
schema_version: 1
name: committer
description: Use this skill after review approval to clean generated artifacts, stage only scoped changes, and create a disciplined commit with an 80-character line limit.
metadata: {"visibility": "profile_scoped", "role": "committer", "aliases": ["comitter"]}
---

# Committer

Prepare the validated work for version control.

## Inputs

- Git status and diff
- `REVIEW.md`
- `TEST_REPORT.md`
- Active scope from `DASHBOARD.md` and `TASKS.md`

## Workflow

1. Inspect the worktree.
2. Remove unneeded generated or temporary artifacts.
3. Stage only files that belong to the active scope.
4. Verify validation passed before committing.
5. Write a commit with:
   - subject line of 80 characters or fewer
   - blank line between subject and body
   - body lines of 80 characters or fewer
6. Verify the stored commit with `git show --format=fuller --no-patch HEAD`.

## Rules

- Never stage unrelated changes silently.
- Never push unless explicitly requested.
- If validation is missing or failed, route back to reviewer.

