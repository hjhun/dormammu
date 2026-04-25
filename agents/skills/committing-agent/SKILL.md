---
name: committing-agent
description: Cleans up generated clutter, stages intended changes, and creates scoped local git commits for Dormammu. Use only after development, tester validation, reviewer approval, and supervisor final verification, or when the user explicitly asks for commit preparation. Push only when the user explicitly requested it.
---

# Committing Agent Skill

Use this skill to finalize a validated scope into version control. The common
misspelling `commiter` refers to this committer role.

## Inputs

- Validated implementation and test results.
- Reviewer verdict and supervisor final verification.
- Current git status and diff.
- User instructions about commit boundaries or push behavior.

## Workspace Persistence

Treat `.dev/...` paths as relative to the active prompt workspace from runtime
path guidance:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

Keep commit preparation notes and final state updates in that workspace.

## Workflow

1. Print `[[Committer]]`.
2. Inspect the working tree.
3. Remove unnecessary files generated during development when they are clearly
   in the active scope.
4. Confirm `.dev` state reflects validation, review, and final verification.
5. Stage only intended files.
6. Create a local commit using the existing project commit-message rules.
7. Verify the stored commit with `git show --format=fuller --no-patch HEAD`.
8. Push only when the user explicitly requested push behavior.
9. For non-goals-scheduler runs, print `<promise>COMPLETE</promise>` as the
   final output line when the runtime contract requires it.

## Commit Message Rules

Use the existing project format:

```text
<subject>

<body with no intentionally inserted blank lines inside the body>

Co-Authored-By: <Agent CLI Name> <noreply@company.com>
```

- English only.
- Subject and body lines must be 80 characters or fewer.
- Use the stable CLI family label, not a model name.
- Map CLI family domains: `codex -> openai.com`, `gemini -> google.com`,
  `claude -> anthropic.com`.
- Stop and ask if the active CLI identity is unavailable.

## Rules

- Never stage unrelated user changes silently.
- Do not commit without validation unless the user explicitly asks.
- Do not push without explicit user instruction.
- If the worktree is mixed, stage explicit paths only.

## Done Criteria

The skill is complete when a scoped local commit exists or the exact blocker is
recorded, and push behavior matches the user's explicit request.
