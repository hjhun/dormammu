# Phase 01 Prompt: Agent Profile Schema

## Objective

Implement the first slice of Phase 1 from `docs/PLAN.md`: introduce a typed `AgentProfile` contract for `dormammu` without breaking the current role-based runtime.

## Background

`dormammu` already has strong orchestration primitives, but its agent configuration surface is still fragmented across runtime-specific structures and ad hoc role handling. The goal of this slice is to define a stable schema that later phases can build on.

Current architectural hotspots:

- `backend/dormammu/config.py`
- `backend/dormammu/loop_runner.py`
- `backend/dormammu/daemon/pipeline_runner.py`
- `backend/dormammu/agent/cli_adapter.py`

Relevant design references:

- `docs/PLAN.md`
- `docs/PLAN_ko.md`
- `.dev/PROJECT.md`
- `.dev/ROADMAP.md`

## Problem

The runtime currently relies on implicit role semantics instead of an explicit agent-profile model. That makes it hard to add:

- per-profile permission policy
- per-profile CLI/model overrides
- deterministic precedence rules
- future manifest-backed custom agents

## Task

Design and implement a typed `AgentProfile` schema plus a minimal loader layer that can coexist with current configuration.

The implementation should:

- define a new schema or dataclass model for agent profiles
- support these profile concepts:
  - profile name
  - human description
  - source type such as built-in or configured
  - CLI override
  - model override
  - permission policy placeholder or structured field
  - worktree policy placeholder or structured field
- provide a canonical mapping from the current pipeline roles to initial built-in profiles
- preserve backward compatibility with existing config and runtime paths

## Constraints

- Do not redesign the whole runtime in this slice.
- Do not implement hooks, worktree execution, or MCP behavior yet.
- Do not widen the CLI surface unless strictly required for inspection or internal use.
- Keep the current interactive and goals-scheduler paths working.
- Preserve CLI-only product scope.

## Suggested Implementation Shape

- Introduce a new module dedicated to agent profiles.
- Keep the first version small and explicit.
- Use the new model as an internal normalization layer rather than a breaking config rewrite.
- Add conversion helpers from current config structures into `AgentProfile`.

## Acceptance Criteria

- A typed `AgentProfile` structure exists in the runtime.
- Built-in profiles exist for the current workflow roles or their equivalent operational modes.
- Existing runtime code can resolve a profile for a given role without changing user-facing behavior.
- The implementation is test-covered.
- The changes are narrow enough that later phases can attach permissions and manifests cleanly.

## Validation

Add or update tests that prove:

- built-in profiles load deterministically
- missing optional fields are handled safely
- existing role-based config still resolves into valid profiles
- profile resolution is stable across loop and pipeline code paths

## Deliverable

Submit a focused patch that adds the profile model, normalization layer, and tests, with concise comments only where the design is not obvious.
