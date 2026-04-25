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
2. Remove unnecessary generated files that were created during development and
   clearly belong to this scope.
3. Confirm validation, review, and supervisor final verification are complete.
4. Stage only the intended files for this scope.
5. Create a local git commit.
6. Push only when the user explicitly requested push behavior.

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

Store all operational outputs under the active prompt workspace described by
the runtime path guidance. New prompt runs should resolve under:
`~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/`.

Write all content in English.
