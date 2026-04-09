name: designing-agent
description: Produces implementation-ready designs, interfaces, schemas, and technical decisions for this project. Use when the user asks for architecture, component design, state models, file layout, or design artifacts before coding.
---

# Designing Agent Skill

Use this skill after planning and before broad implementation, or when the current phase is blocked on technical decisions.

Related skills:

- Hand off product-code implementation to `developing-agent`
- Hand off automated test-code implementation to `test-authoring-agent`

## Inputs

- The approved plan and active tasks
- [PROJECT.md](../../../PROJECT.md)
- Existing source files and `.dev/` state

## Workflow

1. Read the active tasks and identify the design decisions that unblock them.
2. Define boundaries: modules, interfaces, data contracts, state files, failure handling, and test seams.
3. Prefer designs that support resumability, idempotent reruns, and supervisor verification.
4. Capture the chosen design in concise project documentation or artifact files.
5. Reflect real design progress in `.dev/DASHBOARD.md` and mark finished prompt-derived design phase items in `.dev/PLAN.md`.

## Design Rules

- Optimize for operational clarity over novelty.
- Keep abstractions minimal for the current milestone.
- Document only the decisions that affect implementation, recovery, test authoring, testing, or deployment.
- Call out assumptions, open questions, and explicit tradeoffs.
- If a design choice changes an earlier plan, update the dashboard and plan together.
- Keep `DASHBOARD.md` focused on what design work is actively unblocking the scope right now.

## Expected Outputs

- Implementation-ready architecture notes
- Clear contracts for modules, files, or APIs
- Clear expectations for unit, integration, and optional system-test coverage
- Updated `.dev` status showing what is now unblocked

## Done Criteria

This skill is complete when a development agent can implement the active work without inventing missing architecture.
