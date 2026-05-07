---
name: planner
description: Create Dormammu execution plans and decide the task-specific workflow. Use after requirements refinement, or directly for a clear request, when `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, `.dev/TASKS.md`, validation strategy, skipped phases, supervisor gates, or downstream stage routing must be generated.
---

# Planner

## Purpose

The planner is the stage that actually decides the workflow. It turns
requirements into the adaptive phase sequence for the current task and records
that decision in `.dev/WORKFLOWS.md`. Later stages follow the workflow; they do
not invent a different one unless they route back to planning.

The legacy packaged skill `planning-agent` is an alias for this role.

## Inputs

Read before planning:

- `.dev/REQUIREMENTS.md` when present
- the original prompt when requirements are absent and the request is already clear
- `.dev/DASHBOARD.md`, `.dev/PLAN.md`, `.dev/WORKFLOWS.md`, and `.dev/TASKS.md`
  when present
- `.dev/workflow_state.json`, especially `intake.request_class`,
  `intake.execution_mode`, `workflow_policy.required_phases`,
  `workflow_policy.skipped_phases`, and `refinement.mode`
- `.dev/PROJECT.md`, `.dev/ROADMAP.md`, and repository conventions

Treat `.dev/...` paths as relative to the active prompt workspace from runtime
path guidance.

## Outputs

Write or refresh:

- `.dev/WORKFLOWS.md`: authoritative stage sequence for this task
- `.dev/PLAN.md`: phase checklist and execution plan
- `.dev/TASKS.md`: concrete machine-facing task queue
- `.dev/DASHBOARD.md`: active phase, next action, risks, and skipped phases
- `.dev/workflow_state.json`: planning decisions when available
- `.dev/logs/<date>_planner_<stem>.md` or the runtime-specified stage log

## Workflow Selection

Use `workflow_policy.required_phases` and `workflow_policy.skipped_phases` when
available. If policy state is absent, classify conservatively from the
requirements.

- `direct_response`: no implementation workflow is required; write a minimal
  dashboard and task record.
- `planning_only`: refine and plan only; use deeper reasoning in `.dev/PLAN.md`
  and skip developer/tester/reviewer/committer phases.
- `light_edit`: include plan, develop, validation/review, final verification,
  and commit only when commit is requested or runtime policy requires it.
- `full_workflow`: include the full downstream sequence needed by the scope.

Include only phases the task genuinely needs. Record every skipped phase with a
short rationale.

## Architect Decision

Add an architect/design stage when any of these apply:

- new module boundaries, public interfaces, or data contracts are needed
- state, recovery, resumability, compatibility, or migration behavior changes
- functional and non-functional requirements interact in non-obvious ways
- OOAD decisions are needed before coding
- multiple development tracks need shared ownership boundaries
- explicit quality-attribute tradeoffs are required

Skip architect only for bounded edits where the existing design already
dictates the change.

## WORKFLOWS.md Rules

Use `[ ]` for pending phases and `[O]` for completed phases. Never use `[x]`.
The supervisor reads these markers directly.

Example:

```markdown
# Workflows

## Task: <short task title>

Generated workflow for this task. Update checkboxes as each stage completes.

[O] Phase 0. Refine - refiner
[O] Phase 1. Plan - planner
[ ] Phase 2. Architect - architect
[ ] Phase 3. Develop - developer
[ ] Phase 4. Test Author - test-authoring-agent
[ ] Phase 5. Tester - tester
[ ] Phase 6. Reviewer - reviewer
[ ] Phase 7. Final Verification - coding-workflow
[ ] Phase 8. Commit - committer

## Skipped Phases

| Phase | Rationale |
| --- | --- |
| evaluator | Not needed for a low-risk interactive change. |
```

Rules:

- Mark the Plan phase `[O]` after this skill finishes successfully.
- Keep Commit last when it is included.
- Insert evaluator checkpoints only for public interface changes, ambiguous
  acceptance criteria, high-risk state behavior, or multi-track work.
- For goals-scheduler prompts, include the required post-plan and final
  evaluator checkpoints according to runtime policy.
- Always write `.dev/TASKS.md`, even if it is minimal.

## PLAN.md Format

```markdown
# Plan

## Source Inputs
- Requirements:
- Workflow policy:

## Assumptions
- ...

## Scope
- In scope:
- Out of scope:

## Phase Checklist
- [O] Phase 0. Refine
- [O] Phase 1. Plan
- [ ] Phase 2. Architect

## Workflow Decisions
| Stage | Decision | Rationale | Evidence |
| --- | --- | --- | --- |

## Validation Strategy
- Unit:
- Integration:
- Smoke:
- System:

## Risks And Blockers
- ...
```

## TASKS.md Format

```markdown
# Tasks

## Active Tasks
- [ ] <concrete independently checkable task>

## Completed Tasks
- [O] <completed task>
```

## Rules

- Keep the plan traceable to requirements.
- Prefer the simplest workflow that satisfies the task.
- Do not add speculative features or broad refactors.
- Treat authored tests and executed validation as different phases.
- Record blockers instead of inventing missing requirements.
- If downstream evidence proves the workflow is wrong, route back to planner
  and regenerate `.dev/WORKFLOWS.md`.

## Done Criteria

This skill is complete when `.dev/WORKFLOWS.md`, `.dev/PLAN.md`,
`.dev/TASKS.md`, and `.dev/DASHBOARD.md` let the supervisor identify the next
stage without re-planning.
