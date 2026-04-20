# Phase 01 Prompt: Config Loader and Precedence

## Objective

Implement the configuration-loading slice for Phase 1 from `docs/PLAN.md`: agent-profile loading and deterministic precedence.

## Background

`backend/dormammu/config.py` already resolves repository and global config. The next step is to make agent-profile configuration load through an explicit precedence model instead of being scattered across runtime code.

Relevant files:

- `backend/dormammu/config.py`
- `backend/dormammu/agent/cli_adapter.py`
- `backend/dormammu/loop_runner.py`
- `backend/dormammu/daemon/pipeline_runner.py`

## Problem

Even if `AgentProfile` and permission structures exist, they are not useful unless the runtime has a canonical way to build effective profiles from:

- built-in defaults
- project config
- global config
- existing role-based compatibility inputs

## Task

Extend config loading so `dormammu` can resolve effective agent profiles through a deterministic precedence model.

The implementation should:

- define where built-in defaults live
- merge external config into those defaults predictably
- preserve the current config file discovery behavior
- keep backward compatibility with the existing configuration contract

## Required Precedence Direction

Use a precedence order that is explicit in code and tests. A reasonable target is:

1. built-in profile defaults
2. global config overrides
3. project config overrides
4. explicit runtime overrides when already supported

If the existing config system requires a slightly different ordering, document and test it clearly.

## Constraints

- Do not introduce a breaking config migration in this slice.
- Avoid unrelated cleanup in `config.py`.
- Keep JSON config compatibility.
- Preserve current repo-root and global-home resolution behavior.

## Acceptance Criteria

- Effective agent profiles can be resolved from config in one place.
- The precedence model is explicit and tested.
- Existing runtime behavior continues to work when no new profile config is present.
- It is easy to add project-level manifest support later without redesigning this merge logic.

## Validation

Add or update tests for:

- built-in defaults only
- global override behavior
- project override behavior
- conflict resolution between global and project config
- behavior when profile-specific config is absent

## Deliverable

Submit a focused patch that adds effective profile loading and precedence tests, without taking on later-phase manifest or hook work.
