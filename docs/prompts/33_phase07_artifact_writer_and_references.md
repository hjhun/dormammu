# Phase 7 Prompt 03: Artifact Writer and References

## Objective

Introduce a unified artifact writing layer so reports, logs, transcripts, and state-linked outputs are persisted consistently and referenced from lifecycle events and stage results.

## Background

Artifacts are currently written in several runtime paths:

- supervisor reports
- evaluator reports
- stage output files under `.dev/`
- state snapshots and run metadata

These writes are useful, but they are not coordinated through one artifact-oriented abstraction. As a result, different modules decide independently:

- where artifacts live
- how paths are named
- which metadata gets returned
- how artifacts are linked back to runtime execution objects

## Problem

Without a shared artifact writer, artifact persistence is inconsistent and difficult to reason about. The runtime lacks a clean contract for:

- producing stable artifact references
- attaching artifact metadata to stage results and events
- writing related artifacts in a deterministic location
- enforcing naming and path conventions across subsystems

This makes observability and resume behavior harder to standardize.

## Task

Design and implement a centralized artifact writer and artifact reference model.

The implementation should:

- provide one reusable API for persisting runtime artifacts
- return typed references that can be attached to events and results
- support existing `.dev` artifact patterns without breaking operator expectations

## Design Requirements

- Add an artifact module under `backend/dormammu/` that is reusable by loop, pipeline, supervisor, and daemon code
- Define an artifact reference type that includes at least:
  - artifact kind
  - filesystem path
  - run or stage association when applicable
  - creation timestamp or equivalent metadata
- Provide helper methods for writing common artifact categories such as:
  - markdown report
  - plain text output
  - structured JSON metadata
- Ensure artifact writing can be used without requiring every caller to know directory layout details

## Integration Guidance

The artifact writer should be adopted in places that currently write stage or run artifacts directly. Focus especially on:

- supervisor reports
- evaluator outputs
- pipeline stage artifacts
- loop execution outputs

The final design should make it obvious how artifact references are surfaced through the lifecycle event and stage result models introduced in the other Phase 7 prompts.

## Constraints

- Preserve current operator-visible artifact layout where possible
- Avoid large refactors that rename every `.dev` path without strong justification
- Do not hide important path information from callers
- Keep artifact writing deterministic and easy to test

## Acceptance Criteria

- A reusable artifact writer abstraction exists
- Runtime subsystems use the shared writer instead of ad hoc path handling in the main flow
- Artifact references can be attached to stage results and lifecycle events
- Existing artifact outputs remain understandable to operators inspecting `.dev`

## Validation

- Add unit tests for artifact path generation and file writing
- Add integration tests that assert emitted result/event objects contain valid artifact references
- Verify markdown and JSON artifact cases at minimum

## Deliverable

Produce the artifact writer implementation, migrate selected runtime paths to use it, and document the artifact reference contract and directory behavior.
