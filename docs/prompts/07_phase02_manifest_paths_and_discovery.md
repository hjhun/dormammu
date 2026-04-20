# Phase 02 Prompt: Manifest Paths and Discovery

## Objective

Implement manifest path conventions and discovery for Phase 2 from `docs/PLAN.md`.

## Background

`dormammu` already has path conventions for global and repository state through `AppConfig`, `global_home_dir`, `agents_dir`, and repo-root guidance lookup. Phase 2 should add a clean discovery model for custom agent manifests that fits those existing conventions.

Inspect first:

- `backend/dormammu/config.py`
- `backend/dormammu/guidance.py`
- `backend/dormammu/agent/role_config.py`
- `agents/`

## Problem

Without canonical discovery rules, manifest-backed agents will become ambiguous and hard to debug. The runtime needs to know:

- where project-level agent manifests live
- where user-level agent manifests live
- how precedence works when names collide
- how to keep custom manifests separate from packaged workflow guidance

## Task

Implement path resolution and discovery rules for agent manifests.

Your implementation should:

- choose canonical project-local and user-local manifest directories
- expose those directories through config or runtime helpers
- discover manifest files deterministically
- define and enforce precedence when the same agent name exists in more than one scope

## Required Design Properties

- Discovery must be deterministic.
- The chosen paths must fit the current repo and home-directory conventions.
- The system must not silently load duplicate manifests without a clear rule.
- The discovery model must be inspectable later through CLI or logs.

## Constraints

- Keep this separate from skill discovery unless a small shared utility clearly improves both systems.
- Do not add hook behavior in this slice.
- Avoid changing the existing guidance resolution behavior unless it is strictly necessary.

## Acceptance Criteria

- The runtime can enumerate candidate manifest files from project and user scope.
- Precedence is explicit in code and tests.
- The chosen directories do not conflict with the existing `agents/` guidance asset model.
- The resulting discovery model is suitable for later runtime integration.

## Validation

Add or update tests for:

- project-only manifests
- user-only manifests
- duplicate names across scopes
- precedence resolution
- missing directories and empty directories

## Deliverable

Produce a focused patch that adds manifest path conventions, discovery helpers, and precedence tests.
