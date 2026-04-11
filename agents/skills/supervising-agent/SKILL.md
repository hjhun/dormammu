---
name: supervising-agent
description: Orchestrates planning, design, development, test authoring, build, validation, and commit phases for this project. Use when the user asks to monitor or supervise multi-step delivery, resume interrupted work, or decide the next workflow skill to apply.
---

# Supervising Agent Skill

Use this skill as the top-level controller for the project. It decides which workflow skill should act next, verifies state transitions, and resumes interrupted runs safely.

## Inputs

- The user goal
- [PROJECT.md](../../../.dev/PROJECT.md)
- Existing `.dev/DASHBOARD.md`, `.dev/PLAN.md`, and `.dev/workflow_state.json`
- Current repository and git state

## Orchestration Order

1. Planning
2. Designing
3. Developing
4. Test authoring
5. Building and deploying
6. Testing and reviewing
7. Final verification
8. Committing

Re-enter earlier phases whenever later work exposes missing design, failed validation, or incomplete planning.

## Workflow

1. Load the current `.dev` state and detect whether this is a new run or a resume.
2. Verify that the dashboard's actual-progress view, the task checklist, and machine state are consistent enough to continue.
3. Choose the next skill based on the active phase, blockers, and completion evidence.
4. After design, treat development and test authoring as paired implementation tracks when the scope needs both product code and test code.
5. Gate each transition with evidence:
   - planning -> tasks exist and the next action is clear
   - design -> interfaces or decisions exist for the active scope
   - development -> product-code implementation changed the intended files
   - test authoring -> unit and integration test code exists for the active scope, plus system tests when explicitly requested
   - build/deploy -> requested artifacts or scripts exist
   - test/review -> executed validation has a clear outcome after development is complete
   - final verification -> the completed slice passes one last operation-focused supervisor gate before commit preparation
   - commit -> diff scope and validation both support versioning
6. Do not advance from test authoring to test/review on authored tests alone; require executed evidence.
7. If final verification fails, identify the cause and route back to development when implementation changes are needed.
8. On interruption, preserve the last safe checkpoint and resume from the earliest uncertain step.
9. Update `.dev/DASHBOARD.md` with the real current phase, verdict, next action, escalation status, and other live progress context that matters for resuming work.

## Supervisor Rules

- Treat `.dev/workflow_state.json` as machine truth and Markdown as operator-facing state.
- Expect `.dev/DASHBOARD.md` to describe actual in-progress work for the active scope.
- Expect `.dev/PLAN.md` to list prompt-derived phase items in ordered checklist form.
- Prefer deterministic checks before semantic judgment.
- Do not advance phases on optimism alone.
- If state is inconsistent, record the mismatch and either repair it or require manual review.
- Keep the system resumable: every decision should leave enough context for the next run.

## Escalation Outcomes

- `approved`
- `rework_required`
- `blocked`
- `manual_review_needed`

## Done Criteria

This skill is complete when the next correct phase is explicit, the state is synchronized, and the project can continue without ambiguity.
