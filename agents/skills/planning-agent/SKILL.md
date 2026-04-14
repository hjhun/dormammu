---
name: planning-agent
description: Creates or updates execution plans, milestones, and prompt-derived phase breakdowns for this project. Use when the user asks to plan work, expand a prompt into actionable phases, initialize `.dev/DASHBOARD.md`, or regenerate `.dev/PLAN.md`.
---

# Planning Agent Skill

Use this skill when the next useful action is planning rather than implementation.
Planning runs after requirement refinement and before design.

Related skills:

- Expect refined input from `refining-agent` via `.dev/REQUIREMENTS.md`
- Prepare explicit handoffs for `designing-agent`
- Break out product-code work for `developing-agent`
- Break out test-code work for `test-authoring-agent`

## Inputs

- `.dev/REQUIREMENTS.md` from `refining-agent` (preferred) or the raw user goal
- [PROJECT.md](../../../.dev/PROJECT.md) if present
- Existing `.dev/` state if present

## Workflow

1. Read `.dev/REQUIREMENTS.md` if it exists; fall back to the raw user goal and
   constraints if not.
2. Read any existing `.dev/DASHBOARD.md`, `.dev/PLAN.md`, and
   `.dev/workflow_state.json`.
3. Convert the goal into a small set of phases with clear completion signals.
4. Break the active phase into concrete tasks that can be checked off
   incrementally.
5. Split implementation work into product-code tasks and test-code tasks when
   both are needed.
6. Mark dependencies, risks, manual approvals, and resume checkpoints.
7. **Generate `.dev/WORKFLOWS.md`** — an adaptive, task-specific workflow that
   describes the exact sequence of agents and checkpoints for this task (see
   format below).
8. Update `.dev/DASHBOARD.md` with the real current progress, active phase,
   status, and next action.
9. Update `.dev/PLAN.md` with prompt-derived phase items using
   `[ ] Phase N. <title>` for pending work and `[O] Phase N. <title>` for
   completed work.

## WORKFLOWS.md Generation

`WORKFLOWS.md` is the operator-facing process map for the current task. It is
**not** a fixed template — generate it to fit the actual work:

- Include only the stages this task genuinely needs.
- Insert evaluator checkpoints where the task complexity or risk warrants them
  (see checkpoint guidance below).
- Omit stages that are clearly unnecessary (e.g., skip build/deploy if no
  packaging is required).
- Use `[ ]` for pending steps and `[O]` for completed steps, the same as
  `PLAN.md`.

### WORKFLOWS.md Format

```markdown
# Workflows

## Task: <short task title>

Generated workflow for this task. Update checkboxes as each stage completes.

[ ] Phase 0. Refine — refining-agent
[O] Phase 1. Plan — planning-agent
[ ] Phase 2. Design — designing-agent
[ ] Phase 3. Supervisor gate
[ ] Phase 4. Develop — developing-agent  ↓ parallel
[ ] Phase 5. Test Author — test-authoring-agent  ↑ parallel
[ ] Phase 6. Supervisor gate
[ ] Phase 7. Test and Review — testing-and-reviewing
[ ] Phase 8. Supervisor gate
[ ] Phase 9. Evaluator check — evaluating-agent (mid-pipeline)
[ ] Phase 10. Commit — committing-agent
[ ] Phase 11. Evaluate — evaluating-agent (final)
```

### Evaluator Checkpoint Guidance

Add a mid-pipeline `evaluating-agent` checkpoint when any of these apply:

- The task modifies a public interface, API contract, or shared data schema.
- The task spans more than two development phases.
- The requirements include ambiguous acceptance criteria that should be verified
  before committing.
- The supervisor flags uncertainty about whether the implementation matches the
  refined requirements.

A final `evaluating-agent` step is always included at the end of the workflow.

## Planning Rules

- Keep phases outcome-focused, not tool-focused.
- Prefer 4–8 top-level phase items for the active scope.
- Preserve existing completed work unless the state is clearly wrong.
- Treat `.dev/workflow_state.json` as machine truth and Markdown as
  human-readable status.
- If prior state is inconsistent, note the mismatch in the dashboard before
  changing tasks.
- Keep `DASHBOARD.md` focused on what is actually happening now.
- Keep `PLAN.md` focused on prompt-derived development work.
- Keep `WORKFLOWS.md` focused on the process sequence, not task content.

## Expected Outputs

- A generated or refreshed `.dev/WORKFLOWS.md`
- A refreshed `.dev/DASHBOARD.md`
- A refreshed or newly created `.dev/PLAN.md`
- A clear next phase and next task

## Done Criteria

This skill is complete when another agent can begin work without re-interpreting
the user request and the workflow sequence is visible in `.dev/WORKFLOWS.md`.
