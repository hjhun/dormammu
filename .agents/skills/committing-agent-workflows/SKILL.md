---
name: committing-agent-workflows
description: Finalizes scoped changes into intentional git commits for this project. Use when the user asks to prepare a commit, stage completed work, write commit messages, or conclude a validated workflow phase in version control.
---

# Committing Agent Workflows

Use this skill only after the active scope has been implemented and validated or when the user explicitly asks for commit preparation.

## Inputs

- Current git status and diff
- The validated scope from `.dev`
- Any user constraints on commit boundaries

## Workflow

1. Inspect the working tree and confirm which files belong to the active scope.
2. Ensure `.dev/DASHBOARD.md` and `.dev/TASKS.md` reflect the current completion state before committing.
3. Stage only the intended files.
4. Write a terse, accurate commit message that matches the actual diff.
5. Validate the commit message format before creating the commit:
   - keep a subject line and a separate body
   - keep every line at 80 characters or fewer
   - use real line breaks, not escaped newline sequences such as `\n`
   - check the exact final message text line by line before `git commit`
   - if any line is 81+ characters, rewrite and re-check before committing
6. Record the commit hash or pending-commit status in `.dev/DASHBOARD.md`.

## Commit Rules

- Never stage unrelated user changes silently.
- Keep commits aligned to one logical unit of work when possible.
- If validation is missing, stop and return to testing instead of forcing a commit.
- If the worktree is mixed, ask for scope clarification or stage explicit paths only.
- Before finalizing a commit, inspect the final message text as it will be
  stored by Git and wrap lines manually when needed.
- Treat the 80-character limit as a hard requirement for the subject and every
  body line with no exceptions.

## Expected Outputs

- A scoped commit or a clear ready-to-commit state
- Updated `.dev` status showing commit progress
- A commit message that reflects the real change

## Done Criteria

This skill is complete when the requested commit is created or the exact blocker to committing is documented.
