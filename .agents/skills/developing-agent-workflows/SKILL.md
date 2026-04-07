---
name: developing-agent-workflows
description: Implements the active tasks for this project while keeping workflow state current. Use when the user asks to build features, wire components, add automation, or progress the active implementation phase.
---

# Developing Agent Workflows

Use this skill when the active phase is implementation.

## Inputs

- The active task list and design decisions
- Current repository state
- Existing `.dev/` status files

## Workflow

1. Read the active tasks before editing code.
2. Implement only the current scoped slice; avoid mixing unrelated work.
3. Keep steps idempotent where possible so interrupted runs can resume safely.
4. After each meaningful change, update `.dev/TASKS.md` and `.dev/DASHBOARD.md`.
5. Record blockers, partial completion, and required continuation prompts in `.dev/`.

## Development Rules

- Prefer small, verifiable increments.
- Preserve unrelated user changes.
- Do not mark a task complete until the code and state files agree.
- If implementation reveals a design gap, pause and route back to the design skill.
- Leave enough context in `.dev` for a later rerun to continue cleanly.

## Expected Outputs

- Code or automation changes for the active tasks
- Updated `.dev` state reflecting progress
- Clear notes on unfinished work or follow-up prompts

## Done Criteria

This skill is complete when the active implementation slice is finished or explicitly handed off with precise remaining work.
