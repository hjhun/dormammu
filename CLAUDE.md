# CLAUDE.md

## Project Overview

`dormammu` is a Python-based coding agent loop orchestrator.

- CLI-only interface (no Web UI)
- Markdown state management under `.dev/` directory
- Resumable execution
- Supervisor-driven validation

## Source Of Truth

Determine the next action in this priority order:

1. Direct user request
2. `.dev/PROJECT.md`
3. `.dev/ROADMAP.md`
4. Current `.dev/WORKFLOWS.md` stage sequence
5. Current `.dev` execution state files
6. Current repository contents

## Skill Routing

All substantive implementation work is performed through the workflows and
skills in the `agents/` bundle.

### When To Use Which Workflow Or Skill

| Situation | Workflow / Skill |
|-----------|-----------------|
| New request with unclear scope or acceptance criteria | `agents/workflows/refine-plan.md` |
| Requirements clear, need planning refresh before design | `agents/workflows/refine-plan.md` (skip refining when not needed) |
| Implementation ready (code + tests) | `agents/workflows/develop-test-authoring.md` |
| Build / deploy / validation / final review needed | `agents/workflows/build-deploy-test-review.md` |
| Final validation passed, commit ready | `agents/workflows/cleanup-commit.md` |
| Multi-stage task or next workflow unclear | `agents/skills/supervising-agent/SKILL.md` |

### Skill Path Reference

- Refine: `agents/skills/refining-agent/SKILL.md`
- Planning: `agents/skills/planning-agent/SKILL.md`
- Design: `agents/skills/designing-agent/SKILL.md`
- Development: `agents/skills/developing-agent/SKILL.md`
- Test Authoring: `agents/skills/test-authoring-agent/SKILL.md`
- Build and Deploy: `agents/skills/building-and-deploying/SKILL.md`
- Test and Review: `agents/skills/testing-and-reviewing/SKILL.md`
- Commit: `agents/skills/committing-agent/SKILL.md`
- Supervision: `agents/skills/supervising-agent/SKILL.md`
- Evaluation: `agents/skills/evaluating-agent/SKILL.md`

## Required Workflow Sequence

Substantive work must follow this base sequence. The planning agent generates
the exact adaptive sequence in `.dev/WORKFLOWS.md` after requirements are
refined.

```
0. Refine      → agents/skills/refining-agent/SKILL.md
1. Plan        → agents/skills/planning-agent/SKILL.md
                  ↳ generates .dev/WORKFLOWS.md (adaptive stage sequence)
2. Design      → agents/skills/designing-agent/SKILL.md
3. Develop     → agents/skills/developing-agent/SKILL.md         ↓ parallel
4. Test Author → agents/skills/test-authoring-agent/SKILL.md     ↑ parallel
5. [Evaluator check — if WORKFLOWS.md includes a mid-pipeline checkpoint]
6. Build/Deploy → agents/skills/building-and-deploying/SKILL.md  (if packaging needed)
7. Test/Review  → agents/skills/testing-and-reviewing/SKILL.md
8. Final Verify → supervising-agent final gate
9. Commit       → agents/skills/committing-agent/SKILL.md
                  ↳ emit <promise>COMPLETE</promise> after a successful commit
                    (goals-scheduler active: skip signal, proceed to step 10)
10. [Evaluate  → agents/skills/evaluating-agent/SKILL.md — goals-scheduler only]
```

- The supervisor is the controller for all multi-stage implementations.
- Develop and Test Authoring run as parallel tracks after Design.
- Validation runs only after the active implementation slice is complete.
- Default validation scope: unit tests + integration tests. System tests only
  when explicitly requested.
- `.dev/WORKFLOWS.md` is the authoritative stage sequence for the current task.
  Stages not listed in WORKFLOWS.md are skipped.

## Phase Gate Rules (Supervisor Transition Conditions)

Each phase transition requires evidence:

- `refine → plan`: `.dev/REQUIREMENTS.md` exists and is confirmed by operator
- `plan → design`: WORKFLOWS.md and PLAN.md exist; next action is clear
- `design → develop`: Interface or decision exists for the active scope
- `develop → test_author`: Product code changes exist in intended files
- `test_author → test_review`: Unit/integration test code exists (execution
  evidence required — written tests alone do not satisfy this gate)
- `test_review → final_verify`: Executed validation has clear results
- `final_verify → commit`: Completed slice passed final operational verification
- `commit`: Diff scope and validation both support version control
- `commit → done`: After a successful commit the committing-agent emits
  `<promise>COMPLETE</promise>` so the dormammu runtime stops the loop.
  Exception: when a goals-scheduler trigger is active, omit the signal and
  proceed to the final `evaluating-agent` step instead.

If a mid-pipeline evaluator checkpoint is in WORKFLOWS.md:
- `DECISION: PROCEED` from evaluating-agent → advance to next stage
- `DECISION: REWORK` from evaluating-agent → route back to the indicated stage

## `.dev` State Management

Keep these files synchronized throughout the workflow:

| File | Role |
|------|------|
| `.dev/REQUIREMENTS.md` | Refined, unambiguous requirements from refining-agent |
| `.dev/WORKFLOWS.md` | Adaptive stage sequence for the current task (generated by planning-agent) |
| `.dev/DASHBOARD.md` | Current progress, active phase, next action, risks |
| `.dev/PLAN.md` | Prompt-derived phase checklist (`[ ] Phase N. <title>`) |
| `.dev/TASKS.md` | Development items for the current scope |
| `.dev/workflow_state.json` | Machine state (source of truth) |
| `.dev/session.json` | Session context |
| `.dev/logs/` | Execution logs |

- `.dev/workflow_state.json` is machine truth; Markdown files are
  operator-facing state.
- Checklist format: pending `[ ] Phase N. <title>`, completed `[O] Phase N. <title>`
- This same format applies to both `PLAN.md` and `WORKFLOWS.md`.

## Resume Behavior

When resuming after an interruption:

1. Read current `.dev` state.
2. Verify dashboard, tasks, WORKFLOWS.md, and machine state are consistent.
3. Identify the earliest uncertain stage.
4. Do not assume later stages are valid; resume from the identified stage.

## Roadmap Priority

Execute in this order unless the user changes priorities:

1. Phase 1. Core Foundation and Repository Bootstrap
2. Phase 2. `.dev` State Model and Template Generation
3. Phase 3. Agent CLI Adapter and Single-Run Execution
4. Phase 4. Supervisor Validation, Continuation Loop, and Resume
5. Phase 5. CLI Operator Experience and Progress Visibility
6. Phase 6. Installer, Commands, and Environment Diagnostics
7. Phase 7. Hardening, Multi-Session, and Productization

## Default Agent Posture

When working in this repository:

- Mark the active stage explicitly.
- Use the mapped workflow skill for the current stage.
- Reference adjacent workflow skills when handoff or collaboration is needed.
- The supervisor decides stage transitions.
- Keep progress visible in `.dev/`, especially in `WORKFLOWS.md`.
- Prefer deterministic checks before semantic judgment.
- Preserve resumability at every stage.
