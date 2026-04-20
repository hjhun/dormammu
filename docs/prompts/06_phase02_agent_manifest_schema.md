# Phase 02 Prompt: Agent Manifest Schema

## Objective

Implement the schema foundation for Phase 2 from `docs/PLAN.md`: user and project agent manifests.

## Background

Phase 1 introduced typed agent profiles and profile-aware configuration. Phase 2 should make those profiles extensible from disk so projects and individual operators can add agent definitions without editing Python source.

Relevant code and structure to inspect first:

- `backend/dormammu/agent/role_config.py`
- `backend/dormammu/config.py`
- `backend/dormammu/guidance.py`
- `agents/`
- `docs/PLAN.md`

## Problem

The runtime still depends on built-in role configuration and config-file overrides. There is no durable on-disk manifest format for:

- project-scoped custom agents
- user-scoped personal agents
- future profile extension without code edits

## Task

Design and implement a typed manifest schema for agent definitions on disk.

The first version should cover, at minimum:

- agent identifier or name
- description
- prompt or instruction body
- source scope such as built-in, project, or user
- CLI override
- model override
- permission section
- optional preloaded skills
- optional metadata for future use

## Design Requirements

- The schema must map cleanly into the Phase 1 `AgentProfile` model.
- The format must be human-editable.
- Validation failures must be specific and actionable.
- The format must be stable enough for future project sharing.

## Guidance

- You may choose Markdown frontmatter, YAML, or JSON-backed manifests, but optimize for readability and version-controlled editing.
- Keep the first version small and explicit.
- Do not overload the existing `agents/` workflow guidance bundle with a second meaning unless the integration is deliberate and cleanly justified.

## Constraints

- Do not implement discovery or runtime loading in this slice unless needed to validate the schema.
- Do not redesign the guidance-file prompt assembly in this slice.
- Do not break current built-in role behavior.

## Acceptance Criteria

- A typed manifest schema exists in the runtime.
- A parser or decoder can convert manifest data into an internal profile-ready representation.
- Invalid manifests produce precise errors.
- The schema is documented in code or tests well enough for later discovery work.

## Validation

Add or update tests for:

- valid manifest parsing
- missing required fields
- invalid types
- unknown or unsupported fields if relevant
- conversion from manifest data into internal agent-profile structures

## Deliverable

Submit a focused patch that introduces the manifest schema, parser, and tests, ready for the discovery and loader work in later Phase 2 slices.
