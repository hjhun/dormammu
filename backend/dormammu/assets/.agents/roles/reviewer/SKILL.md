---
schema_version: 1
name: reviewer
description: Use this skill after implementation to verify requirements, run relevant unit/smoke/e2e tests, review side effects, and decide whether work should return to development.
metadata: {"visibility": "profile_scoped", "role": "reviewer"}
---

# Reviewer

Review the implemented work and execute the validation gates.

## Inputs

- Changed files
- `REQUIREMENTS.md`
- `TEST_PLAN.md`
- `DEV_NOTES.md`
- Existing test commands and project scripts

## Workflow

1. Confirm the implementation matches the requirements.
2. Run unit tests for changed logic.
3. Run smoke tests for executable flows.
4. Run e2e tests for user-facing or cross-process behavior.
5. If a gate is irrelevant or unavailable, record the reason.
6. Inspect for hidden side effects, regressions, and missing edge cases.
7. Write `TEST_REPORT.md` and `REVIEW.md`.
8. Return `APPROVED` only when evidence supports completion.

## Verdicts

- `APPROVED`: requirements met and validation evidence is sufficient.
- `NEEDS_WORK`: implementation must return to developer or architect.
- `BLOCKED`: external input, credentials, or environment is required.

