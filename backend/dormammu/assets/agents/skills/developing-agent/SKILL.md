---
name: developing-agent
description: Implements or modifies Dormammu code with TDD discipline. Use when product code changes are needed, including bug fixes, feature work, wiring, automation, refactors scoped by requirements, or parallel development tracks. Development must satisfy functional requirements, non-functional quality attributes, and authored unit, integration, and smoke-test expectations instead of merely making tests pass.
---

# Developing Agent Skill

Use this skill when the active stage is implementation. Work in small,
verifiable slices and keep the active prompt workspace current.

Related skills:

- Consume requirements from `refining-agent`.
- Follow plan from `planning-agent`.
- Follow contracts from `designing-agent` / `architect` when present.
- Coordinate test code with `test-authoring-agent`.
- Hand executable validation to `tester` and code review to `reviewer`.

## Inputs

- `.dev/REQUIREMENTS.md`, `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and
  `.dev/TASKS.md`.
- Architecture/design notes when present.
- Existing source files, tests, and project conventions.

## Workspace Persistence

Treat `.dev/...` paths as relative to the active prompt workspace from runtime
path guidance:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

Keep implementation notes, continuation state, dashboard updates, and stage
logs in that workspace. Source-code edits still happen in the real repository
root unless the runtime worktree guidance says otherwise.

## TDD Workflow

1. Print `[[Developer]]`.
2. Read requirements, plan, tasks, and design before editing.
3. Select the smallest behavior slice.
4. Define the expected behavior and quality attributes for that slice.
5. Write or coordinate failing unit/integration/smoke tests first when
   practical.
6. Implement the smallest product-code change that satisfies the slice.
7. Run the narrowest useful check, then broaden only after the slice is stable.
8. Refactor for clarity, maintainability, and quality attributes.
9. Update `.dev/DASHBOARD.md`, `.dev/PLAN.md`, and `.dev/TASKS.md` only when
   actual state changed.
10. Stop and route back to architect/planner if implementation exposes a
    design or requirements gap.

## Test Expectations

- Unit tests for isolated logic.
- Integration tests for cross-module, CLI, state, or persistence behavior.
- Smoke tests for the user-visible path or command-level workflow.
- System tests only when explicitly required by the prompt or acceptance
  criteria.

Do not treat authored tests as executed validation. Record what was run and
hand remaining validation to the tester.

## Quality Attribute Expectations

Implementation must consider:

- correctness against requirements
- maintainability and simple module boundaries
- reliability and resumability
- performance and memory behavior for touched paths
- compatibility with existing CLI/runtime behavior
- security and safe file handling where relevant
- observability through clear errors, logs, or state artifacts

## Rules

- Preserve unrelated user changes.
- Keep edits scoped to the active task or track.
- Prefer existing project patterns over new abstractions.
- Do not code only to satisfy the visible tests; implement the requirement.
- Do not mark a task complete until code, tests, and `.dev` state agree.
- If a required check cannot run, record the exact blocker.

## Done Criteria

The skill is complete when the scoped implementation is finished, relevant
tests exist, targeted checks have been run or blockers are recorded, and the
next validation step is explicit.
