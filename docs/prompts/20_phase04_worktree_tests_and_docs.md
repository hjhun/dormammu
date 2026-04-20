# Phase 04 Prompt: Worktree Validation and Documentation

## Objective

Complete the validation and documentation slice for Phase 4 from `docs/PLAN.md`.

## Background

Managed worktree isolation changes runtime execution behavior and state handling. Once introduced, it needs strong validation and operator-facing documentation.

Relevant areas:

- tests around loop, pipeline, supervisor, and state behavior
- `backend/dormammu/state/SCHEMA.md`
- `docs/GUIDE.md`
- any new worktree-related docs added in Phase 4

## Problem

Worktree isolation can become fragile if it is not documented and tested as a first-class runtime feature.

## Task

Add or update automated tests and operator-facing documentation for the Phase 4 worktree feature.

## Required Coverage

Testing should cover:

- worktree service foundation
- lifecycle operations
- state persistence
- runtime integration
- no-worktree compatibility behavior

Documentation should explain:

- when worktree isolation is used
- how it is configured or requested
- how it appears in state and logs
- cleanup and resume expectations
- known limitations

## Constraints

- Keep documentation aligned with implemented behavior.
- Do not expand into broad unrelated docs cleanup.
- Preserve CLI-only product framing.

## Acceptance Criteria

- Worktree behavior is covered by automated tests.
- Operator-facing docs explain how isolation works.
- State documentation is updated if schema changes were introduced.
- Remaining limitations are explicit.

## Deliverable

Submit a test-and-doc patch that closes the validation gap for Phase 4 and leaves managed worktree isolation understandable to operators and maintainers.
