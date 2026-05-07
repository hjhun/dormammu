---
name: coding-workflow
description: Coordinate the full Dormammu coding lifecycle by using refiner, planner, architect, developer, tester, reviewer, and committer skills. Use for multi-stage coding work, resumable execution, rework routing, final verification, or when `.dev/WORKFLOWS.md` must control which stages run. The planner decides the workflow during the planning stage.
---

# Coding Workflow

## Purpose

Coordinate the end-to-end coding process. This skill does not replace the
specialized role skills; it invokes or follows them in order, checks their
durable `.dev` artifacts, and routes rework to the responsible stage.

The planner is the only stage that creates or materially changes
`.dev/WORKFLOWS.md` during normal execution. Coding-workflow reads that file and
supervises the remaining path.

## Stage Skills

Use these canonical skills:

1. `refiner`: write `.dev/REQUIREMENTS.md`.
2. `planner`: write `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and `.dev/TASKS.md`.
3. `architect`: design only when the planner includes the stage.
4. `developer`: implement only when the planner includes development.
5. `test-authoring-agent`: author tests when included.
6. `tester`: execute validation when included.
7. `reviewer`: review changed code and validation evidence when included.
8. `committer`: commit only when included and allowed by user/runtime policy.

Legacy aliases remain valid: `refining-agent`, `planning-agent`,
`developing-agent`, and `committing-agent`.

## Durable Files

Use `.dev/WORKFLOWS.md` as the stage map and `.dev/DASHBOARD.md` as the live
status board. Also expect:

- Refiner: `.dev/REQUIREMENTS.md`
- Planner: `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, `.dev/TASKS.md`
- Architect: `.dev/DESIGN.md` or architect log
- Developer: `.dev/DEVELOPMENT.md` or developer log
- Tester: tester log or `.dev/progress/tester.md`
- Reviewer: reviewer log or `.dev/progress/reviewer.md`
- Committer: committer log or `.dev/progress/committer.md`

Treat `.dev/...` paths as relative to the active prompt workspace.

## Workflow

1. **Refine**
   - Run `refiner` unless requirements already exist and are current.
   - Stop if refinement is blocked.

2. **Plan**
   - Run `planner`.
   - Verify `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, `.dev/TASKS.md`, and
     `.dev/DASHBOARD.md` exist when the workflow requires them.
   - From this point forward, follow `.dev/WORKFLOWS.md`.

3. **Architect**
   - Run only when `.dev/WORKFLOWS.md` includes the architect phase.
   - Route back to planner if the design proves the workflow is unsafe.

4. **Develop And Test Author**
   - Run developer and test authoring phases according to `.dev/WORKFLOWS.md`.
   - Keep product-code and test-code ownership distinct when parallel tracks
     are used.

5. **Tester**
   - Execute planned unit, integration, smoke, and explicit system checks.
   - If validation fails, route back to developer with reproduction evidence.

6. **Reviewer**
   - Review findings first, grounded in changed files and executed validation.
   - Route design, implementation, or test issues back to the responsible role.

7. **Final Verification**
   - Confirm workflow state, dashboard state, validation evidence, and git diff
     agree before commit.
   - If this pass fails, route back to the responsible earlier stage.

8. **Commit**
   - Run committer only when `.dev/WORKFLOWS.md` includes commit and validation
     supports it, or when the user explicitly requested commit preparation.

## Rework Loop

When a later stage reports rework:

1. Read the reporting stage log.
2. Mark the responsible earlier phase pending or rework-required.
3. Run that stage with the rework handoff as context.
4. Continue forward from that stage, not from the beginning.
5. Keep `.dev/WORKFLOWS.md`, `.dev/DASHBOARD.md`, `.dev/PLAN.md`, and
   `.dev/workflow_state.json` aligned.

Stop and ask for clarification only when the artifacts disagree in a way that
would make the next stage unsafe.

## Final Response

Report briefly:

- completed stages
- skipped stages and planner rationale
- validation and review result
- blockers or rework requirements
- commit SHA when a commit was created

Detailed audit trails belong in `.dev` files, not in the chat response.
