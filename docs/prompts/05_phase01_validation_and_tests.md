# Phase 01 Prompt: Validation and Test Matrix

## Objective

Complete the validation slice for Phase 1 from `docs/PLAN.md` by tightening automated coverage around the new agent-profile and permission foundation.

## Background

Phase 1 introduces:

- typed agent profiles
- permission ruleset foundations
- config precedence
- backward-compatible role normalization

These changes affect core runtime behavior, so the validation bar must be higher than a smoke test.

Current relevant tests include:

- `tests/test_agent_cli_adapter.py`
- `tests/test_loop_runner.py`
- `tests/test_supervisor.py`
- `tests/test_daemon.py`
- `tests/test_state_repository.py`
- any config-related tests already covering `backend/dormammu/config.py`

## Problem

Without a deliberate test matrix, Phase 1 can easily pass narrow unit tests while leaving hidden incompatibilities in:

- config resolution
- role-to-profile normalization
- pipeline behavior
- loop behavior

## Task

Add or refactor automated tests so Phase 1 behavior is verified end to end at the unit and integration-adjacent level.

## Required Coverage

Cover these dimensions:

- built-in profile defaults
- profile permission defaults
- global and project config override precedence
- legacy role compatibility mapping
- loop runner compatibility
- pipeline runner compatibility
- invalid config or invalid mapping failure behavior

## Testing Rules

- Prefer targeted tests over broad fixture-heavy rewrites.
- Reuse current test structure where possible.
- Keep assertions behavior-focused.
- Add regression tests for bugs discovered while implementing Phase 1.

## Acceptance Criteria

- Phase 1 behavior is covered by automated tests.
- New tests demonstrate both the new model and backward compatibility.
- Failures are descriptive enough to guide future Phase 2 work.
- The resulting test set makes later manifest work safer to implement.

## Deliverable

Submit a test-focused patch that closes the main validation gaps introduced by Phase 1 and documents any remaining risk if full coverage is not feasible in one slice.
