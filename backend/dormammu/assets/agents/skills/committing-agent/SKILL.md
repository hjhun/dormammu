---
name: committing-agent
description: Finalizes scoped changes into intentional git commits for this project. Use when the user asks to prepare a commit, stage completed work, write commit messages, or conclude a validated workflow phase in version control. Runs after all parallel development tracks have been merged and testing has passed.
---

# Committing Agent Skill

Use this skill only after the active scope has been implemented and validated,
or when the user explicitly asks for commit preparation. When parallel
development tracks were used, commit only after all tracks are complete and the
merge supervisor gate has passed.

Related skills:

- Require completed validation from `testing-and-reviewing`
- Expect any test-code changes from `test-authoring-agent` to be included or
  explicitly excluded by scope

## Inputs

- Current git status and diff (covering all merged tracks)
- The validated scope from `.dev`
- Any user constraints on commit boundaries

## Workflow

1. Print `[[Committer]]` to standard output.
2. Inspect the working tree and confirm which files belong to the active scope.
3. Ensure `.dev/DASHBOARD.md` shows the real completion status and
   `.dev/PLAN.md` shows the correct prompt-derived phase completion state
   before committing.
4. Stage only the intended files.
5. If intended `.dev` state files are ignored by Git, add them explicitly with
   `git add -f` instead of silently dropping them from scope.
6. Write a terse, accurate commit message that matches the actual diff.
7. Validate the commit message format before creating the commit:
   - Use this exact structure:
     ```text
     <subject>

     <body with no intentionally inserted blank lines inside the body>

     Co-Authored-By: <Agent CLI Name> <noreply@company.com>
     ```
   - Keep a subject line, a separate body, and the final
     `Co-Authored-By:` trailer.
   - Keep every line at 80 characters or fewer.
   - If a line would exceed 80 characters, wrap it onto the next line.
   - Use real line breaks, not escaped newline sequences such as `\n`.
   - Prefer a temporary message file or repeated `-m` flags over embedded
     escape sequences in a single shell string.
   - Do not insert blank lines inside the body just to separate paragraphs.
   - Set `Agent CLI Name` from the active agent CLI identity; do not use the
     selected model name in this trailer.
   - Prefer the stable CLI family label, for example `Codex`, `Gemini`, or
     `Claude`.
   - If the active agent CLI identity is unavailable, stop and ask instead of
     guessing.
   - Map `company.com` from the active CLI family:
     - `codex` → `openai.com`
     - `gemini` → `google.com`
     - `claude` → `anthropic.com`
   - Keep the `Co-Authored-By:` trailer exactly as
     `Co-Authored-By: <Agent CLI Name> <noreply@company.com>`.
   - Check the exact final message text line by line before `git commit`.
   - If any line is 81+ characters, rewrite and re-check before committing.
8. After committing, verify the stored message with
   `git show --format=fuller --no-patch HEAD`.
9. If this is **not** a goals-scheduler run, print the loop-completion signal
   as the very last line of output so the dormammu runtime stops the loop:
   ```
   <promise>COMPLETE</promise>
   ```
   Omit this signal when a goals-scheduler trigger is active (the
   evaluating-agent runs next and the runtime must not stop early).
10. Update `.dev` commit status intentionally:
    - Before the commit, `pending` is acceptable.
    - After the commit, record the real hash and summary in machine state when
      those files are part of the intended follow-up scope.
    - If recording the real hash would require changing the just-created
      commit, either amend intentionally or leave a documented follow-up
      instead of pretending the sync already happened.

## Commit Rules

- Never stage unrelated user changes silently.
- Keep commits aligned to one logical unit of work when possible.
- If validation is missing, stop and return to testing instead of forcing a
  commit.
- If the worktree is mixed, ask for scope clarification or stage explicit
  paths only.
- Treat ignored-but-required state files as an explicit staging decision, not
  an accidental omission.
- Before finalizing a commit, inspect the final message text as it will be
  stored by Git and wrap lines manually when needed.
- Treat the 80-character limit as a hard requirement for the subject and every
  body line with no exceptions.
- Treat the `Co-Authored-By:` trailer format and company-domain mapping as a
  hard requirement.

## Expected Outputs

- A scoped commit or a clear ready-to-commit state
- Updated `.dev` status showing commit progress
- A commit message that reflects the real change

## Done Criteria

This skill is complete when:
1. The requested commit is created (or the exact blocker is documented), and
2. `<promise>COMPLETE</promise>` has been printed as the final output line
   (non-goals-scheduler runs only).
