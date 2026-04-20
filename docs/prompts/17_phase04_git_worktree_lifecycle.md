# Phase 04 Prompt: Git Worktree Lifecycle

## Objective

Implement managed git worktree lifecycle operations for Phase 4 from `docs/PLAN.md`.

## Background

Once the worktree service foundation exists, `dormammu` needs explicit lifecycle operations for isolated execution.

Current code already has git-based repository inspection in `backend/dormammu/supervisor.py`, but no dedicated worktree lifecycle management.

## Problem

Without lifecycle support, worktree isolation remains theoretical. The runtime needs explicit, testable behavior for:

- create
- reuse or lookup
- reset
- remove or cleanup

## Task

Implement managed git worktree lifecycle operations through the new worktree service.

The first version should support:

- creating an isolated worktree from the main repository
- deterministically naming or identifying worktrees
- safely cleaning up or resetting worktrees
- clear failure behavior when git prerequisites are not met

## Design Guidance

- Prefer explicit state over implicit shell assumptions.
- Keep git interaction centralized.
- Make failure modes readable and actionable.
- Ensure cleanup behavior is deterministic enough for later resume logic.

## Constraints

- Do not yet integrate all stage execution into isolated worktrees in this slice.
- Do not scatter git worktree commands across runtime modules.
- Avoid destructive behavior unless explicitly modeled and test-covered.

## Acceptance Criteria

- The runtime can create a managed git worktree.
- The runtime can remove or reset a managed git worktree safely.
- Errors for unsupported repositories or failing git commands are explicit.
- Lifecycle code is centralized and testable.

## Validation

Add or update tests for:

- successful worktree creation
- repeated creation behavior or collision handling
- reset behavior
- cleanup behavior
- non-git repository or git failure cases

## Deliverable

Produce a focused patch that implements managed git worktree lifecycle operations with targeted tests.
