---
name: testing-and-reviewing-workflows
description: Validates changes through tests, checks, and review-oriented analysis for this project. Use when the user asks to test work, review implementation quality, verify a phase, or produce findings before release or commit.
---

# Testing and Reviewing Workflows

Use this skill when the active phase is validation or when a supervisor needs proof that completed work is actually correct.

## Inputs

- The current implementation or artifact under review
- Relevant test commands and project scripts
- `.dev` status and task state

## Workflow

1. Identify the most relevant validations for the active scope.
2. Run available tests, linters, builds, or smoke checks as appropriate.
3. Review the changed files for correctness, regressions, and missing edge cases.
4. Record findings first, then summarize residual risks and verification gaps.
5. Update `.dev/DASHBOARD.md` and `.dev/TASKS.md` to reflect pass, fail, or blocked status.

## Review Rules

- Prioritize bugs, regressions, and missing validation over style commentary.
- Do not claim success for checks that were not actually run.
- If no findings are discovered, state that clearly and note remaining risk.
- Escalate to manual review when confidence depends on unavailable systems or credentials.

## Expected Outputs

- Test and review results tied to the active scope
- Concrete findings or explicit confirmation that none were found
- Updated `.dev` validation status

## Done Criteria

This skill is complete when the current phase has a clear validation outcome and any remaining risk is visible in `.dev`.
