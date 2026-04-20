# Phase 04 Prompt: Runtime Stage Isolation

## Objective

Integrate managed worktree isolation into selected runtime stages for Phase 4 from `docs/PLAN.md`.

## Background

The plan recommends worktree isolation first for risky or high-churn stages such as:

- developer stage
- reviewer reproduction
- experimental feature work

`dormammu` currently runs those paths against the active checkout unless the operator manually creates isolation outside the runtime.

## Problem

Even with a worktree service and state tracking, the feature is incomplete until actual runtime stages can opt into isolated execution.

## Task

Integrate worktree isolation into selected runtime stage flows.

Start with the narrowest high-value path that fits the current architecture cleanly, such as:

- developer stage execution in the loop or pipeline flow
- reviewer reproduction path if it is already isolated enough to wire safely

## Design Guidance

- Keep isolation optional and explicit.
- Preserve current behavior when isolation is not requested.
- Centralize the decision path for when a stage should run in a worktree.
- Ensure logs and state clearly show whether an isolated worktree was used.

## Constraints

- Do not expand isolation to every stage in the first integration slice.
- Do not redesign the full pipeline or supervisor contract here.
- Avoid mixing worktree orchestration with unrelated permission or hook work.

## Acceptance Criteria

- At least one real runtime stage can execute in a managed isolated worktree.
- Non-isolated execution still behaves as before.
- The runtime records enough information to understand which worktree was used.
- Integration remains centralized enough to extend to other stages later.

## Validation

Add or update tests for:

- isolated stage execution path
- default non-isolated execution path
- state or log evidence of the selected worktree
- failure behavior when worktree creation or selection fails

## Deliverable

Produce a focused patch that wires managed worktree isolation into a selected runtime stage while preserving default behavior elsewhere.
