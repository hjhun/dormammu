---
name: developing-agent
description: Implements the active tasks for this project while keeping workflow state current. Use when the user asks to build features, wire components, add automation, or progress the active implementation phase.
---

# Developing Agent Skill

Use this skill when the active phase is implementation.

Related skills:

- Read design handoff from `designing-agent`
- Coordinate test ownership with `test-authoring-agent`
- Hand executed validation to `testing-and-reviewing` after implementation is complete

## Inputs

- The active task list and design decisions
- Current repository state
- Existing `.dev/` status files

## Workflow

1. Read the active tasks before editing code.
2. Implement only the current scoped slice; avoid mixing unrelated work.
3. Keep steps idempotent where possible so interrupted runs can resume safely.
4. Keep the test authoring agent informed about behavior changes that affect unit, integration, or system-test expectations.
5. After each meaningful change, update `.dev/DASHBOARD.md` with the real implementation progress and update `.dev/PLAN.md` only when a prompt-derived phase item changes completion state.
6. Record blockers, partial completion, and required continuation prompts in `.dev/`.

## Development Rules

- Prefer small, verifiable increments.
- Preserve unrelated user changes.
- Keep product-code ownership separate from test-code ownership.
- Do not mark a task complete until the code and state files agree.
- Keep `DASHBOARD.md` focused on live implementation status rather than a generic summary of the whole repo.
- Keep `PLAN.md` as a scoped prompt-derived checklist, not a running narrative.
- If implementation reveals a design gap, pause and route back to the design skill.
- Do not treat authored tests as executed validation; hand off to the testing skill after the implementation slice is finished.
- Leave enough context in `.dev` for a later rerun to continue cleanly.

## Expected Outputs

- Code or automation changes for the active tasks
- Updated `.dev` state reflecting progress
- Clear notes on unfinished work or follow-up prompts

## Done Criteria

This skill is complete when the active implementation slice is finished or explicitly handed off with precise remaining work.
