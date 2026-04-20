# Phase 06 Prompt: MCP Runtime Adapter

## Objective

Implement the runtime adapter boundary for Phase 6 from `docs/PLAN.md`.

## Background

After configuration, resolution, and governance boundaries are defined, `dormammu` needs a runtime adapter layer that can represent actual MCP interaction in a controlled way.

The adapter should sit behind:

- configuration schema
- registry and resolution
- permission checks
- hook checks

## Problem

Without a runtime adapter layer, MCP remains purely declarative.

The runtime needs a dedicated boundary that can:

- prepare a server interaction
- report failures consistently
- remain separable from agent-profile resolution and policy enforcement

## Task

Implement an MCP runtime adapter boundary.

The first version does not need to cover every protocol feature. It should focus on a clear runtime abstraction that can:

- accept a resolved MCP server definition
- represent an attempted interaction
- surface success and failure in a structured way
- be extended later without changing the public config and policy contract

## Design Guidance

- Keep the adapter boundary explicit and narrow.
- Separate protocol execution concerns from policy and config concerns.
- Return structured runtime results instead of loose strings.
- Make failure reporting suitable for logs, diagnostics, and later operator inspection.

## Constraints

- Do not overbuild a full MCP ecosystem in one slice.
- Avoid coupling transport execution to unrelated loop or pipeline modules.
- Keep the first version focused on the runtime boundary and structured results.

## Acceptance Criteria

- A dedicated MCP runtime adapter abstraction exists.
- The adapter consumes resolved MCP server definitions and returns structured results.
- Failure modes are explicit and testable.
- The adapter can be used later by operator inspection or event logging work.

## Validation

Add or update tests for:

- successful adapter invocation path if implemented
- unavailable or invalid server behavior
- structured failure reporting
- compatibility with permission and hook boundary integration

## Deliverable

Produce a focused patch that adds the MCP runtime adapter boundary and targeted tests.
