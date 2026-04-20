# Phase 04 Prompt: Worktree State and Resume Integration

## Objective

Integrate managed worktrees into machine-readable state for Phase 4 from `docs/PLAN.md`.

## Background

The plan explicitly calls for worktree state to be stored explicitly in machine-readable state. `dormammu` already has session and workflow state infrastructure through:

- `backend/dormammu/state/repository.py`
- `backend/dormammu/state/session_manager.py`
- `backend/dormammu/state/SCHEMA.md`

## Problem

Worktree isolation is not robust unless the runtime can resume, inspect, and clean up worktrees through persisted state rather than implicit filesystem discovery.

## Task

Add worktree state integration to the `.dev` machine-truth layer.

The implementation should:

- define how worktree metadata is stored in state
- keep session and workflow scope explicit
- support resume and cleanup logic later
- avoid corrupting existing state files when no worktrees are used

## Design Requirements

- Use explicit schema additions instead of loose ad hoc fields.
- Keep machine-truth and operator-facing state clearly separated.
- Make the schema easy to inspect and extend.
- Update schema documentation if state shape changes.

## Constraints

- Do not perform a broad state-system rewrite in this slice.
- Keep compatibility with existing sessions that do not use worktrees.
- Avoid adding unrelated `.dev` cleanup work beyond what worktree tracking needs.

## Acceptance Criteria

- Worktree metadata is persisted in machine-readable state.
- State changes are backward compatible for sessions without worktrees.
- The runtime has a clear path to restore or clean worktree state on resume.
- State documentation and tests are updated if schema changes are introduced.

## Validation

Add or update tests for:

- state persistence with no worktree
- state persistence with active worktree metadata
- restore or resume-oriented read paths
- backward compatibility with older state payloads if needed

## Deliverable

Submit a focused patch that integrates worktree metadata into runtime state and prepares the system for reliable resume behavior.
