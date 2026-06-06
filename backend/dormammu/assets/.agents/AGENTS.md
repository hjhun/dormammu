# Dormammu Agent Instructions

This `.agents/` directory is the distributable workflow guidance bundle for
automated development loops across Codex, Claude, agy(Antigravity), and Cline.

## Default Loop

Use the default loop for non-trivial development:

```text
analyzer -> refiner -> planner -> architect -> developer -> reviewer
         -> coordinator -> supervisor
```

The supervisor decides whether the goal is complete. The coordinator routes
failed or incomplete work back to the earliest stage that can resolve it.

## Simple Tasks

For simple, low-risk tasks, use `.agents/workflows/simple-task.md`. Do not
force heavyweight planning for typo fixes, small documentation edits, or
single-file configuration updates.

## Validation

Before completion, run the relevant validation gates:

- unit tests for local logic
- smoke tests for executable flows
- e2e tests for user-facing or cross-process behavior

If a gate is not relevant or cannot run in the current environment, record the
reason in `TEST_REPORT.md` or `SUPERVISOR_REPORT.md`.

## State

Keep operator-readable state current:

- `GOAL.md`
- `ANALYSIS.md`
- `REQUIREMENTS.md`
- `ROADMAP.md`
- `DASHBOARD.md`
- `TASKS.md`
- `ARCHITECTURE.md`
- `DECISIONS.md`
- `DEV_NOTES.md`
- `TEST_PLAN.md`
- `TEST_REPORT.md`
- `REVIEW.md`
- `COORDINATION.md`
- `SUPERVISOR_REPORT.md`
- `workflow_state.json`
