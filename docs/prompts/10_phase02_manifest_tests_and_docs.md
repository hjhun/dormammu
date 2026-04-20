# Phase 02 Prompt: Manifest Tests and Operator Documentation

## Objective

Complete the validation and documentation slice for Phase 2 from `docs/PLAN.md`.

## Background

Phase 2 introduces a user-visible extension surface: agent manifests stored on disk. That means the change is not complete until the behavior is covered by tests and documented for operators and contributors.

Likely relevant files:

- tests covering config, runtime resolution, and role execution
- `docs/PLAN.md`
- `docs/GUIDE.md`
- `agents/AGENTS.md` if any contributor-facing guidance needs updates

## Problem

Manifest support creates new operator expectations:

- where manifests live
- how precedence works
- how validation errors appear
- how manifests relate to built-in roles and the existing `agents/` bundle

Without tests and docs, the feature will be fragile and confusing.

## Task

Add or update automated tests and operator-facing documentation for manifest-backed agents.

## Required Coverage

Testing should cover:

- manifest schema parsing
- discovery and precedence
- loader validation
- runtime integration
- compatibility when no manifests exist

Documentation should explain:

- project-level manifest location
- user-level manifest location
- precedence rules
- how manifests differ from the `agents/` workflow guidance bundle
- common failure modes

## Constraints

- Keep docs aligned with the implemented behavior, not aspirational behavior.
- Do not turn this into a broad documentation rewrite outside Phase 2 scope.
- Preserve CLI-only product framing.

## Acceptance Criteria

- Manifest behavior is covered by automated tests.
- Operator-facing docs explain how to use the feature.
- Contributor-facing guidance clearly distinguishes manifests from existing workflow guidance assets if needed.
- Remaining limitations are documented explicitly.

## Deliverable

Submit a test-and-doc patch that closes the validation gap for Phase 2 and leaves the manifest feature understandable to both operators and maintainers.
