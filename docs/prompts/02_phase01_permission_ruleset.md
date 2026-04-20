# Phase 01 Prompt: Permission Ruleset Foundation

## Objective

Implement the permission-model foundation for Phase 1 from `docs/PLAN.md`.

## Background

The long-term plan calls for typed agent profiles with explicit control over:

- tools
- filesystem scope
- network access
- worktree usage

This prompt covers only the permission ruleset foundation, not the final enforcement of every permission at runtime.

Current files to inspect first:

- `backend/dormammu/config.py`
- `backend/dormammu/agent/cli_adapter.py`
- `backend/dormammu/loop_runner.py`
- `backend/dormammu/daemon/pipeline_runner.py`

## Problem

`dormammu` does not yet have a first-class permission ruleset that can be attached to an agent profile and evaluated consistently.

Without that, later work on manifests, hooks, MCP, and worktree policy will stay ambiguous.

## Task

Add a structured permission ruleset model suitable for agent profiles.

The ruleset should support, at minimum:

- tool policy
- filesystem policy
- network policy
- worktree policy

The first implementation can be simple, but it must be typed and extensible.

## Scope

In scope:

- schema or dataclass definitions
- normalization helpers
- default values for built-in profiles
- evaluation helpers suitable for later enforcement

Out of scope:

- full hook integration
- MCP-specific behavior
- full worktree implementation
- large runtime rewrites

## Design Requirements

- Use explicit allow/deny/ask style semantics where appropriate.
- Keep the evaluation contract deterministic.
- Separate the rule model from command execution details.
- Avoid baking repository-specific policy into the core types.

## Acceptance Criteria

- Permission policy is represented by typed runtime structures.
- Built-in profiles can carry default permission values.
- There is a clear evaluation helper or resolver for later runtime checks.
- The code path is compatible with future project-level overrides.
- Tests cover rule normalization and evaluation behavior.

## Validation

Add or update tests for:

- default permission resolution
- overrides for one or more built-in profiles
- allow/deny/ask evaluation behavior
- serialization or config loading if introduced in this slice

## Deliverable

Produce a narrow patch that adds the permission ruleset foundation and associated tests, ready for later enforcement work.
