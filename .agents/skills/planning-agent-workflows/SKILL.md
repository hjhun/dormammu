---
name: planning-agent-workflows
description: Creates or updates execution plans, milestones, and task breakdowns for this project. Use when the user asks to plan work, expand a prompt into actionable phases, initialize `.dev/DASHBOARD.md`, or regenerate `.dev/TASKS.md`.
---

# Planning Agent Workflows

Use this skill when the next useful action is planning rather than implementation.

## Inputs

- The user goal and constraints
- [PROJECT.md](../../../PROJECT.md)
- Existing `.dev/` state if present

## Workflow

1. Read the current goal, repo context, and any existing `.dev/DASHBOARD.md`, `.dev/TASKS.md`, and `.dev/workflow_state.json`.
2. Convert the goal into a small set of phases with clear completion signals.
3. Break the active phase into concrete tasks that can be checked off incrementally.
4. Mark dependencies, risks, manual approvals, and resume checkpoints.
5. Update `.dev/DASHBOARD.md` with the current phase, status, and next action.
6. Update `.dev/TASKS.md` with `[ ]` for pending work and `[O]` for already completed work.

## Planning Rules

- Keep phases outcome-focused, not tool-focused.
- Prefer 4-8 top-level tasks for the active phase.
- Preserve existing completed work unless the state is clearly wrong.
- Treat `.dev/workflow_state.json` as machine truth and Markdown as human-readable status.
- If prior state is inconsistent, note the mismatch in the dashboard before changing tasks.

## Expected Outputs

- A refreshed `.dev/DASHBOARD.md`
- A refreshed or newly created `.dev/TASKS.md`
- A clear next phase and next task

## Done Criteria

This skill is complete when another agent can begin work without re-interpreting the user request.
