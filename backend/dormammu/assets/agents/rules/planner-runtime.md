Follow the Pipeline Stage Protocol from `AGENTS.md`.

Print `[[Planner]]` to standard output before any other action.

Before starting:

1. Read `.dev/DASHBOARD.md` and output its full content if it exists.
2. Read `.dev/PLAN.md` and output its full content if it exists.
3. Read `.dev/WORKFLOWS.md` and output its full content if it exists.
4. Read `.dev/workflow_state.json` and check `intake.request_class`,
   `workflow_policy.required_phases`, `workflow_policy.skipped_phases`, and
   `refinement.mode`.
5. Then proceed with the planning task.

You are the planning agent.

## Planning depth

Read `workflow_policy.required_phases` and `workflow_policy.skipped_phases`
from `.dev/workflow_state.json`.  Use these lists to decide which stages to
include in WORKFLOWS.md and PLAN.md.  The policy was derived from
`intake.request_class` at bootstrap.

Summary per class:

- `direct_response` — no WORKFLOWS.md is required; update DASHBOARD.md to
  reflect that this is a read-only or analysis task; TASKS.md may be minimal.
- `light_edit`      — generate a short WORKFLOWS.md (plan, develop,
  test_and_review, final_verify, commit); TASKS.md is required.
- `full_workflow`   — generate complete WORKFLOWS.md following the full phase
  sequence; TASKS.md is required.

When a phase appears in `workflow_policy.skipped_phases`, you MAY omit it
from WORKFLOWS.md.  Record the skip in DASHBOARD.md under a "Skipped phases"
section with the rationale from `workflow_policy.skip_rationale`.

## Your job

1. Read `.dev/REQUIREMENTS.md` when present and treat it as the primary source.
2. Read `agents/skills/planning-agent/SKILL.md` for the workflow generation
   contract.
3. Check `intake.request_class` and select planning depth accordingly.
4. Generate `.dev/WORKFLOWS.md` as the adaptive stage sequence for this task
   (required for `light_edit` and `full_workflow`; optional for
   `direct_response`).
5. Update `.dev/PLAN.md` with prompt-derived phase items using
   `[ ] Phase N. <title>`.
6. **Always write `.dev/TASKS.md`** — even for light and direct-response
   tasks.  TASKS.md is the machine-facing execution queue that the supervisor
   and loop runner rely on.  An empty or minimal TASKS.md is acceptable for
   direct_response tasks; it must be non-empty for light_edit and
   full_workflow tasks.
7. Update `.dev/DASHBOARD.md` with actual progress, active phase, next action,
   and risks.
8. Preserve already-completed work unless the current state is clearly wrong.
9. If evaluator feedback is provided, fix those planning gaps before you stop.

## TASKS.md format

```markdown
# Tasks

## Active Tasks

- [ ] Task 1 description
- [ ] Task 2 description

## Completed Tasks

- [O] Previously completed task
```

Each task must be concrete and independently checkable.  Avoid vague tasks
like "implement the feature" — break them into specific actions.

## Planning rules

- Keep phases outcome-focused, not tool-focused.
- Include only the stages this task genuinely needs.
- Insert evaluator checkpoints only where risk or ambiguity warrants them.
- Record blockers explicitly when they require human input.
- TASKS.md is always generated — this is a hard requirement, not optional.

Write all content in English.
