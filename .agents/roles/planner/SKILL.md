---
schema_version: 1
name: planner
description: Use this skill after requirements are refined to produce ROADMAP.md, DASHBOARD.md, TASKS.md, and a resumable development plan that can drive repeated work loops.
metadata: {"visibility": "profile_scoped", "role": "planner"}
---

# Planner

Create a practical execution plan from refined requirements.

## Inputs

- `REQUIREMENTS.md`
- `ANALYSIS.md`
- Existing `.dev` state

## Workflow

1. Choose default loop or simple-task workflow based on scope and risk.
2. Split work into phases with concrete completion signals.
3. Break the active phase into actionable tasks.
4. Define validation gates for unit, smoke, and e2e testing.
5. Record dependencies, blockers, and rollback points.
6. Write or update `ROADMAP.md`, `DASHBOARD.md`, and `TASKS.md`.
7. Keep `DASHBOARD.md` focused on current status and next action.

## Output

Use these files:

- `ROADMAP.md`: phase sequence and completion signals
- `DASHBOARD.md`: active phase, status, risks, next action
- `TASKS.md`: checkable work items

