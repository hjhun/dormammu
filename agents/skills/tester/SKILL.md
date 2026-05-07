---
name: tester
description: Execute black-box, authored-test, and CLI scenario validation for completed Dormammu work. Use when `.dev/WORKFLOWS.md` includes tester validation after development or test authoring, and report PASS/FAIL evidence that can route failures back to developer without weakening tests.
---

# Tester Skill

Use this skill after implementation is complete enough for executable
validation. Follow `.dev/WORKFLOWS.md`; do not run this stage if planner
skipped validation unless explicitly redirected.

## Workflow

1. Print `[[Tester]]`.
2. Read requirements, plan, workflow, tasks, design, development notes, and
   relevant stage reports.
3. Build a CLI and operator scenario test plan from observable behavior.
4. Execute authored unit, integration, and smoke tests that apply to the scope.
5. Execute scenario checks using CLI commands or executable environments.
6. Record exact commands, PASS/FAIL evidence, skipped checks, and reproduction
   steps for every failure.
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
