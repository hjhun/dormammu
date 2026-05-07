---
name: committer
description: Prepare a validated Dormammu scope for version control by cleaning generated clutter, staging only intended files, and creating a scoped local git commit. Use only after validation, review, and final verification, or when the user explicitly asks for commit preparation. Never push unless explicitly requested.
---

# Committer

## Purpose

Finalize completed work into a clean local commit while protecting unrelated
user changes. The committer is not a development stage; it stages only the
validated scope selected by the workflow.

The legacy packaged skill `committing-agent` is an alias for this role.

## Inputs

Read before committing:

- `.dev/REQUIREMENTS.md`
- `.dev/WORKFLOWS.md`
- `.dev/PLAN.md`
- `.dev/TASKS.md`
- `.dev/DESIGN.md` when present
- `.dev/DEVELOPMENT.md` when present
- tester and reviewer logs or progress files
- `.dev/DASHBOARD.md`
- `git status --short` and targeted diffs

If `.dev/WORKFLOWS.md` marks commit skipped or not required, do not commit
unless the user explicitly asks.

## Outputs

Write or refresh:

- a scoped local git commit
- `.dev/DASHBOARD.md`: committer status
- `.dev/logs/<date>_committer_<stem>.md` or runtime-specified stage log
- `.dev/progress/committer.md` when progress files are used

## Guardrails

- Commit only after validation and review pass, unless the user explicitly asks
  to commit an unvalidated state.
- Never stage unrelated local changes.
- Never revert unrelated user edits.
- Remove only obvious generated artifacts, build outputs, caches, logs, or
  temporary files created by the active work.
- If a file may be user work, preserve it and record the ambiguity.
- Do not amend or push unless explicitly requested.

## Workflow

1. Print `[[Committer]]` when acting as the runtime stage.
2. Read workflow state and final verification evidence.
3. Inspect the worktree with `git status --short` and targeted diffs.
4. Clean obvious generated clutter in the active scope.
5. Stage only intended files.
6. Write an English commit message from the actual diff.
7. Commit non-interactively.
8. Verify the commit with `git show --format=fuller --no-patch HEAD`.
9. Record the commit SHA and update `.dev` state.
10. Print `<promise>COMPLETE</promise>` as the final line only when the runtime
    contract requires loop termination for a non-goals-scheduler run.

## Commit Message Rules

Use this format:

```text
Detailed imperative subject under 80 characters

Detailed body line under 80 characters describing what changed and why.
Mention relevant implementation, tests, or cleanup in concise paragraphs.
```

When the active project commit contract requires a co-author line, use the
stable CLI family identity instead of a model name.

## Done Criteria

This skill is complete when a scoped local commit exists and the SHA is
recorded, or when the exact blocker preventing commit is recorded with the
intended staged scope.
