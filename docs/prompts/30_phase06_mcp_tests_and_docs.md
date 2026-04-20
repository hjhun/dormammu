# Phase 06 Prompt: MCP Validation and Documentation

## Objective

Complete the validation and documentation slice for Phase 6 from `docs/PLAN.md`.

## Background

MCP is a new product boundary in `dormammu`. Once introduced, it needs:

- strong automated validation
- explicit operator-facing documentation
- clear explanation of how MCP fits with profiles, permissions, and hooks

Relevant surfaces:

- tests for config, permissions, hooks, and runtime integration
- `docs/GUIDE.md`
- any new MCP-related docs added during Phase 6

## Problem

Without tests and documentation, MCP will be difficult to reason about and easy to misuse, especially if operators assume it bypasses the existing runtime governance model.

## Task

Add or update automated tests and documentation for the Phase 6 MCP subsystem.

## Required Coverage

Testing should cover:

- MCP config schema validation
- server registration and resolution
- permission-aware access control
- hook-aware governance behavior
- runtime adapter behavior
- compatibility when no MCP servers are configured

Documentation should explain:

- how MCP servers are configured
- how profile allowlists work
- how MCP interacts with permissions and hooks
- expected failure behavior for unavailable or blocked servers
- current limitations

## Constraints

- Keep docs aligned with implemented behavior.
- Do not over-document future phases that are not yet built.
- Preserve CLI-only product framing.

## Acceptance Criteria

- The Phase 6 MCP subsystem is covered by automated tests.
- Operator-facing docs explain MCP configuration and governance clearly.
- The relationship between MCP, permissions, and hooks is explicit.
- Remaining limitations are documented.

## Deliverable

Submit a test-and-doc patch that closes the validation gap for Phase 6 and leaves the MCP subsystem understandable to operators and maintainers.
