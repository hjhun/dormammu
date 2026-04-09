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
4. Build and Deploy
5. Test and Review
6. Commit

Use the supervisor skill as the controller for every multi-step implementation
effort.

## Skill Routing

Use the skills under `.agents/skills/` to execute each phase:

- Planning: `.agents/skills/planning-agent-workflows/SKILL.md`
- Design: `.agents/skills/designing-agent-workflows/SKILL.md`
- Development: `.agents/skills/developing-agent-workflows/SKILL.md`
- Build and Deploy: `.agents/skills/building-and-deploying-workflows/SKILL.md`
- Test and Review: `.agents/skills/testing-and-reviewing-workflows/SKILL.md`
- Commit: `.agents/skills/committing-agent-workflows/SKILL.md`
- Supervision: `.agents/skills/supervising-agent-workflows/SKILL.md`

## Phase Expectations

### 1. Plan

- update `.dev/DASHBOARD.md`
- update `.dev/TASKS.md`
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
- route back to design when implementation exposes a gap

### 4. Build And Deploy

Use this phase when the roadmap requires packaging, install flows, release
artifacts, or deployability checks.

### 5. Test And Review

Validation must include, when relevant:

- tests
- linters
- build checks
- smoke checks
- review of changed files for bugs, regressions, and missing edge cases

### 6. Commit

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
- let the supervisor govern transitions
- keep progress visible in `.dev`
- prefer deterministic checks before semantic judgment
- preserve resumability at every step
