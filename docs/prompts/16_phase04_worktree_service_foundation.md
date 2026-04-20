# Phase 04 Prompt: Worktree Service Foundation

## Objective

Implement the service foundation for Phase 4 from `docs/PLAN.md`: managed worktree isolation.

## Background

`dormammu` already knows how to validate repository changes through:

- `require_worktree_changes` in `LoopRunRequest`
- git diff checks in `backend/dormammu/supervisor.py`

However, it does not yet manage isolated git worktrees as a first-class runtime capability.

Relevant files to inspect first:

- `backend/dormammu/loop_runner.py`
- `backend/dormammu/supervisor.py`
- `backend/dormammu/config.py`
- `backend/dormammu/state/repository.py`

## Problem

The runtime can check whether a worktree changed, but it cannot create, track, reset, or clean up managed worktrees for isolated execution.

That means high-risk stages still share one checkout by default.

## Task

Design and implement the foundational worktree service for `dormammu`.

The service should establish the core runtime model for:

- worktree identity
- source repository root
- isolated directory path
- owning session or run metadata
- lifecycle status

## Design Requirements

- Keep the worktree service separate from stage-specific business logic.
- Use typed runtime models.
- Make the service compatible with later CLI inspection commands.
- Preserve compatibility when worktree isolation is disabled.

## Constraints

- Do not wire every runtime path yet.
- Do not redesign the supervisor in this slice.
- Do not add manifest or hook work here.

## Acceptance Criteria

- A dedicated worktree service or module exists.
- Typed worktree runtime models exist.
- The service is structured so later slices can add create/reset/remove behavior cleanly.
- Existing runtime behavior remains unchanged when no worktree isolation is requested.

## Validation

Add or update tests for:

- worktree model creation
- configuration defaults
- disabled-path behavior
- invalid initialization cases if applicable

## Deliverable

Submit a focused patch that introduces the worktree service foundation and tests, ready for lifecycle operations in later Phase 4 slices.
