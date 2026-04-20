# Phase 03 Prompt: Synchronous Hook Execution Runner

## Objective

Implement the synchronous execution runner for Phase 3 from `docs/PLAN.md`.

## Background

The plan explicitly recommends:

- synchronous lifecycle hooks first
- structured input/output contracts
- typed results

This slice should turn the hook contract into an execution mechanism that the runtime can call safely.

Inspect first:

- the new Phase 3 hook schema
- `backend/dormammu/config.py`
- `backend/dormammu/loop_runner.py`
- `backend/dormammu/daemon/pipeline_runner.py`

## Problem

Without a centralized runner, hooks will either:

- be reimplemented ad hoc at each integration point
- or become loosely structured subprocess calls without consistent behavior

## Task

Implement a dedicated synchronous hook execution runner.

The runner should:

- accept a typed hook event payload
- evaluate matching configured hooks
- execute them through a centralized mechanism
- normalize results into the typed hook response model
- support blocking and non-blocking outcomes according to the contract

## Design Requirements

- Keep execution logic centralized.
- Make the runner deterministic.
- Preserve enough detail for logs, diagnostics, and future operator inspection.
- Fail clearly on malformed hook output.
- Support multiple hooks for the same event in a predictable order.

## Constraints

- Focus on synchronous hooks first.
- Do not implement the full async/background feature set beyond what is needed in the response model.
- Do not bury policy logic in subprocess wrappers or runtime call sites.

## Acceptance Criteria

- A centralized hook runner exists.
- The runner can execute configured synchronous hooks for a given event.
- The runner returns normalized typed results.
- Blocking behavior for deny-like outcomes is well-defined and test-covered.

## Validation

Add or update tests for:

- successful hook execution
- multiple hooks on one event
- deny or blocking behavior
- warn and annotate behavior
- malformed output handling
- deterministic ordering

## Deliverable

Submit a focused patch that adds the synchronous hook runner and tests, ready for runtime integration in the next Phase 3 slice.
