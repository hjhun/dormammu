# Phase 06 Prompt: MCP Permission and Hook Boundary

## Objective

Integrate MCP with the permission and hook boundary for Phase 6 from `docs/PLAN.md`.

## Background

The plan explicitly requires MCP access to be routed through the same permission and hook layers as native tools.

Earlier phases establish:

- typed agent profiles
- permission rulesets
- hook schema and runtime integration

Phase 6 must connect MCP to those boundaries rather than treating it as a side channel.

## Problem

If MCP is integrated as a bypass path, it will undermine the permission and hook model already introduced in earlier phases.

## Task

Design and implement the permission and hook boundary for MCP access.

The implementation should:

- model MCP access as a governed runtime action
- ensure profile-level access control is enforced before MCP use
- define where hook events are emitted around MCP invocation
- preserve clear blocking and diagnostic behavior

## Design Requirements

- MCP should not bypass permission rules.
- MCP should not bypass hook evaluation.
- The resulting control flow should be explicit and reusable.
- Failures should remain readable when a server is denied, unavailable, or blocked by hooks.

## Constraints

- Do not overbuild the full adapter execution stack in this slice if the boundary can be implemented first.
- Avoid introducing a parallel permission model just for MCP.
- Keep the implementation centralized.

## Acceptance Criteria

- MCP access is routed through permission-aware decision logic.
- MCP access can trigger hook evaluation through the existing hook system.
- The deny or block path is explicit and testable.
- The design preserves the same governance model used for native tools.

## Validation

Add or update tests for:

- MCP allowed by profile and permissions
- MCP denied by profile or permissions
- MCP blocked or annotated by hooks
- readable failure behavior when a configured server is unavailable

## Deliverable

Submit a focused patch that establishes the permission-and-hook boundary for MCP access.
