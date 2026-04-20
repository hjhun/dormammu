# Phase 06 Prompt: MCP Config Schema

## Objective

Implement the schema foundation for Phase 6 from `docs/PLAN.md`: MCP integration surface.

## Background

The plan calls for MCP to become a first-class runtime boundary in `dormammu`, with:

- project-level MCP server definitions
- per-agent MCP allowlists
- routing through permissions and hooks

The current codebase does not yet have a dedicated MCP configuration model.

Relevant files to inspect first:

- `backend/dormammu/config.py`
- Phase 1 agent-profile and permission models
- Phase 3 hook models
- `docs/PLAN.md`

## Problem

MCP cannot be integrated safely unless the runtime has a typed configuration contract for:

- server identity
- transport or launch mechanism
- scope
- profile-level access
- failure policy

## Task

Design and implement a typed MCP configuration schema for `dormammu`.

The first version should define, at minimum:

- MCP server identifier
- server enable/disable state
- execution or connection configuration
- agent-profile allowlist or equivalent access mapping
- validation-friendly metadata for diagnostics

## Design Requirements

- The schema must fit into the existing project and agent config model.
- Validation failures must be specific and actionable.
- The schema should leave room for future server transport variations without redesigning the public contract.
- The schema must separate configuration identity from runtime connection logic.

## Constraints

- Do not implement the full adapter or runtime invocation in this slice.
- Do not add speculative cloud or hosted-control-plane behavior.
- Keep the first version explicit and typed.

## Acceptance Criteria

- A typed MCP config schema exists.
- The schema can represent project-level server definitions and profile-level access control.
- Invalid MCP config fails clearly.
- The contract is suitable for later adapter and permission integration.

## Validation

Add or update tests for:

- valid MCP config parsing
- missing required fields
- invalid field types
- invalid profile allowlist references if applicable
- normalization of config data into runtime-ready structures

## Deliverable

Submit a focused patch that introduces the MCP config schema and tests, ready for discovery and runtime adapter work in later Phase 6 slices.
