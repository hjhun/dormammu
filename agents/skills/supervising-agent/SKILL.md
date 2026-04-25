---
name: supervising-agent
description: Orchestrates planning, design, development, test authoring, testing, review, and commit phases for Dormammu. Use when a task spans refiner, planner, architect, developer, tester, reviewer, committer, or resume behavior; when state files need consistency checks; or when a failed/weak stage must be routed back for rework.
---

# Supervising Agent Skill

Use this skill as the controller for multi-step Dormammu work. The supervisor
checks each completed stage, decides whether the next stage may proceed, and
routes rework when evidence is weak.

## Inputs

- User goal and current prompt workspace.
- `.dev/DASHBOARD.md`, `.dev/PLAN.md`, `.dev/WORKFLOWS.md`,
  `.dev/TASKS.md`, and `.dev/workflow_state.json`.
- Stage reports, validation output, review findings, and git status.

## Workspace Persistence

Treat `.dev/...` paths as relative to the active prompt workspace from runtime
path guidance:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

The supervisor keeps that workspace authoritative for the current prompt. It
must keep dashboard, plan, tasks, workflows, logs, and machine state aligned.

## Stage Order

The supervisor manages these stages when the planner includes them:

1. Refiner
2. Planner
3. Architect / Designer
4. Developer
5. Test Author
6. Tester
7. Reviewer
8. Committer

After each stage, verify evidence before advancing. If evidence is missing,
incorrect, or low-confidence, route back to the responsible stage.

## Workflow

1. Print `[[Supervisor]]`.
2. Read current `.dev` state and detect new run vs resume.
3. Identify the earliest uncertain stage in `.dev/WORKFLOWS.md`.
4. Check the latest stage output against its done criteria.
5. Confirm state files agree with actual progress.
6. Route the next action:
   - back to refiner if requirements are incomplete
   - back to planner if workflow or tasks are unsafe
   - back to architect if design contracts are missing
   - back to developer if implementation or tests fail
   - back to tester if validation evidence is incomplete
   - back to reviewer if code review was not decisive
   - to committer only after final verification passes
7. Update dashboard, plan, workflows, and machine state.

## Gate Evidence

- Refiner complete: `.dev/REQUIREMENTS.md` has clear, verifiable criteria.
- Planner complete: workflow, plan, and task files exist and align.
- Architect complete: implementation contracts and quality tradeoffs are clear.
- Developer complete: code changes match requirements and tests exist.
- Tester complete: unit, integration, smoke, and user-scenario evidence is
  recorded; failures include reproduction steps.
- Reviewer complete: findings are resolved or explicitly accepted.
- Committer ready: diff scope, cleanup, validation, and review all support a
  local commit.

## Rules

- Prefer deterministic evidence before semantic judgment.
- Do not advance stages on optimism.
- Do not treat authored tests as executed validation.
- Preserve resumability after every decision.
- Keep the active prompt workspace as the source of operational truth.

## Done Criteria

The skill is complete when the next correct stage is explicit, state files are
consistent, and any rework path is assigned to the responsible role.
