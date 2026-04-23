---
name: planning-agent
description: Creates or updates execution plans, adaptive workflow sequences, and parallel development tracks for this project. Use when the user asks to plan work, break a goal into phases, initialize `.dev/DASHBOARD.md`, regenerate `.dev/PLAN.md`, split implementation into parallel tracks, or determine the correct agent sequence for a task.
---

# Planning Agent Skill

Use this skill when the next useful action is planning rather than implementation.
Planning runs after requirement refinement and before design.

Related skills:

- Expect refined input from `refining-agent` via `.dev/REQUIREMENTS.md`
- Prepare explicit handoffs for `designing-agent`
- Break out product-code work for `developing-agent` (one agent per parallel track)
- Break out test-code work for `test-authoring-agent` (one agent per parallel track)

## Inputs

- `.dev/REQUIREMENTS.md` from `refining-agent` (preferred) or the raw user goal
- [PROJECT.md](../../../.dev/PROJECT.md) if present
- Existing `.dev/` state if present

## Workflow

1. Print `[[Planner]]` to standard output.
2. Read `.dev/REQUIREMENTS.md` if it exists; fall back to the raw user goal and
   constraints if not.
3. Read any existing `.dev/DASHBOARD.md`, `.dev/PLAN.md`, and
   `.dev/workflow_state.json`.
4. Check `workflow_policy.required_phases` and `workflow_policy.skipped_phases`
   in `.dev/workflow_state.json` to determine which stages this task needs.
   Use the skip rationale from `workflow_policy.skip_rationale` to explain
   omitted stages in DASHBOARD.md.
5. Convert the goal into a small set of phases with clear completion signals.
6. Break the active phase into concrete tasks. **Identify parallel development
   tracks** (see "Parallel Development Track Splitting" below) when the scope
   warrants it.
7. Mark dependencies, risks, manual approvals, and resume checkpoints.
8. **Generate `.dev/WORKFLOWS.md`** — an adaptive, task-specific workflow that
   describes the exact sequence of agents, tracks, and checkpoints for this
   task (see format below). Include only phases that appear in
   `workflow_policy.required_phases`.
9. **Always write `.dev/TASKS.md`** — required for all workflow depths. Use
   track sections when parallel tracks are defined.
10. Update `.dev/DASHBOARD.md` with the real current progress, active phase,
    status, next action, parallel track summary (if any), and a "Skipped
    phases" section listing any omitted stages with their rationale.
11. Update `.dev/PLAN.md` with prompt-derived phase items using
    `[ ] Phase N. <title>` for pending work and `[O] Phase N. <title>` for
    completed work.

## Parallel Development Track Splitting

When the development scope is large enough, split implementation into
independent tracks so multiple developer agents can work in parallel without
blocking each other.

### When to split into parallel tracks

Split when **two or more** of the following are true:

- The development scope covers clearly distinct sub-domains (e.g., CLI layer
  and runtime engine, schema changes and API layer, frontend component and
  backend endpoint).
- Tasks in one sub-domain do not depend on in-progress work from another.
- Each track can be implemented, tested, and verified independently.
- The total task list for a single developer would span more than ~6 tasks.

Do **not** split when:
- Tasks are tightly sequential (Track B cannot start until Track A's types
  or interfaces are stable).
- The scope is small enough for one developer to finish cleanly in a single
  pass.

### How to define tracks

1. Identify the natural seam — the module boundary, layer boundary, or data
   flow boundary where tasks are independent.
2. Assign each task to exactly one track. A task belongs to the track where
   most of its file changes live.
3. Name each track with a short domain label (e.g., "Track A: CLI adapter",
   "Track B: runtime engine").
4. Record inter-track dependencies explicitly: if Track B requires a type or
   interface exported by Track A, list that as a dependency and note that Track
   B cannot start until Track A publishes the interface.

### TASKS.md format with parallel tracks

```markdown
# Tasks

## Track A: <domain name>

- [ ] A1. <task>
- [ ] A2. <task>

## Track B: <domain name>

- [ ] B1. <task>
- [ ] B2. <task>

## Track A ↔ Track B dependency note
<Any interface or type that Track B needs from Track A before it can start>
```

If no parallel split is needed, use the flat task list format instead:

```markdown
# Tasks

- [ ] 1. <task>
- [ ] 2. <task>
```

## WORKFLOWS.md Generation

`WORKFLOWS.md` is the operator-facing process map for the current task. It is
**not** a fixed template — generate it to fit the actual work:

- Include only the stages this task genuinely needs.
- Insert evaluator checkpoints where the task complexity or risk warrants them
  (see checkpoint guidance below).
- Omit stages that are clearly unnecessary (e.g., skip build/deploy if no
  packaging is required).
- Use `[ ]` for pending steps and `[O]` for completed steps.
- When parallel tracks are defined, list each track as a separate phase line
  inside the parallel block.

### WORKFLOWS.md Format — single track (no split)

```markdown
# Workflows

## Task: <short task title>

Generated workflow for this task. Update checkboxes as each stage completes.

[ ] Phase 0. Refine — refining-agent
[O] Phase 1. Plan — planning-agent
[ ] Phase 2. Design — designing-agent
[ ] Phase 3. Supervisor gate
[ ] Phase 4. Develop — developing-agent           ↓ parallel
[ ] Phase 5. Test Author — test-authoring-agent   ↑ parallel
[ ] Phase 6. Supervisor gate
[ ] Phase 7. Test and Review — testing-and-reviewing
[ ] Phase 8. Supervisor gate
[ ] Phase 9. Commit — committing-agent
               ↳ supervisor stops loop here
```

### WORKFLOWS.md Format — parallel development tracks

```markdown
# Workflows

## Task: <short task title>

Generated workflow for this task. Update checkboxes as each stage completes.

[ ] Phase 0. Refine — refining-agent
[O] Phase 1. Plan — planning-agent
[ ] Phase 2. Design — designing-agent
[ ] Phase 3. Supervisor gate
[ ] Phase 4. Develop (Track A: <domain>) — developing-agent    ↓ parallel
[ ] Phase 5. Develop (Track B: <domain>) — developing-agent    ↕ parallel
[ ] Phase 6. Test Author (Track A) — test-authoring-agent      ↕ parallel
[ ] Phase 7. Test Author (Track B) — test-authoring-agent      ↑ parallel
[ ] Phase 8. Supervisor gate (merge tracks)
[ ] Phase 9. Test and Review — testing-and-reviewing
[ ] Phase 10. Supervisor gate
[ ] Phase 11. Commit — committing-agent
                ↳ supervisor stops loop here
```

Add an evaluator checkpoint before the merge gate when any of these apply:

- The task modifies a public interface, API contract, or shared data schema.
- The task spans more than two development phases.
- The requirements include ambiguous acceptance criteria that should be verified
  before committing.
- The supervisor flags uncertainty about whether the implementation matches the
  refined requirements.

Do **not** add a final `evaluating-agent` step for manually-invoked runs —
the supervisor stops the loop after commit. A final evaluator is added only
when the goals-scheduler is explicitly active.

## Planning Rules

- Keep phases outcome-focused, not tool-focused.
- Prefer 4–8 top-level phase items for the active scope.
- Preserve existing completed work unless the state is clearly wrong.
- Treat `.dev/workflow_state.json` as machine truth and Markdown as
  human-readable status.
- If prior state is inconsistent, note the mismatch in the dashboard before
  changing tasks.
- Keep `DASHBOARD.md` focused on what is actually happening now, including
  which tracks are active and their independent status.
- Keep `PLAN.md` focused on prompt-derived development work.
- Keep `WORKFLOWS.md` focused on the process sequence, not task content.

## Expected Outputs

- A generated or refreshed `.dev/WORKFLOWS.md` (with parallel tracks when
  applicable)
- A generated or refreshed `.dev/TASKS.md` (with track sections when
  applicable)
- A refreshed `.dev/DASHBOARD.md`
- A refreshed or newly created `.dev/PLAN.md`
- A clear next phase and next task (or next track set)

## Done Criteria

This skill is complete when another agent can begin work without
re-interpreting the user request, the workflow sequence is visible in
`.dev/WORKFLOWS.md`, and any parallel tracks are clearly defined with
independent task lists and dependency notes.
