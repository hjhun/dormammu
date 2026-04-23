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

- Use adaptive execution depth based on `intake.request_class` and the active
  task scope.
- `direct_response`: do not invent slices, workflow phases, or repository
  edits. Handle the request directly and stop.
- `light_edit`: prefer one bounded implementation pass when a single small
  change can be completed and verified safely without artificial subdivision.
- `full_workflow`: use divide-and-conquer slices and move one verified slice at
  a time.
- Keep product-code ownership separate from test-code ownership, but shape each
  slice so `test-authoring-agent` can close it with concrete coverage quickly.
- When in a parallel track: treat the other track's files as read-only unless
  an interface contract explicitly requires a cross-track change.

## Workflow

1. Print `[[Developer]]` to standard output. If in a named track, print
   `[[Developer — Track <label>]]` instead.
2. Read `.dev/TASKS.md` and identify the track assignment for this invocation.
3. Read `.dev/workflow_state.json` and check `intake.request_class` plus
   `workflow_policy.required_phases` before choosing slice depth.
4. Read the active tasks, design notes, relevant code paths, and existing tests
   before editing code.
5. Check inter-track dependency notes: if this track depends on an interface
   from another track that is not yet stable, pause and record the blocker in
   `.dev/DASHBOARD.md` before continuing.
6. Choose the execution shape:
   - `direct_response`: answer directly or make the explicitly requested
     one-shot action; do not expand the work.
   - `light_edit`: start with a single bounded pass. Split further only if the
     change unexpectedly spans multiple behaviors or files.
   - `full_workflow`: decompose the active scope into a short ordered slice
     list. Each slice should change one behavior, seam, state transition, or
     failure path.
7. Start with the smallest unit of work that creates observable progress or
   reduces risk for later work.
8. For the current unit of work, define the expected behavior, likely files to
   touch, the acceptance signal, and the test coverage to request from
   `test-authoring-agent` when tests are warranted by the workflow policy.
9. Coordinate early with `test-authoring-agent` so unit and integration
   coverage is authored for the same slice instead of after a large batch of
   code lands.
10. Implement the minimum product-code change that satisfies the current unit
    of work. Prefer extending existing paths over introducing wide
    abstractions too early.
11. Run the narrowest useful verification after each meaningful unit of work.
    Fix failures or split the work further before continuing if the check
    surface grows too large.
12. After each meaningful unit of work, update `.dev/DASHBOARD.md` with real
    implementation progress, current blockers, and the next slice. Update
    `.dev/PLAN.md` only when a prompt-derived phase item changes completion
    state.
13. Record partial completion, unfinished slices, and continuation prompts in
    `.dev/` so interrupted work can resume without rediscovery.

## Fast-Path Rules

- If `intake.request_class` is `direct_response`, do not create a slice list,
  do not open implementation tracks, and do not leave fake pending work in
  `.dev` just to continue the loop.
- If `intake.request_class` is `light_edit` and the change is still bounded
  after code inspection, complete it in one pass and mark the relevant state as
  complete instead of forcing divide-and-conquer.
- Escalate from the fast path only when the code inspection shows hidden
  complexity such as multiple modules, interface changes, migration work, or a
  required test matrix that no longer fits a single bounded pass.

## Small-Slice Loop

Use this loop for `full_workflow` implementation or whenever a bounded edit
must be split further after inspection:

1. Choose the smallest next slice.
2. Align the expected behavior and test seam for that slice.
3. Implement the minimum product-code change for that slice.
4. Run a targeted check for that slice.
5. Move to the next slice only after the current one is stable enough to hand
   off cleanly.

## Development Rules

- Prefer small, verifiable increments, but do not split a genuinely small fix
  just to satisfy process.
- Preserve unrelated user changes.
- Keep product-code ownership separate from test-code ownership.
- Default to behavior-first vertical slices rather than sweeping refactors.
- Treat `light_edit` as a fast bounded edit unless the repository proves
  otherwise.
- When operating in a parallel track, do not modify files listed as owned by
  another track unless the design explicitly authorizes it.
- When the user prefers a test-first workflow, coordinate so the current slice
  gets test code before or alongside the product-code change whenever
  practical.
- Do not open the next slice until the current slice has a clear acceptance
  signal and any immediate failures are resolved or explicitly recorded.
- Do not leave work artificially incomplete when the requested change and its
  relevant verification are already done.
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
