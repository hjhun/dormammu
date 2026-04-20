# Phase 05 Prompt: Skill Model and Schema

## Objective

Implement the schema foundation for Phase 5 from `docs/PLAN.md`: permission-aware skill discovery.

## Background

`dormammu` already ships a workflow guidance bundle under `agents/`, and the runtime already references guidance and skill-related content in several places:

- guidance prompt assembly
- continuation prompt composition
- packaged `agents/` assets
- Telegram skill-tail progress summaries

However, there is not yet a first-class runtime skill model.

Relevant files to inspect first:

- `backend/dormammu/guidance.py`
- `backend/dormammu/continuation.py`
- `backend/dormammu/config.py`
- `agents/`
- `docs/PLAN.md`

## Problem

The runtime uses skill content indirectly, but it has no typed model for:

- what a skill is
- where a skill came from
- how a skill should be loaded
- how a skill should be filtered per agent profile

That makes later discovery and permission work ambiguous.

## Task

Design and implement a typed runtime skill model and schema.

The first version should define, at minimum:

- skill identifier or name
- description
- source scope such as built-in, project, or user
- source path
- content or content-loading contract
- optional metadata for future filtering

## Design Requirements

- The model must support future permission-aware filtering.
- The model must make source precedence explicit.
- The model must distinguish skills from general guidance files such as `AGENTS.md`.
- The model should be compatible with the existing `agents/skills/**/SKILL.md` layout.

## Constraints

- Do not implement full discovery or runtime filtering in this slice unless needed for validation.
- Do not repurpose `AGENTS.md` as a skill file.
- Keep the first version small and typed.

## Acceptance Criteria

- A typed runtime skill model exists.
- A schema or parser contract exists for skill documents.
- The model can represent repo-local and user-local skills later without redesign.
- Tests cover schema validation and normalization.

## Validation

Add or update tests for:

- valid skill metadata parsing
- missing required fields
- invalid types
- source scope normalization
- mapping from on-disk skill data into runtime skill objects

## Deliverable

Submit a focused patch that introduces the runtime skill model and tests, ready for discovery and permission-aware loading in later Phase 5 slices.
