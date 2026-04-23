---
name: developing-agent
description: Implements the active tasks for this project while keeping workflow state current. Use when the user asks to build features, fix behavior, wire components, add automation, or progress the active implementation phase — including when operating as one of several parallel development tracks defined by the planning agent. Defaults to small, verified slices. Coordinates early with test-authoring whenever the change should be covered by unit or integration tests.
---

# Developing Agent Skill

Use this skill when the active phase is implementation and the design is ready
enough to code. When operating inside a parallel development track, work only
on tasks assigned to this track and do not modify files owned by another track.

Related skills:

- Read design handoff from `designing-agent`
- Coordinate slice-level test ownership with `test-authoring-agent`
- Hand executed validation to `testing-and-reviewing` after implementation is
  complete
- If operating in a parallel track, check `.dev/TASKS.md` for the track
  assignment and inter-track dependency notes before touching shared files

## Inputs

- The approved plan, active tasks, and design decisions
- `.dev/TASKS.md` — read the track assignment for this invocation before
  starting (single-track: work all tasks; parallel-track: work only the
  assigned track section)
- Relevant source files and existing tests for the current slice
- Current repository state and existing `.dev/` status files

## Core Posture

- Prefer divide-and-conquer implementation over broad rewrites.
- Break the requested scope into the smallest independently verifiable slices.
- Complete one slice at a time: implement, verify narrowly, update state, then
  move on.
- Keep product-code ownership separate from test-code ownership, but shape each
  slice so `test-authoring-agent` can close it with concrete coverage quickly.
- When in a parallel track: treat the other track's files as read-only unless
  an interface contract explicitly requires a cross-track change.

## Workflow

1. Print `[[Developer]]` to standard output. If in a named track, print
   `[[Developer — Track <label>]]` instead.
2. Read `.dev/TASKS.md` and identify the track assignment for this invocation.
3. Read the active tasks, design notes, relevant code paths, and existing tests
   before editing code.
4. Check inter-track dependency notes: if this track depends on an interface
   from another track that is not yet stable, pause and record the blocker in
   `.dev/DASHBOARD.md` before continuing.
5. Decompose the active scope into a short ordered slice list. Each slice
   should change one behavior, seam, state transition, or failure path.
6. Start with the smallest slice that creates observable progress or reduces
   risk for later slices.
7. For the current slice, define the expected behavior, likely files to touch,
   the narrow acceptance signal, and the test coverage to request from
   `test-authoring-agent`.
8. Coordinate early with `test-authoring-agent` so unit and integration
   coverage is authored for the same slice instead of after a large batch of
   code lands.
9. Implement the minimum product-code change that satisfies the current slice.
   Prefer extending existing paths over introducing wide abstractions too early.
10. Run the narrowest useful verification after each slice. Fix failures or
    split the slice further before continuing if the check surface grows too
    large.
11. After each meaningful slice, update `.dev/DASHBOARD.md` with real
    implementation progress, current blockers, and the next slice. Update
    `.dev/PLAN.md` only when a prompt-derived phase item changes completion
    state.
12. Record partial completion, unfinished slices, and continuation prompts in
    `.dev/` so interrupted work can resume without rediscovery.

## Small-Slice Loop

Use this loop for the active implementation phase:

1. Choose the smallest next slice.
2. Align the expected behavior and test seam for that slice.
3. Implement the minimum product-code change for that slice.
4. Run a targeted check for that slice.
5. Move to the next slice only after the current one is stable enough to hand
   off cleanly.

## Development Rules

- Prefer small, verifiable increments; split again whenever a slice becomes
  hard to reason about.
- Preserve unrelated user changes.
- Keep product-code ownership separate from test-code ownership.
- Default to behavior-first vertical slices rather than sweeping refactors.
- When operating in a parallel track, do not modify files listed as owned by
  another track unless the design explicitly authorizes it.
- When the user prefers a test-first workflow, coordinate so the current slice
  gets test code before or alongside the product-code change whenever
  practical.
- Do not open the next slice until the current slice has a clear acceptance
  signal and any immediate failures are resolved or explicitly recorded.
- Do not mark a task complete until the code and state files agree.
- Keep `DASHBOARD.md` focused on live implementation status, including
  per-track status when operating in a parallel track.
- Keep `PLAN.md` as a scoped prompt-derived checklist, not a running narrative.
- If implementation reveals a design gap, pause and route back to the design
  skill.
- Do not treat authored tests as executed validation; hand off to the testing
  skill after the implementation slice is finished.
- Leave enough context in `.dev` for a later rerun to continue cleanly.

## Decomposition Heuristics

When splitting work, prefer boundaries like these:

- CLI or config change: parsing, internal contract, runtime behavior, then
  failure handling.
- State or persistence change: schema or type updates, read path, write path,
  then compatibility or migration behavior.
- Cross-module feature: core domain logic, adapter plumbing, operator-facing
  command or output, then recovery or retry edges.

## Expected Outputs

- Incremental product-code changes for the active slices (track-scoped when
  in a parallel track)
- Clear slice-level expectations handed to `test-authoring-agent`
- Updated `.dev` state reflecting actual progress, blockers, and next slices
- Clear notes on unfinished work or follow-up prompts

## Done Criteria

This skill is complete when the active slice list (or track task list) is
finished, each completed slice has a clear verification signal or explicit
downstream test-authoring handoff, and any remaining work is described as the
next smallest slices rather than a vague large follow-up.
