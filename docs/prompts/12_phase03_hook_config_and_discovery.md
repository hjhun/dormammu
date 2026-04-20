# Phase 03 Prompt: Hook Configuration and Discovery

## Objective

Implement hook configuration and discovery for Phase 3 from `docs/PLAN.md`.

## Background

Once the hook schema exists, the runtime needs a deterministic way to discover and load hook definitions from configuration.

Relevant files to inspect first:

- `backend/dormammu/config.py`
- any new Phase 3 schema modules
- Phase 2 manifest-loading conventions if they are already available

## Problem

Hooks cannot be safely introduced without a clear answer to:

- where hook definitions live
- how they are configured
- how project and user scope interact
- how precedence and overrides work

## Task

Implement hook configuration and discovery rules.

The implementation should:

- define where hook configuration is declared
- support deterministic loading from the chosen config layers
- expose effective hook configuration to the runtime through a centralized loader
- define precedence explicitly

## Design Guidance

- Align the hook config approach with existing `AppConfig` behavior.
- Keep discovery and resolution deterministic.
- Make it possible to inspect effective hooks later through CLI or logs.
- Avoid coupling hook discovery to unrelated manifest or guidance loading unless the shared mechanism is truly justified.

## Constraints

- Do not wire the entire execution engine in this slice.
- Do not implement hook effects in multiple runtime modules directly.
- Avoid inventing a second ambiguous configuration path if existing config layers can carry the feature cleanly.

## Acceptance Criteria

- Hook config can be loaded deterministically from runtime config.
- Precedence is explicit and tested.
- The resulting effective hook definitions are centralized and reusable.
- Invalid hook config fails clearly.

## Validation

Add or update tests for:

- no hook config present
- global hook config
- project hook config
- precedence between scopes
- malformed hook config

## Deliverable

Produce a focused patch that adds hook configuration loading and discovery behavior with clear precedence tests.
