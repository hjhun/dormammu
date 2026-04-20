# Phase 05 Prompt: Skill Discovery Paths and Precedence

## Objective

Implement skill discovery paths and precedence for Phase 5 from `docs/PLAN.md`.

## Background

The plan calls for:

- consistent discovery of repo-local and user-local skills
- duplicate-name conflict policy
- visibility into loaded skills

`dormammu` already has path conventions for repo guidance and packaged assets through `AppConfig`, but it does not yet have a canonical runtime skill discovery layer.

## Problem

Without explicit discovery rules, runtime skill loading will be inconsistent and hard to debug.

The runtime needs to know:

- where project-local skills live
- where user-local skills live
- how packaged skills participate
- what happens when two skills share the same name

## Task

Implement path discovery and precedence rules for runtime skills.

The discovery layer should:

- enumerate candidate skill directories and files
- support project scope and user scope
- include packaged or built-in skills where appropriate
- define deterministic precedence for duplicate skill names

## Design Guidance

- Align skill discovery with existing repo and home-directory conventions in `AppConfig`.
- Make precedence explicit in code and tests.
- Distinguish packaged built-ins from project overrides and user overrides.
- Keep discovery logic separate from permission filtering.

## Constraints

- Do not yet implement full runtime integration into every prompt path.
- Avoid coupling skill discovery to unrelated manifest loading unless a shared utility clearly improves both.
- Do not silently merge conflicting skills with ambiguous rules.

## Acceptance Criteria

- The runtime can enumerate candidate skills from project, user, and packaged scopes.
- Duplicate-name precedence is explicit and deterministic.
- Missing directories and empty directories are handled safely.
- The discovery layer is ready for later permission-aware filtering.

## Validation

Add or update tests for:

- project-only skills
- user-only skills
- packaged-only skills
- duplicate names across scopes
- empty or missing discovery roots

## Deliverable

Produce a focused patch that adds skill discovery paths, precedence rules, and tests.
