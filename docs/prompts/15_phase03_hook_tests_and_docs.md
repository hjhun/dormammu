# Phase 03 Prompt: Hook Validation and Documentation

## Objective

Complete the validation and documentation slice for Phase 3 from `docs/PLAN.md`.

## Background

Hooks are a user-facing extensibility surface. Once introduced, they need:

- automated validation
- clear operator documentation
- contributor guidance on intended use and current limits

Relevant areas:

- tests for config, loop, pipeline, and evaluator behavior
- `docs/GUIDE.md`
- any hook-related docs introduced during Phase 3

## Problem

Hooks change runtime behavior in a potentially powerful way. Without tests and documentation, they become fragile and unsafe.

## Task

Add or update automated tests and operator-facing documentation for the Phase 3 hook system.

## Required Coverage

Testing should cover:

- hook schema validation
- hook config loading and precedence
- synchronous hook runner behavior
- lifecycle integration behavior
- no-hook compatibility behavior

Documentation should explain:

- supported hook events
- configuration shape
- result semantics such as `allow`, `deny`, `warn`, `annotate`, and `background_started`
- what is synchronous today
- what is intentionally not supported yet

## Constraints

- Keep documentation aligned with implemented behavior.
- Do not turn this into a broad documentation rewrite.
- Preserve CLI-only product scope.

## Acceptance Criteria

- Hook behavior is covered by automated tests.
- Documentation explains how operators configure and reason about hooks.
- Limitations and safety boundaries are documented explicitly.
- Later phases can build on the hook surface without re-explaining the basics.

## Deliverable

Submit a test-and-doc patch that closes the validation gap for Phase 3 and leaves the hook system understandable for operators and contributors.
