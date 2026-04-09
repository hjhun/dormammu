# AGENTS.md

## Purpose

This repository is building `dormammu`, a Python-based coding agent loop
orchestrator with:

- standalone Python execution for core workflows
- CLI entrypoints for terminal-first usage
- resumable execution
- Markdown-based state management under `.dev/`
- supervisor-driven validation
- packaging and deployment support

The product surface is CLI-only. Web UI and browser-served control paths are
not part of the current product scope.

All agent work in this repository must help advance the goals defined in:

- `.dev/PROJECT.md`
- `.dev/ROADMAP.md`

## Source Of Truth

Use the following precedence order when deciding what to do next:

1. Direct user request
2. `.dev/PROJECT.md`
3. `.dev/ROADMAP.md`
4. Current `.dev` execution state files
5. Current repository contents

## Required Workflow

All substantial work should follow this sequence:

1. Plan
2. Design
3. Develop
4. Test Authoring
5. Build and Deploy
6. Test and Review
7. Commit

Use the supervisor skill as the controller for every multi-step implementation
effort.

After design, the supervisor should route two implementation tracks as needed:

- the development skill for product code
- the test authoring skill for automated test code

Execute validation only after the active development slice is complete. Default
validation coverage is unit test plus integration test. Add system tests only
when the prompt or acceptance criteria explicitly require system-test-level
coverage; when that happens, run them in a real device or equivalent executable
environment when available.

## Skill Routing

Use the distributable workflow bundle under `agents/` to execute each phase:

- Planning and Design workflow: `agents/workflows/planning-design.md`
- Development and Test Authoring workflow: `agents/workflows/develop-test-authoring.md`
- Build Deploy and Test Review workflow: `agents/workflows/build-deploy-test-review.md`
- Cleanup and Commit workflow: `agents/workflows/cleanup-commit.md`

Use the skills under `agents/skills/` when a workflow document routes to a
specific skill:

- Planning: `agents/skills/planning-agent/SKILL.md`
- Design: `agents/skills/designing-agent/SKILL.md`
- Development: `agents/skills/developing-agent/SKILL.md`
- Test Authoring: `agents/skills/test-authoring-agent/SKILL.md`
- Build and Deploy: `agents/skills/building-and-deploying/SKILL.md`
- Test and Review: `agents/skills/testing-and-reviewing/SKILL.md`
- Commit: `agents/skills/committing-agent/SKILL.md`
- Supervision: `agents/skills/supervising-agent/SKILL.md`

## Phase Expectations

### 1. Plan

- update `.dev/DASHBOARD.md` with the actual in-progress status for the active scope
- update `.dev/TASKS.md` with prompt-derived development items in `[ ] Phase N. <title>` form
- update `.dev/ROADMAP.md` when roadmap slices change
- record the active phase and next action

### 2. Design

Focus on:

- module boundaries
- interfaces and contracts
- state files and schemas
- recovery and resumability
- validation strategy

### 3. Develop

Implement only the active scoped slice.

Rules:

- keep changes incremental and verifiable
- preserve unrelated user changes
- keep the repo resumable after each meaningful update
- coordinate with the test authoring skill so product code and test code stay aligned
- route back to design when implementation exposes a gap

### 4. Test Authoring

Use this phase after design to author test code for the active scope.

Rules:

- assign test code ownership to the dedicated test authoring skill
- write unit tests and integration tests by default
- add system tests only when the prompt or acceptance criteria explicitly call
  for system-test-level validation
- if system tests require a real device or equivalent environment and that
  environment is unavailable, record the gap explicitly instead of pretending
  coverage exists

### 5. Build And Deploy

Use this phase when the roadmap requires packaging, install flows, release
artifacts, or deployability checks.

### 6. Test And Review

Validation must include, when relevant:

- unit tests
- integration tests
- system tests when explicitly requested
- linters
- build checks
- smoke checks
- review of changed files for bugs, regressions, and missing edge cases

Run this phase after the developer agent has finished the active implementation
slice. Do not treat authored test code as executed validation.

### 7. Commit

Use the committing skill only after the active scope has passed validation or
the user explicitly asks for commit preparation.

## `.dev` State Management

When a workflow is active, keep these files aligned when they exist:

- `.dev/DASHBOARD.md`
- `.dev/ROADMAP.md`
- `.dev/TASKS.md`
- `.dev/workflow_state.json`
- `.dev/session.json`
- `.dev/logs/`

Treat `.dev/workflow_state.json` as machine truth and Markdown files as
operator-facing state.

Use the Markdown files with these roles:

- `.dev/DASHBOARD.md`: show the real current progress, active phase, next action,
  risks, and notable in-progress context for the active scope
- `.dev/TASKS.md`: list the development work derived from the current user prompt
  or scope in ordered phase items such as `[ ] Phase 1. <title>`

## Roadmap Alignment

Prefer roadmap execution in this order unless the user redirects the priority:

1. Phase 1. Core Foundation and Repository Bootstrap
2. Phase 2. `.dev` State Model and Template Generation
3. Phase 3. Agent CLI Adapter and Single-Run Execution
4. Phase 4. Supervisor Validation, Continuation Loop, and Resume
5. Phase 5. CLI Operator Experience and Progress Visibility
6. Phase 6. Installer, Commands, and Environment Diagnostics
7. Phase 7. Hardening, Multi-Session, and Productization

## Resume Behavior

When resuming work after interruption:

1. read current `.dev` state
2. verify whether dashboard, tasks, and machine state agree
3. identify the earliest uncertain phase
4. resume from that phase rather than assuming later phases are valid

## Default Agent Posture

When working in this repository, agents should:

- be explicit about the active phase
- use the mapped workflow skill for that phase
- refer to adjacent workflow skills when handoff or collaboration is required
- let the supervisor govern transitions
- keep progress visible in `.dev`
- prefer deterministic checks before semantic judgment
- preserve resumability at every step
