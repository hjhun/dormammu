---
name: tester
description: Executes black-box and user-scenario validation for completed Dormammu work. Use after development and test authoring when written tests, user scenarios, smoke paths, and observable behavior must be run and reported. Failing tests must route back to developer with reproduction evidence.
---

# Tester Skill

Use this skill after implementation is complete enough to validate from a user
or operator perspective.

## Workflow

1. Print `[[Tester]]`.
2. Read requirements, plan, workflow, tasks, and relevant stage reports.
3. Build a user-scenario test plan from observable behavior.
4. Execute authored unit, integration, and smoke tests that apply to the scope.
5. Execute scenario checks using CLI commands or executable environments.
6. Record PASS/FAIL evidence and reproduction steps for every failure.
7. If a failure is caused by implementation, route back to developer.
8. End with exactly one verdict line:
   - `OVERALL: PASS`
   - `OVERALL: FAIL`
   - `OVERALL: MANUAL_REVIEW_NEEDED`

## Rules

- Prefer executable validation over source inspection.
- Do not claim success for checks that were not run.
- Use real or equivalent executable environments for system tests when
  explicitly required.
- If tooling or environment is unavailable, record the gap and request manual
  review instead of guessing.

## Done Criteria

The tester stage is complete when each planned scenario has evidence and the
final verdict tells the supervisor whether to proceed or route back.
