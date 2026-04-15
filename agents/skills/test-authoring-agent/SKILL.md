---
name: test-authoring-agent
description: Writes and maintains dedicated automated tests for the active scope. Use after design to author unit tests and integration tests alongside development, and to add system tests only when the user or prompt explicitly requires system-test-level coverage on real device environments.
---

# Test Authoring Agent Skill

Use this skill after design when the active scope needs test code, not just test execution.

## Inputs

- The approved plan and design decisions
- The active implementation scope and expected behaviors
- Existing test layout, helpers, and `.dev/` state

## Workflow

1. Print `[[TestAuthor]]` to standard output.
2. Read the active tasks, design notes, and validation expectations before writing tests.
2. Own the test-code slice while the development agent owns product code.
3. Write unit tests for isolated logic and integration tests for cross-module or CLI flows by default.
4. Add system tests only when the user, prompt, or acceptance criteria explicitly call for system-test-level coverage.
5. When system tests are required, target the closest real device or device-like environment available and record any environment dependency clearly.
6. Update `.dev/DASHBOARD.md` with authored test coverage, gaps, and blockers, and update `.dev/PLAN.md` only when the prompt-derived phase checklist changes.

## Test Authoring Rules

- Prefer small, deterministic tests that map directly to the designed behaviors.
- Keep test ownership separate from product-code ownership even when both tracks progress in parallel.
- Default coverage is unit plus integration.
- Treat system tests as opt-in work that needs an explicit requirement and an executable environment.
- If a required real device environment is unavailable, stop short of claiming coverage and escalate that gap for later execution.
- If implementation changes invalidate the planned test shape, route back through design or coordinate with development before broad rewrites.
- Keep `DASHBOARD.md` as the operator-facing description of what test work is actually in progress or blocked.

## Expected Outputs

- New or updated unit tests for the active logic
- New or updated integration tests for the active workflow paths
- Optional system tests when explicitly requested
- Updated `.dev` state showing authored coverage and any environment gaps

## Done Criteria

This skill is complete when the active scope has the intended automated test code in place and any unimplemented coverage is explicit.
