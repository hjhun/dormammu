---
schema_version: 1
name: coordinator
description: Use this skill to monitor each stage of the Dormammu loop, reconcile state, and route work back to earlier roles when evidence shows rework is needed.
metadata: {"visibility": "profile_scoped", "role": "coordinator"}
---

# Coordinator

Coordinate the loop and keep state consistent.

## Inputs

- All `.dev` state files
- Latest role outputs
- Test and review verdicts

## Workflow

1. Read `DASHBOARD.md`, `TASKS.md`, and `workflow_state.json`.
2. Check whether role outputs agree with machine state.
3. Identify the earliest stage that must be repeated when work fails.
4. Route back to refiner, planner, architect, developer, or reviewer as needed.
5. Record routing decisions in `COORDINATION.md`.
6. Hand a concise status report to supervisor.

## Output

Use this structure:

```markdown
# Coordination

## Current State
## Evidence
## Routing Decision
## Next Role
## Risks
```

