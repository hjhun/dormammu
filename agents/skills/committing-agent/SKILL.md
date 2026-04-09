name: committing-agent
description: Finalizes scoped changes into intentional git commits for this project. Use when the user asks to prepare a commit, stage completed work, write commit messages, or conclude a validated workflow phase in version control.
---

# Committing Agent Skill

Use this skill only after the active scope has been implemented and validated or when the user explicitly asks for commit preparation.

Related skills:

- Require completed validation from `testing-and-reviewing`
- Expect any test-code changes from `test-authoring-agent` to be included or explicitly excluded by scope

## Inputs

- Current git status and diff
- The validated scope from `.dev`
- Any user constraints on commit boundaries

## Workflow

1. Inspect the working tree and confirm which files belong to the active scope.
2. Ensure `.dev/DASHBOARD.md` shows the real completion status and `.dev/TASKS.md` shows the correct prompt-derived phase completion state before committing.
3. Stage only the intended files.
4. If intended `.dev` state files are ignored by Git, add them explicitly with
   `git add -f` instead of silently dropping them from scope.
5. Write a terse, accurate commit message that matches the actual diff.
6. Validate the commit message format before creating the commit:
   - keep a subject line and a separate body
   - keep every line at 80 characters or fewer
   - use real line breaks, not escaped newline sequences such as `\n`
   - prefer a temporary message file or repeated `-m` flags over embedded
     escape sequences in a single shell string
   - check the exact final message text line by line before `git commit`
   - if any line is 81+ characters, rewrite and re-check before committing
7. After committing, verify the stored message with `git show --format=fuller --no-patch HEAD`.
8. Update `.dev` commit status intentionally:
   - before the commit, `pending` is acceptable
   - after the commit, record the real hash and summary in machine state when
     those files are part of the intended follow-up scope
   - if recording the real hash would require changing the just-created commit,
     either amend intentionally or leave a documented follow-up instead of
     pretending the sync already happened

## Commit Rules

- Never stage unrelated user changes silently.
- Keep commits aligned to one logical unit of work when possible.
- If validation is missing, stop and return to testing instead of forcing a commit.
- If the worktree is mixed, ask for scope clarification or stage explicit paths only.
- Treat ignored-but-required state files as an explicit staging decision, not an
  accidental omission.
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
