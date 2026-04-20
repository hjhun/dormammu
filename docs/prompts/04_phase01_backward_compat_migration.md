# Phase 01 Prompt: Backward-Compatible Role Migration

## Objective

Implement the backward-compatibility slice of Phase 1 from `docs/PLAN.md`.

## Background

`dormammu` already has active loop and pipeline behavior tied to existing role semantics. Phase 1 must not break those paths while introducing typed agent profiles and profile-aware config loading.

Important runtime areas:

- `backend/dormammu/loop_runner.py`
- `backend/dormammu/daemon/pipeline_runner.py`
- `backend/dormammu/agent/cli_adapter.py`
- any role/config models currently used by those modules

## Problem

If Phase 1 adds a new profile model without a compatibility bridge, the runtime will split into old and new execution paths.

That would increase complexity instead of reducing it.

## Task

Add a compatibility layer that maps the existing role-based runtime into the new profile model.

The migration layer should:

- preserve current role names and stage behavior
- resolve each runtime role to an effective `AgentProfile`
- avoid duplicating the same fallback logic in multiple modules
- make future removal of legacy role mapping straightforward

## Implementation Guidance

- Prefer one normalization entry point instead of local conversions scattered through the runtime.
- Keep the bridge explicit rather than magical.
- If a role has no direct profile mapping, fail clearly instead of silently guessing.
- Update only the minimum runtime call sites needed to consume the normalized profile.

## Acceptance Criteria

- Existing loop execution still works through the new normalization path.
- Existing pipeline execution still works through the new normalization path.
- The legacy role vocabulary is preserved externally for now.
- Internal code is simpler because profile resolution is centralized.

## Validation

Add or update tests that cover:

- loop runner profile resolution
- pipeline runner profile resolution
- fallback behavior for existing configs
- clear failure behavior for invalid mappings

## Deliverable

Produce a compatibility-focused patch that routes current runtime roles through the new profile model while preserving behavior.
