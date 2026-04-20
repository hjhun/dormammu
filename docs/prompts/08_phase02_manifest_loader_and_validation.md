# Phase 02 Prompt: Manifest Loader and Validation Errors

## Objective

Implement the manifest loading and validation layer for Phase 2 from `docs/PLAN.md`.

## Background

Once schema and discovery exist, `dormammu` needs a loader that turns discovered manifest files into validated runtime agent definitions.

Relevant files:

- `backend/dormammu/config.py`
- `backend/dormammu/agent/role_config.py`
- Phase 1 profile and permission foundation
- any new Phase 2 schema and discovery modules introduced earlier

## Problem

Discovery alone is not enough. The runtime needs one place that:

- reads manifest files
- validates them
- normalizes them
- produces runtime-ready agent definitions
- emits useful errors when something is wrong

## Task

Build the manifest loader layer.

The loader should:

- consume manifest files discovered from project and user scope
- validate file content against the manifest schema
- normalize paths relative to the manifest location where appropriate
- emit stable internal agent definitions ready to convert into `AgentProfile`
- surface actionable error messages for malformed manifests

## Error-Handling Requirements

Validation and load errors should identify:

- the manifest path
- the field or section that failed
- the reason it failed

Prefer deterministic failure over partial silent loading.

## Constraints

- Do not scatter manifest parsing across loop or pipeline modules.
- Keep manifest loading centralized.
- Do not silently drop invalid manifests unless there is a deliberate warning model with tests.

## Acceptance Criteria

- Manifest loading happens through a dedicated runtime layer or service.
- Good manifests produce normalized runtime definitions.
- Bad manifests fail clearly.
- Relative-path handling is correct and tested.
- The loader can be reused by later runtime integration and inspect commands.

## Validation

Add or update tests for:

- successful load of multiple manifests
- malformed frontmatter or malformed config content
- invalid relative path handling
- collision handling if loader owns part of precedence enforcement
- readable error messages

## Deliverable

Submit a focused patch that adds centralized manifest loading, normalization, and validation coverage.
