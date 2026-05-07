# Refine And Plan Workflow

Use this workflow when a new request or goal arrives and needs to be clarified
before planning begins, or when an already-refined scope needs its planning
state refreshed before design starts. This is the entry point for every
non-trivial task.

## Covers

- Phase 0. Refine
- Phase 1. Plan

## Skills To Use

- `skills/refiner/SKILL.md`
- `skills/planner/SKILL.md`

## Sequence

1. Start with `skills/refiner/SKILL.md` to convert the raw user request
   into a structured `.dev/REQUIREMENTS.md`. Ask clarifying questions, confirm
   scope boundaries, and define verifiable acceptance criteria.
2. Move to `skills/planner/SKILL.md` once requirements are confirmed.
3. The planner reads `.dev/REQUIREMENTS.md` and generates:
   - `.dev/WORKFLOWS.md` — the adaptive, task-specific stage sequence with
     checkboxes for this task
   - `.dev/PLAN.md` — the phase and task checklist for implementation
   - `.dev/DASHBOARD.md` — current status and next action
4. If the active scope already has clear requirements, skip
   `skills/refiner/SKILL.md` and enter this workflow at planning.
5. After planning, hand off to `skills/architect/SKILL.md` when the
   implementation still needs interface, contract, or recovery decisions before
   code changes begin.
6. Route back to refining if the planner surfaces ambiguities that the
   requirements document did not resolve.

## When To Skip Refining

Skip `refiner` and go directly to `planner` when:

- The request is a simple, well-scoped fix (e.g., "rename this variable",
  "update this config value").
- The user has already provided explicit acceptance criteria.
- `.dev/REQUIREMENTS.md` was recently produced and is still accurate.

## Outputs

- `.dev/REQUIREMENTS.md` with refined, unambiguous requirements
- `.dev/WORKFLOWS.md` with the planner-selected adaptive stage sequence for this task
- `.dev/PLAN.md` with the phase checklist
- `.dev/DASHBOARD.md` with current status and next action
- A clear handoff into the design phase when implementation decisions are still
  needed
