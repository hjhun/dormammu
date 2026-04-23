---
name: testing-and-reviewing
description: Validates changes through executed tests, checks, and review-oriented analysis for this project. Use after development is complete — including after all parallel development tracks have merged — when the user asks to test work, review implementation quality, verify a phase, or produce findings before release or commit.
---

# Testing and Reviewing Skill

Use this skill when the active phase is validation or when a supervisor needs
proof that completed work is actually correct. When parallel development tracks
were used, this skill runs after the merge supervisor gate confirms all tracks
are individually complete.

Related skills:

- Expect automated test code from `test-authoring-agent` (across all tracks
  when parallel tracks were used)
- Start only after `developing-agent` has finished the active implementation
  slice (or all track slices)

## Inputs

- The current implementation or artifact under review (all tracks combined
  when parallel tracks were used)
- Relevant test commands and project scripts
- `.dev` status and task state

## Workflow

1. Print `[[Tester]]` to standard output.
2. Confirm that the active development slice (and all parallel track slices,
   if applicable) is complete before executing validation.
3. Identify the most relevant validations for the active scope.
4. Run unit tests and integration tests by default, then add linters, builds,
   or smoke checks as appropriate.
5. Run system tests only when the user, prompt, or acceptance criteria
   explicitly require system-test-level validation.
6. For required system tests, use a real device or equivalent executable
   environment when available; otherwise record the gap and escalate instead
   of claiming success.
7. Review the changed files for correctness, regressions, and missing edge
   cases — covering changes from all parallel tracks when applicable.
8. Record findings first, then summarize residual risks and verification gaps.
9. Update `.dev/DASHBOARD.md` to reflect the real validation outcome and
   update `.dev/PLAN.md` when the prompt-derived phase checklist changes
   because validation is complete or blocked.

## Review Rules

- Prioritize bugs, regressions, and missing validation over style commentary.
- Do not claim success for checks that were not actually run.
- Treat authored tests and executed tests as different evidence levels.
- When parallel tracks were used, verify that cross-track integration points
  work correctly — not just each track in isolation.
- If no findings are discovered, state that clearly and note remaining risk.
- Escalate to manual review when confidence depends on unavailable systems or
  credentials.
- Keep `DASHBOARD.md` as the primary operator view for pass, fail, blocked,
  and residual-risk status.

## Expected Outputs

- Test and review results tied to the active scope (all tracks combined)
- Concrete findings or explicit confirmation that none were found
- Updated `.dev` validation status

## Done Criteria

This skill is complete when the current phase has a clear validation outcome
and any remaining risk is visible in `.dev`.
