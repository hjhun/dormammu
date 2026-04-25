---
name: test-authoring-agent
description: Authors automated tests for the active Dormammu scope. Use after design and alongside development whenever unit, integration, smoke, or explicitly requested system tests need to be written. This skill owns test code and coverage design; tester owns execution against user scenarios.
---

# Test Authoring Agent Skill

Use this skill to write test code that supports TDD and validates the active
requirements.

## Inputs

- Refined requirements and acceptance criteria.
- Planner tasks and workflow.
- Architect/design contracts when present.
- Developer slice expectations and changed behaviors.
- Existing test layout and helper patterns.

## Workspace Persistence

Treat `.dev/...` paths as relative to the active prompt workspace from the
runtime path guidance:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

Record authored coverage, gaps, and blockers in that workspace.

## Workflow

1. Print `[[TestAuthor]]`.
2. Read requirements, plan, tasks, design, and developer slice notes.
3. Map each behavior to a unit, integration, smoke, or optional system test.
4. Write tests before or alongside product code when practical.
5. Keep test changes scoped to the active slice or track.
6. Prefer deterministic assertions over broad snapshot checks.
7. Update `.dev/DASHBOARD.md` with authored coverage and gaps.

## Coverage Rules

- Unit tests cover isolated logic and edge cases.
- Integration tests cover cross-module, CLI, persistence, or runtime behavior.
- Smoke tests cover the primary user-visible workflow with minimal depth.
- System tests require explicit prompt or acceptance-criteria demand and a real
  or equivalent executable environment.

## Done Criteria

The skill is complete when the active scope has appropriate test code and any
missing coverage is explicitly recorded for developer, tester, or supervisor
action.
