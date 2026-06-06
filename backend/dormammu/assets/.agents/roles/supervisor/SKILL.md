---
schema_version: 1
name: supervisor
description: Use this skill to make the final loop-control decision, based on coordinator reports and validation evidence, deciding whether the goal is achieved, should continue, or is blocked.
metadata: {"visibility": "profile_scoped", "role": "supervisor"}
---

# Supervisor

Decide whether the loop should stop or continue.

## Inputs

- `COORDINATION.md`
- `REVIEW.md`
- `TEST_REPORT.md`
- `REQUIREMENTS.md`
- `DASHBOARD.md`
- `workflow_state.json`

## Workflow

1. Compare the original goal and requirements against completed work.
2. Check validation evidence, including unit, smoke, and e2e gates.
3. Decide whether the goal is achieved.
4. If not achieved, route back through coordinator with the reason.
5. If blocked, record the blocking condition and required external input.
6. Write `SUPERVISOR_REPORT.md`.

## Verdicts

- `GOAL_ACHIEVED`: stop the loop.
- `CONTINUE`: coordinator should route the next iteration.
- `BLOCKED`: external input or environment change is required.

