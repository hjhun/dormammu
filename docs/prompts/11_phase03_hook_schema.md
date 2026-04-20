# Phase 03 Prompt: Hook Schema and Event Contract

## Objective

Implement the schema foundation for Phase 3 from `docs/PLAN.md`: lifecycle hooks.

## Background

Earlier phases establish:

- typed agent profiles
- permission foundations
- manifest-backed extensibility

Phase 3 should add a safe hook system around the runtime lifecycle without turning the runtime into a loose collection of shell callbacks.

Current integration hotspots to inspect first:

- `backend/dormammu/loop_runner.py`
- `backend/dormammu/daemon/pipeline_runner.py`
- `backend/dormammu/daemon/evaluator.py`
- `backend/dormammu/config.py`

## Problem

The runtime has visible lifecycle boundaries, but no typed hook contract for policy, auditing, or structured automation.

Without a typed contract, later hook work will become inconsistent across:

- stage boundaries
- prompt intake
- tool execution
- final verification
- session termination

## Task

Design and implement a typed hook schema and event contract for `dormammu`.

The first version should define:

- supported hook event names
- hook configuration shape
- hook input payload shape
- hook result payload shape
- response semantics for:
  - `allow`
  - `deny`
  - `warn`
  - `annotate`
  - `background_started`

## Recommended Initial Events

Model at least the events proposed in `docs/PLAN.md`:

- prompt intake
- plan start
- stage start
- stage completion
- tool execution
- config changes
- final verification
- session end

You may normalize these into internal event identifiers, but keep the public contract explicit.

## Design Requirements

- The hook contract must be typed and centrally defined.
- Inputs and outputs must be structured, not free-form string conventions.
- The schema must be extensible for future async/background support.
- The schema must separate event identity from execution implementation.

## Constraints

- Do not implement the whole runner in this slice unless needed to validate the contract.
- Do not introduce shell-only semantics into the core model.
- Do not wire every hook point yet; focus on the contract first.

## Acceptance Criteria

- A typed hook event model exists.
- A typed hook result model exists.
- The initial event set is explicitly represented in code.
- The contract is suitable for synchronous hooks first, with room for later async/background support.

## Validation

Add or update tests for:

- event schema validation
- hook result schema validation
- invalid event or invalid response rejection
- any normalization rules introduced in the contract

## Deliverable

Submit a focused patch that introduces the hook schema, event contract, and tests, ready for runtime execution work in later Phase 3 slices.
