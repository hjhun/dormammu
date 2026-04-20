# Phase 06 Prompt: MCP Registration and Resolution

## Objective

Implement MCP server registration and resolution for Phase 6 from `docs/PLAN.md`.

## Background

Once an MCP config schema exists, the runtime needs a centralized way to register configured servers and resolve which servers are available to which agent profiles.

Relevant areas:

- `backend/dormammu/config.py`
- Phase 1 profile resolution
- Phase 2 manifest-backed agent definitions
- Phase 6 MCP schema introduced earlier

## Problem

Without a centralized registry or resolution layer, MCP usage will become fragmented and hard to debug.

The runtime needs one place that can answer:

- which MCP servers are configured
- which are enabled
- which are available to a specific effective agent profile
- what should happen when configuration is invalid or incomplete

## Task

Implement MCP registration and resolution behavior.

The resolution layer should:

- build an effective MCP server registry from configuration
- expose enabled servers deterministically
- resolve server visibility per effective agent profile
- prepare the runtime for later permission and hook enforcement

## Design Guidance

- Keep registration and resolution separate from transport execution.
- Make profile-level access explicit.
- Use deterministic precedence and stable identifiers.
- Preserve behavior when no MCP servers are configured.

## Constraints

- Do not implement actual server process management in this slice unless needed for lightweight validation.
- Avoid scattering MCP resolution logic across runtime modules.
- Keep the first version focused on configuration-to-runtime mapping.

## Acceptance Criteria

- The runtime can build an effective MCP registry from config.
- The runtime can resolve which MCP servers are visible to a given profile.
- Misconfigured or disabled servers are handled clearly.
- The resolution layer is reusable by later adapter and inspection work.

## Validation

Add or update tests for:

- no MCP servers configured
- multiple configured servers
- disabled server behavior
- profile allowlist behavior
- invalid or conflicting configuration

## Deliverable

Produce a focused patch that adds MCP registration and resolution behavior with targeted tests.
