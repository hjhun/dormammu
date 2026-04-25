---
name: testing-and-reviewing
description: Runs validation and review-oriented checks after development. Use when the active implementation must be tested through unit, integration, smoke, user-scenario, lint, build, or review checks before final verification or commit. Prefer the dedicated `tester` and `reviewer` skills when those stages are split.
---

# Testing And Reviewing Skill

Use this combined skill when the workflow has a single validation/review phase.
When the workflow separates roles, use `tester` for executable scenario
validation and `reviewer` for code review.

## Inputs

- Completed implementation and authored tests.
- Requirements, plan, tasks, and design documents.
- Changed files and relevant project test commands.

## Workspace Persistence

Treat `.dev/...` paths as relative to the active prompt workspace from the
runtime path guidance:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

Write validation reports, review findings, and status updates inside that
workspace.

## Workflow

1. Print `[[Tester]]` or `[[Reviewer]]` according to the active stage.
2. Confirm development and test authoring are complete enough to validate.
3. Run relevant unit tests, integration tests, and smoke checks.
4. Add lint, build, or packaging checks when touched files justify them.
5. Execute user-scenario checks from requirements.
6. Review changed files for correctness, regressions, missed edges, memory
   risks, performance risks, and maintainability issues.
7. Record findings first; if none, state that clearly.
8. Update `.dev/DASHBOARD.md` and `.dev/PLAN.md` with the real outcome.

## Rules

- Do not claim checks passed unless they were actually run.
- Treat authored tests and executed validation as different evidence.
- If validation fails, route back to developer with reproduction evidence.
- If review finds issues, request developer changes before commit.
- Record unavailable environment, credentials, or tools as residual risk.

## Done Criteria

The skill is complete when validation and review have a clear pass, fail,
needs-work, blocked, or manual-review outcome in `.dev`.
