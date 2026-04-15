Follow the Pipeline Stage Protocol from `AGENTS.md`.

Print `[[Committer]]` to standard output before any other action.

Before starting:

1. Read `.dev/DASHBOARD.md` and output its full content.
2. Read `.dev/PLAN.md` and output its full content.
3. Read `.dev/WORKFLOWS.md` and output its full content.
4. Then proceed with the commit task.

You are the committer.

Your job:

1. Inspect the working tree for the active scope only.
2. Stage only the intended files for this scope.
3. Create a git commit.

Commit message rules:

- English only.
- Title line must be 80 characters or fewer.
- Separate title and body with one blank line.
- Wrap body lines at 80 characters.
- End the message with a `Co-Authored-By:` trailer on its own line:
  ```
  Co-Authored-By: <Agent CLI Name> <noreply@company.com>
  ```
  Map the domain from the active CLI family:
  - `codex` → `openai.com`
  - `gemini` → `google.com`
  - `claude` → `anthropic.com`
  Use the stable CLI family label (e.g. `Claude`), not the model name.
  If the CLI identity is unavailable, stop and ask instead of guessing.
- Use a temporary message file or repeated `-m` flags — never embed
  raw `\n` escape sequences in a single shell string.
- After committing, verify the stored message with
  `git show --format=fuller --no-patch HEAD`.
- If this is **not** a goals-scheduler run, print as the very last
  output line:
  ```
  <promise>COMPLETE</promise>
  ```

Write all content in English.
