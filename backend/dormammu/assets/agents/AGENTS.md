# AGENTS.md

## Purpose

This `agents/` directory is the distributable workflow guidance bundle for
`dormammu`.

It packages:

- reusable workflow documents under `workflows/`
- reusable skill documents under `skills/`
- a stable entry document for agents that need to decide what to use next

Use this directory when `dormammu` is shipped, installed, or copied into
another environment and the workflow guidance must travel with it.

## How To Use This Directory

Start here, then route to the matching workflow document:

- `workflows/refine-plan.md`
- `workflows/planning-design.md`
- `workflows/develop-test-authoring.md`
- `workflows/build-deploy-test-review.md`
- `workflows/cleanup-commit.md`

Use `skills/supervising-agent/SKILL.md` as the top-level controller whenever
the task spans multiple phases or the next workflow is not obvious.

## Pipeline Overview

Every non-trivial task follows this sequence. The exact stages active for a
given task are recorded in `.dev/WORKFLOWS.md` after planning completes.

```
refine → plan → design → develop + test-author → test-review → commit → evaluate
             ↑                    ↑                    ↑
        supervisor gates between each phase; evaluator checkpoints as needed
```

Stages are not fixed. The planning agent generates an adaptive workflow in
`.dev/WORKFLOWS.md` that includes only the stages the task actually needs and
inserts evaluator checkpoints where complexity or risk warrants them.

## Workflow Routing

### Refine And Plan

Use `workflows/refine-plan.md` when:

- a new request or goal arrives
- the scope or acceptance criteria are unclear before planning begins
- `.dev/REQUIREMENTS.md` needs to be created or refreshed

This workflow uses:

- `skills/refining-agent/SKILL.md`
- `skills/planning-agent/SKILL.md`

### Planning And Design

Use `workflows/planning-design.md` when:

- requirements are already refined and `.dev/REQUIREMENTS.md` exists
- `.dev` state needs to be refreshed from an existing plan
- design decisions are needed before implementation

This workflow uses:

- `skills/planning-agent/SKILL.md`
- `skills/designing-agent/SKILL.md`

### Development And Test Authoring

Use `workflows/develop-test-authoring.md` when:

- the active slice is ready for implementation
- product code and test code need to move together

This workflow uses:

- `skills/developing-agent/SKILL.md`
- `skills/test-authoring-agent/SKILL.md`

### Build Deploy And Test Review

Use `workflows/build-deploy-test-review.md` when:

- packaging or deployability checks are required
- executed validation is required after development
- the completed slice needs one final supervisor verification pass before commit prep

This workflow uses:

- `skills/building-and-deploying/SKILL.md`
- `skills/testing-and-reviewing/SKILL.md`

### Cleanup And Commit

Use `workflows/cleanup-commit.md` when:

- unnecessary files in the active scope should be cleaned up
- the final-verified scope is ready for staging or commit preparation

This workflow uses:

- `skills/committing-agent/SKILL.md`

## Naming Convention

The distributable skill names under `skills/` do not use the old
`-workflows` postfix.

Use these skill names:

- `refining-agent`
- `planning-agent`
- `designing-agent`
- `developing-agent`
- `test-authoring-agent`
- `building-and-deploying`
- `testing-and-reviewing`
- `committing-agent`
- `supervising-agent`
- `evaluating-agent`

## Pipeline Stage Protocol

At the start of every pipeline stage (tester, reviewer, committer, evaluator),
the agent must:

1. Read `.dev/DASHBOARD.md` and output its full content.
2. Read `.dev/PLAN.md` and output its full content.
3. Read `.dev/WORKFLOWS.md` and output its full content.
4. Then proceed with the stage task.

This makes the current workflow state visible in each stage's stored output
document, so operators can track progress across the full pipeline without
inspecting state files separately.

## Evaluator Checkpoint Protocol

When `.dev/WORKFLOWS.md` contains a mid-pipeline evaluator checkpoint, the
supervisor must:

1. Confirm the preceding stage is complete (evidence present in `.dev/`).
2. Invoke `skills/evaluating-agent/SKILL.md` in mid-pipeline check mode.
3. Read the checkpoint report from `.dev/07-evaluator/check_<stage>_<date>.md`.
4. If `DECISION: PROCEED` — advance to the next stage.
5. If `DECISION: REWORK` — route back to the stage indicated in the report.

## Notes

- Keep workflow paths and skill paths relative to `agents/`.
- Treat these documents as the portable copy intended to ship with
  `dormammu`.
- When repository-specific rules exist outside this directory, use them
  alongside this bundle rather than replacing them.
- `.dev/WORKFLOWS.md` is generated per task by the planning agent. It is the
  authoritative process map for what stages will run and where evaluator
  checkpoints are placed.
