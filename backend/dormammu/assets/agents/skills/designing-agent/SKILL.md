---
name: designing-agent
description: Produces implementation-ready designs, interfaces, schemas, and technical decisions for this project. Use when the user asks for architecture, component design, state models, file layout, or design artifacts before coding — and when parallel development tracks are planned, design must define the cross-track interface contracts before track agents begin.
---

# Designing Agent Skill

Use this skill after planning and before broad implementation, or when the
current phase is blocked on technical decisions.

When the planning agent has defined parallel development tracks, the designer
must produce explicit interface contracts between tracks before either track
starts. This prevents cross-track conflicts during implementation.

Related skills:

- Consume the track layout from `planning-agent` via `.dev/TASKS.md` and
  `.dev/WORKFLOWS.md`
- Hand off product-code implementation to `developing-agent` (per track)
- Hand off automated test-code implementation to `test-authoring-agent` (per
  track)

## Inputs

- The approved plan and active tasks
- `.dev/TASKS.md` — check for parallel track definitions and inter-track
  dependency notes
- [PROJECT.md](../../../.dev/PROJECT.md)
- Existing source files and `.dev/` state

## Workflow

1. Print `[[Designer]]` to standard output.
2. Read the active tasks and identify the design decisions that unblock them.
3. When parallel tracks are defined in `.dev/TASKS.md`:
   - Identify the shared interfaces, types, or contracts that cross track
     boundaries.
   - Define those cross-track contracts first so each track can implement
     independently without waiting for the other.
   - Document which files or modules each track owns to avoid conflicts.
4. Define boundaries: modules, interfaces, data contracts, state files, failure
   handling, and test seams.
5. Prefer designs that support resumability, idempotent reruns, and supervisor
   verification.
6. Capture the chosen design in concise project documentation or artifact
   files.
7. Reflect real design progress in `.dev/DASHBOARD.md` and mark finished
   prompt-derived design phase items in `.dev/PLAN.md`.

## Design Rules

- Optimize for operational clarity over novelty.
- Keep abstractions minimal for the current milestone.
- When parallel tracks are planned, explicitly state which files each track
  owns — this is the most important output for preventing merge conflicts.
- Document only the decisions that affect implementation, recovery, test
  authoring, testing, or deployment.
- Call out assumptions, open questions, and explicit tradeoffs.
- If a design choice changes an earlier plan, update the dashboard and tasks
  together.
- Keep `DASHBOARD.md` focused on what design work is actively unblocking the
  scope right now.

## Expected Outputs

- Implementation-ready architecture notes
- Clear contracts for modules, files, or APIs
- Cross-track interface contracts and file ownership map (when parallel tracks
  are defined)
- Clear expectations for unit, integration, and optional system-test coverage
- Updated `.dev` status showing what is now unblocked

## Done Criteria

This skill is complete when a development agent can implement the active work
without inventing missing architecture, and when parallel track developers can
each start independently without ambiguity about file ownership or interface
contracts.
