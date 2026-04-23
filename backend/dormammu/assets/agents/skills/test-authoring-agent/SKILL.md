---
name: test-authoring-agent
description: Writes and maintains dedicated automated tests for the active scope. Use after design to author unit tests and integration tests alongside development — including when operating as one of several parallel test-authoring tracks defined by the planning agent. Adds system tests only when the user or prompt explicitly requires system-test-level coverage on real device environments.
---

# Test Authoring Agent Skill

Use this skill after design when the active scope needs test code, not just
test execution. When operating inside a parallel development track, write tests
only for the tasks assigned to this track.

Related skills:

- Coordinate slice-level test seams with `developing-agent` (same track)
- Hand authored tests to `testing-and-reviewing` for execution

## Inputs

- The approved plan and design decisions
- `.dev/TASKS.md` — read the track assignment for this invocation before
  starting (single-track: cover all tasks; parallel-track: cover only the
  assigned track section)
- The active implementation scope and expected behaviors
- Existing test layout, helpers, and `.dev/` state

## Workflow

1. Print `[[TestAuthor]]` to standard output. If in a named track, print
   `[[TestAuthor — Track <label>]]` instead.
2. Read `.dev/TASKS.md` and identify the track assignment for this invocation.
3. Read the active tasks, design notes, and validation expectations before
   writing tests.
4. Own the test-code slice while the development agent owns product code for
   the same track.
5. Write unit tests for isolated logic and integration tests for cross-module
   or CLI flows by default.
6. Add system tests only when the user, prompt, or acceptance criteria
   explicitly call for system-test-level coverage.
7. When system tests are required, target the closest real device or
   device-like environment available and record any environment dependency
   clearly.
8. Update `.dev/DASHBOARD.md` with authored test coverage, gaps, and blockers
   (scoped to this track when in a parallel track). Update `.dev/PLAN.md` only
   when the prompt-derived phase checklist changes.

## Test Authoring Rules

- Prefer small, deterministic tests that map directly to the designed
  behaviors.
- Keep test ownership separate from product-code ownership even when both
  tracks progress in parallel.
- When operating in a parallel track, write tests only for the behavior changes
  owned by this track. Do not duplicate test coverage authored by another
  track.
- Default coverage is unit plus integration.
- Treat system tests as opt-in work that needs an explicit requirement and an
  executable environment.
- If a required real device environment is unavailable, stop short of claiming
  coverage and escalate that gap for later execution.
- If implementation changes invalidate the planned test shape, route back
  through design or coordinate with development before broad rewrites.
- Keep `DASHBOARD.md` as the operator-facing description of what test work is
  actually in progress or blocked, including per-track status.

## Expected Outputs

- New or updated unit tests for the active logic (track-scoped when in a
  parallel track)
- New or updated integration tests for the active workflow paths
- Optional system tests when explicitly requested
- Updated `.dev` state showing authored coverage and any environment gaps

## Done Criteria

This skill is complete when the active scope (or track scope) has the intended
automated test code in place and any unimplemented coverage is explicit.
