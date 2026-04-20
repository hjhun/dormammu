# Phase 02 Prompt: Runtime Integration for Manifest-Backed Agents

## Objective

Integrate manifest-backed agent definitions into the runtime for Phase 2 from `docs/PLAN.md`.

## Background

Phase 1 established typed agent profiles. Earlier Phase 2 slices define manifest schema, discovery, and loading. This slice should connect those pieces so manifest-backed agents actually participate in effective profile resolution.

Inspect first:

- `backend/dormammu/agent/role_config.py`
- `backend/dormammu/config.py`
- `backend/dormammu/loop_runner.py`
- `backend/dormammu/daemon/pipeline_runner.py`
- any new Phase 1 and Phase 2 modules added previously

## Problem

Custom agent manifests are not useful until the runtime can resolve them as part of effective profile construction and role execution.

## Task

Integrate manifest-backed agents into the existing runtime without breaking built-in roles.

The integration should support:

- built-in role defaults
- config-based overrides
- manifest-backed custom agents
- deterministic resolution when a runtime role maps to a manifest-defined profile or override

## Design Guidance

- Keep built-in roles as the default path.
- Treat manifests as an extension layer, not a replacement for the current pipeline contract.
- Centralize resolution instead of adding bespoke branching in multiple runtime modules.
- Make it obvious which source produced the final effective profile.

## Constraints

- Do not rewrite the entire pipeline role model in this slice.
- Do not add hooks, worktrees, or MCP-specific behavior here.
- Preserve current interactive and goals-scheduler execution behavior.

## Acceptance Criteria

- The runtime can resolve effective profiles that include manifest-backed agent definitions.
- Existing built-in roles still work when no manifests are present.
- Resolution behavior is deterministic and inspectable.
- Runtime integration does not duplicate profile-selection logic across modules.

## Validation

Add or update tests for:

- no manifests present
- user manifest present
- project manifest present
- project/user collision behavior
- runtime role resolution through manifest-backed definitions
- compatibility with existing built-in execution paths

## Deliverable

Produce a focused patch that wires manifest-backed agents into effective runtime profile resolution while preserving current behavior.
