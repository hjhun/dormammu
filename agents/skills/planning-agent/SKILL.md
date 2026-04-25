---
name: planning-agent
description: Creates execution plans from refined user requirements. Use when a request needs phases, `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, `.dev/TASKS.md`, supervisor gates, optional architect routing, validation strategy, or a resumable prompt-workspace plan before implementation starts.
---

# Planning Agent Skill

Use this skill when the next useful action is planning. After requirements
refinement, it decides how the work should proceed and records the plan in the
active prompt workspace.

Related skills:

- Consume `.dev/REQUIREMENTS.md` from `refining-agent`.
- Route to `designing-agent` or `architect` when architecture/design is needed.
- Route implementation to `developing-agent`.
- Route test code to `test-authoring-agent`.
- Expect supervision by `supervising-agent` after every major stage.

## Inputs

- `.dev/REQUIREMENTS.md` when present, otherwise the original prompt.
- `.dev/PROJECT.md`, `.dev/ROADMAP.md`, and current `.dev` state.
- Repository structure and existing workflow conventions.

## Workspace Persistence

Treat `.dev/...` paths as relative to the operational state directory from the
runtime path guidance. New prompt work should live under:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

Write `WORKFLOWS.md`, `PLAN.md`, `TASKS.md`, dashboard updates, and any plan
logs inside that active prompt workspace.

## Workflow

1. Print `[[Planner]]`.
2. Read refined requirements first; fall back to the original prompt only when
   requirements are absent.
3. Classify the work depth from `workflow_policy` when available.
4. Decide whether an architect/design stage is needed.
5. Define phases with completion evidence and supervisor gates.
6. Define concrete tasks and dependencies.
7. Define the validation plan: unit, integration, smoke, and optional system
   tests.
8. Generate `.dev/WORKFLOWS.md` with only the stages this task needs.
9. Generate or refresh `.dev/TASKS.md`.
10. Refresh `.dev/PLAN.md` with prompt-derived phase checklist items.
11. Refresh `.dev/DASHBOARD.md` with active phase, next action, risks, and
    skipped-phase rationale.

## When To Route To Architect

Add `designing-agent` / `architect` after planning when any of these apply:

- New module boundaries, data contracts, or public interfaces are needed.
- Functional and non-functional requirements interact in non-obvious ways.
- OOAD decisions are needed before implementation.
- ISO-style quality attributes need explicit tradeoff analysis.
- Multiple development tracks need shared contracts or file ownership rules.
- The implementation touches state, recovery, resumability, or compatibility.

Skip architect only for clearly bounded edits where the existing design already
dictates the change.

## WORKFLOWS.md Rules

- Use `[ ]` for pending and `[O]` for completed.
- Include supervisor gates after completed stages that need evidence review.
- Include evaluator checkpoints only when risk or ambiguity warrants them.
- Keep commit last for normal interactive runs.
- Record skipped phases with a short rationale.

Example:

```markdown
# Workflows

## Task: <short task title>

[O] Phase 0. Refine - refining-agent
[O] Phase 1. Plan - planning-agent
[ ] Phase 2. Architect - designing-agent
[ ] Phase 3. Supervisor gate
[ ] Phase 4. Develop - developing-agent
[ ] Phase 5. Test Author - test-authoring-agent
[ ] Phase 6. Tester - tester
[ ] Phase 7. Reviewer - reviewer
[ ] Phase 8. Supervisor gate
[ ] Phase 9. Commit - committing-agent
```

## TASKS.md Rules

- Each task must be concrete and independently checkable.
- Split parallel tracks only when file ownership and dependencies are clear.
- Include development, test-authoring, and validation tasks when relevant.
- Avoid vague items like "implement the feature."

## Done Criteria

The skill is complete when another agent can start the next phase from
`.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and `.dev/TASKS.md` without re-planning
the user's request.
