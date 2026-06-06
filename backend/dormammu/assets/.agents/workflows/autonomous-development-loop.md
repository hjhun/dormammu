# Autonomous Development Loop

Use this workflow for non-trivial Dormammu development.

## Stage Order

```text
analyzer -> refiner -> planner -> architect -> developer -> reviewer
         -> coordinator -> supervisor
```

## Stage Contracts

1. `analyzer` writes `ANALYSIS.md`.
2. `refiner` writes `REQUIREMENTS.md`.
3. `planner` writes `ROADMAP.md`, `DASHBOARD.md`, and `TASKS.md`.
4. `architect` writes `ARCHITECTURE.md` and `DECISIONS.md`.
5. `developer` implements the scoped slice and updates `DEV_NOTES.md`.
6. `reviewer` runs relevant unit, smoke, and e2e gates, then writes
   `TEST_REPORT.md` and `REVIEW.md`.
7. `coordinator` decides the next route and writes `COORDINATION.md`.
8. `supervisor` writes `SUPERVISOR_REPORT.md` and decides stop, continue,
   or blocked.

## Loop Rules

- If reviewer returns `NEEDS_WORK`, coordinator routes to the earliest role
  that can fix the issue.
- If supervisor returns `CONTINUE`, coordinator starts the next iteration.
- If supervisor returns `GOAL_ACHIEVED`, the loop stops.
- If supervisor returns `BLOCKED`, record the blocker and required input.

## Validation Gates

Run the relevant gates before supervisor approval:

- unit tests for changed logic
- smoke tests for executable flows
- e2e tests for user-facing or cross-process behavior

Record skipped gates with a concrete reason.

