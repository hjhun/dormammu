# Phase 7 Prompt 01: Lifecycle Event Schema

## Objective

Define a typed lifecycle event model that represents the full execution flow across loop, pipeline, supervisor, daemon, and evaluator paths.

## Background

The current codebase already records execution outcomes in several places, but the model is fragmented:

- `backend/dormammu/daemon/models.py` defines stage-oriented result objects
- supervisor, evaluator, and daemon flows write reports and state snapshots independently
- `.dev` state files act as operator-facing status, but they are not clearly derived from one shared event contract

Phase 7 in `docs/PLAN.md` requires the project to emit typed events for the full pipeline lifecycle and align human-readable state with machine-truth runtime data.

## Problem

The runtime currently relies on a mix of direct state mutation, report generation, and inferred status. That makes it difficult to:

- reconstruct the exact lifecycle of a run
- explain why a stage advanced, failed, retried, or was blocked
- unify observability across loop and pipeline execution
- make `.dev` files deterministic projections of actual runtime activity

Without a typed event schema, each subsystem evolves its own tracking semantics and the product becomes harder to resume, inspect, and verify.

## Task

Design and implement a shared lifecycle event schema for runtime execution.

The implementation should:

- introduce typed event models for important lifecycle transitions
- capture enough metadata to reconstruct execution order and outcome
- support both single-run loop flows and multi-stage pipeline flows
- make event payloads stable enough for persistence, inspection, and testing

## Design Requirements

- Add event model definitions in a runtime-appropriate module under `backend/dormammu/`
- Use explicit event types rather than loosely structured dictionaries
- Include common metadata fields such as:
  - `event_id`
  - `event_type`
  - `run_id`
  - `session_id` when available
  - `timestamp`
  - `role` or `stage` when applicable
  - `status`
  - optional `artifact_refs`
  - optional `metadata`
- Separate event identity from stage result payloads
- Ensure the schema can represent both normal progress and exceptional conditions

## Event Coverage Guidance

At minimum, support events for:

- run requested
- run started
- run finished
- stage queued
- stage started
- stage completed
- stage failed
- stage retried
- evaluator checkpoint decision
- supervisor handoff
- hook execution started and finished
- permission gate blocked or approved
- worktree prepared and released
- artifact persisted

You do not need to finalize every possible event variant in one pass, but the model must be extensible without breaking existing persisted data.

## Constraints

- Preserve current runtime behavior unless a change is necessary to support the new contract
- Do not hardcode the schema to pipeline-only execution
- Avoid event models that duplicate large output blobs unnecessarily
- Prefer small, typed payloads plus artifact references over giant in-memory records
- Keep serialization straightforward for future JSON persistence

## Acceptance Criteria

- A shared event schema exists and is used by runtime code
- Event types and payload fields are explicit and testable
- The schema supports both loop and pipeline execution modes
- Events can reference persisted artifacts instead of embedding large reports inline
- The design clarifies how `.dev` projections can be derived from lifecycle events

## Validation

- Add unit tests for event construction and serialization
- Add targeted tests that prove stage and run events can be emitted in realistic sequences
- Verify that event payloads remain stable when optional metadata is absent

## Deliverable

Produce the lifecycle event schema implementation, wire it into the runtime where appropriate, and add tests plus concise developer documentation describing the event contract.
