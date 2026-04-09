name: planning-agent
description: Creates or updates execution plans, milestones, and prompt-derived phase breakdowns for this project. Use when the user asks to plan work, expand a prompt into actionable phases, initialize `.dev/DASHBOARD.md`, or regenerate `.dev/PLAN.md`.
---

# Planning Agent Skill

Use this skill when the next useful action is planning rather than implementation.

Related skills:

- Prepare explicit handoffs for `designing-agent`
- Break out product-code work for `developing-agent`
- Break out test-code work for `test-authoring-agent`

## Inputs

- The user goal and constraints
- [PROJECT.md](../../../PROJECT.md)
- Existing `.dev/` state if present

## Workflow

1. Read the current goal, repo context, and any existing `.dev/DASHBOARD.md`, `.dev/PLAN.md`, and `.dev/workflow_state.json`.
2. Convert the goal into a small set of phases with clear completion signals.
3. Break the active phase into concrete tasks that can be checked off incrementally.
4. Split implementation work into product-code tasks and test-code tasks when both are needed.
5. Mark dependencies, risks, manual approvals, and resume checkpoints.
6. Update `.dev/DASHBOARD.md` with the real current progress, active phase, status, and next action.
7. Update `.dev/PLAN.md` with prompt-derived phase items using `[ ] Phase N. <title>` for pending work and `[O] Phase N. <title>` for completed work.

## Planning Rules

- Keep phases outcome-focused, not tool-focused.
- Prefer 4-8 top-level phase items for the active scope.
- Preserve existing completed work unless the state is clearly wrong.
- Treat `.dev/workflow_state.json` as machine truth and Markdown as human-readable status.
- If prior state is inconsistent, note the mismatch in the dashboard before changing tasks.
- Keep `DASHBOARD.md` focused on what is actually happening now, not a generic template summary.
- Keep `PLAN.md` focused on prompt-derived development work, not a mixed log of every note.

## Expected Outputs

- A refreshed `.dev/DASHBOARD.md`
- A refreshed or newly created `.dev/PLAN.md`
- A clear next phase and next task

## Done Criteria

This skill is complete when another agent can begin work without re-interpreting the user request.
