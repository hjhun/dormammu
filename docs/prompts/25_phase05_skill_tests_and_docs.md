# Phase 05 Prompt: Skill Validation and Documentation

## Objective

Complete the validation and documentation slice for Phase 5 from `docs/PLAN.md`.

## Background

Permission-aware skill discovery introduces a new runtime subsystem that operators and contributors need to understand clearly.

Relevant documentation and validation surfaces include:

- tests for config, runtime metadata, and prompt assembly
- `docs/GUIDE.md`
- contributor-facing guidance where skill behavior needs clarification
- any state schema or operator metadata docs updated during Phase 5

## Problem

If the skill subsystem is not documented and tested, users will confuse:

- skills
- general `AGENTS.md` guidance
- packaged workflow instructions
- profile-specific preloaded capabilities

That confusion will make later MCP and inspection work harder.

## Task

Add or update automated tests and documentation for the Phase 5 skill subsystem.

## Required Coverage

Testing should cover:

- skill schema validation
- discovery and precedence
- permission-aware filtering
- runtime integration and visibility
- compatibility when no extra skills are present

Documentation should explain:

- what a runtime skill is
- where project and user skills live
- how precedence works
- how skill visibility depends on agent profiles
- how skills differ from `AGENTS.md` and workflow guidance

## Constraints

- Keep docs aligned with implemented behavior.
- Do not over-document future phases that are not built yet.
- Preserve CLI-only product framing.

## Acceptance Criteria

- The Phase 5 skill subsystem is covered by automated tests.
- Operator-facing docs explain skill discovery and visibility clearly.
- Contributor-facing docs distinguish skills from general guidance assets.
- Remaining limitations are explicit.

## Deliverable

Submit a test-and-doc patch that closes the validation gap for Phase 5 and leaves the skill subsystem understandable to operators and maintainers.
