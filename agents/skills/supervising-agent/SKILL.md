---
name: supervising-agent
description: Orchestrates planning, design, development, test authoring, build, validation, and commit phases for this project. Use when the user asks to monitor or supervise multi-step delivery, resume interrupted work, manage parallel development tracks, or decide the next workflow skill to apply.
---

# Supervising Agent Skill

Use this skill as the top-level controller for the project. It decides which
workflow skill should act next, verifies state transitions, coordinates
parallel development tracks, and resumes interrupted runs safely.

## Inputs

- The user goal
- [PROJECT.md](../../../.dev/PROJECT.md)
- Existing `.dev/DASHBOARD.md`, `.dev/PLAN.md`, `.dev/WORKFLOWS.md`, and
  `.dev/workflow_state.json`
- Current repository and git state

## Orchestration Order

1. Planning
2. Designing
3. Developing (and Test Authoring — parallel tracks when defined)
4. Building and deploying (when packaging is needed)
5. Testing and reviewing
6. Final verification
7. Committing

Re-enter earlier phases whenever later work exposes missing design, failed
validation, or incomplete planning.

## Workflow

1. Print `[[Supervisor]]` to standard output.
2. Load the current `.dev` state and detect whether this is a new run or a resume.
3. Verify that the dashboard's actual-progress view, the task checklist, and
   machine state are consistent enough to continue.
4. Read `.dev/WORKFLOWS.md` to determine whether parallel development tracks
   are defined for the current task.
5. Choose the next skill based on the active phase, blockers, and completion
   evidence:
   - **No parallel tracks**: advance through the standard single-track sequence.
   - **Parallel tracks defined**: coordinate track-level agents independently.
     Each track's develop + test-author pair runs without waiting for the other
     track. Advance to the merge supervisor gate only when all tracks are
     complete and verified.
6. Gate each transition with evidence:
   - planning → tasks and WORKFLOWS.md exist; next action is clear
   - design → interfaces or decisions exist for the active scope
   - development → product-code changes exist in the intended files for each
     active track
   - test authoring → unit and integration tests exist for the active scope,
     plus system tests when explicitly requested
   - build/deploy → requested artifacts or scripts exist
   - test/review → executed validation has a clear outcome after development
     is complete for all tracks
   - final verification → the completed slice passes one last operation-focused
     gate before commit preparation
   - commit → diff scope and validation both support versioning
7. Do not advance from test authoring to test/review on authored tests alone;
   require executed evidence.
8. At the merge supervisor gate (after parallel tracks complete): confirm that
   no track left unresolved cross-track conflicts or incomplete interfaces
   before allowing test/review to start.
9. If final verification fails, identify the cause and route back to
   development in the affected track when implementation changes are needed.
10. On interruption, preserve the last safe checkpoint and resume from the
    earliest uncertain step (or earliest uncertain track).
11. After each stage completes successfully, mark the corresponding phase in
    `.dev/PLAN.md` as `[O]` and update `.dev/WORKFLOWS.md` to reflect the
    same. This keeps both files in sync so the runtime can detect completion.
12. Update `.dev/DASHBOARD.md` with the real current phase, active track
    status, verdict, next action, escalation status, and other live context
    that matters for resuming work.

## Parallel Track Coordination

When `.dev/WORKFLOWS.md` lists parallel development tracks:

- Treat each track as an independent sub-pipeline with its own develop and
  test-author phases.
- A track is "complete" when its developer has finished all track tasks and
  its test-author has authored the corresponding test code.
- Do not block Track B on Track A unless an explicit inter-track dependency
  is listed in `.dev/TASKS.md`.
- At the merge gate, verify:
  - All tracks are individually complete and have no open blockers.
  - Cross-track interfaces match (types, contracts, shared state files).
  - No file conflicts between tracks remain unresolved.
- Only after the merge gate passes does the single test/review phase run
  across the combined changes.

## Supervisor Rules

- Treat `.dev/workflow_state.json` as machine truth and Markdown as
  operator-facing state.
- Expect `.dev/DASHBOARD.md` to describe actual in-progress work for the
  active scope, including per-track status when tracks are active.
- Expect `.dev/PLAN.md` to list prompt-derived phase items in ordered checklist
  form.
- Prefer deterministic checks before semantic judgment.
- Do not advance phases on optimism alone.
- If state is inconsistent, record the mismatch and either repair it or require
  manual review.
- Keep the system resumable: every decision should leave enough context for
  the next run.

## Escalation Outcomes

- `approved`
- `rework_required`
- `blocked`
- `manual_review_needed`

## Loop Completion Signal

After the commit phase succeeds, check whether this run was triggered by the
goals-scheduler:

- **Not goals-scheduler** (normal manual run): the committing-agent will emit
  `<promise>COMPLETE</promise>` as its final output line. The dormammu runtime
  detects this and stops the loop. Do not advance to any further stage.
- **Goals-scheduler run**: omit the signal. Route to the final
  `evaluating-agent` step as listed in `.dev/WORKFLOWS.md`.

A goals-scheduler run is identified by the presence of an automated goal file
passed in the session context (e.g. a `.goals/` entry) rather than a direct
user request at the terminal.

## Done Criteria

This skill is complete when the next correct phase is explicit, all active
tracks are accounted for, the state is synchronized, and the project can
continue without ambiguity.
