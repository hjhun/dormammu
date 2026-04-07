# AGENTS.md

## Purpose

This repository is building `dormammu`, a Python-based coding agent loop
orchestrator with:

- standalone Python execution for core workflows
- CLI entrypoints for terminal-first usage
- resumable execution
- Markdown-based state management under `.dev/`
- supervisor-driven validation
- an optional local web UI
- packaging and deployment support

All agent work in this repository must help advance the goals defined in:

- `.dev/PROJECT.md`
- `.dev/ROADMAP.md`

Treat those two files as the primary product and delivery context for this repo.

## Source Of Truth

Use the following precedence order when deciding what to do next:

1. Direct user request
2. `.dev/PROJECT.md`
3. `.dev/ROADMAP.md`
4. Current `.dev` execution state files
5. Current repository contents

Machine state should live in `.dev/workflow_state.json` when available.
Operator-facing status should live in Markdown files under `.dev/`.
When roadmap work is completed, `.dev/ROADMAP.md` must also be updated in the
same workflow so the checklist and phase sections reflect reality.

## Required Workflow

All substantial work should follow this sequence:

1. Plan
2. Design
3. Develop
4. Build and Deploy
5. Test and Review
6. Commit

This workflow is supervised continuously. Use the supervisor skill as the
controller for every multi-step implementation effort.

If a later phase discovers missing requirements, incorrect design, failed
validation, or incomplete implementation, return to the earliest broken phase,
repair it, and then move forward again.

Never force progress to the next phase without evidence.

The core product must remain usable without the web UI. Agents should preserve
an architecture where Python modules and CLI entrypoints can run the essential
workflow independently, while the web UI acts as an optional visibility and
control layer.

## Skill Routing

Use the skills under `.agents/skills/` to execute each phase:

- Planning:
  `.agents/skills/planning-agent-workflows/SKILL.md`
- Design:
  `.agents/skills/designing-agent-workflows/SKILL.md`
- Development:
  `.agents/skills/developing-agent-workflows/SKILL.md`
- Build and Deploy:
  `.agents/skills/building-and-deploying-workflows/SKILL.md`
- Test and Review:
  `.agents/skills/testing-and-reviewing-workflows/SKILL.md`
- Commit:
  `.agents/skills/committing-agent-workflows/SKILL.md`
- Supervision:
  `.agents/skills/supervising-agent-workflows/SKILL.md`

The supervisor skill is responsible for:

- deciding the next correct phase
- checking whether state is consistent enough to continue
- preventing unsupported phase transitions
- sending work back to an earlier phase when evidence is missing
- leaving the repository in a resumable state after interruptions

## Supervisor Operating Rules

The supervisor must apply these checks before allowing a phase transition:

- Planning -> tasks exist, scope is clear, and the next action is explicit
- Design -> implementation-facing decisions exist for the active scope
- Development -> intended files changed and match the approved design
- Build and Deploy -> requested artifacts, scripts, or packaging outputs exist
- Test and Review -> validation has a clear pass, fail, or blocked outcome
- Commit -> the diff is scoped, validation is complete, and status files agree

If state is inconsistent, the supervisor must:

1. record the mismatch in `.dev`
2. choose the earliest uncertain phase
3. send the workflow back for rework
4. re-run validation before allowing progress

Escalation outcomes should be one of:

- `approved`
- `rework_required`
- `blocked`
- `manual_review_needed`

## Phase Expectations

### 1. Plan

Use the planning skill to translate the current goal into concrete, checkable
tasks.

Expected outputs:

- updated `.dev/DASHBOARD.md`
- updated `.dev/TASKS.md`
- updated `.dev/ROADMAP.md` when completed roadmap slices change status
- explicit active phase
- explicit next action

### 2. Design

Use the design skill to create implementation-ready decisions for the current
slice.

Focus on:

- module boundaries
- interfaces and contracts
- state files and schemas
- recovery and resumability
- validation strategy

Do not proceed to implementation if key design decisions are still implicit.

### 3. Develop

Use the development skill to implement only the active scoped slice.

Rules:

- keep changes incremental and verifiable
- preserve unrelated user changes
- keep the repo resumable after each meaningful update
- route back to design when implementation exposes a gap

### 4. Build And Deploy

Use the build and deploy skill when the roadmap requires packaging, install
flows, release artifacts, or deployability checks.

Capture:

- commands used
- artifacts produced
- failures and missing prerequisites

Do not hide broken prerequisites.

### 5. Test And Review

Use the testing and reviewing skill for both execution checks and code review.

Validation must include, when relevant:

- tests
- linters
- build checks
- smoke checks
- review of changed files for bugs, regressions, and missing edge cases

Findings come first. If no findings are discovered, say so explicitly and note
remaining risk.

### 6. Commit

Use the committing skill only after the active scope has passed validation or
the user explicitly asks for commit preparation.

Rules:

- stage only the intended files
- never include unrelated user changes silently
- keep one logical unit of work per commit when possible
- reflect commit status back into `.dev`
- if the committed slice completes a roadmap phase, update `.dev/ROADMAP.md`
  before finishing the workflow

Commit messages must follow this formatting rule:

- separate subject and body
- keep every line at 80 characters or fewer

## `.dev` State Management

When a workflow is active, keep these files aligned when they exist:

- `.dev/DASHBOARD.md`
- `.dev/ROADMAP.md`
- `.dev/TASKS.md`
- `.dev/workflow_state.json`
- `.dev/session.json`
- `.dev/logs/`

General rules:

- treat `.dev/workflow_state.json` as machine truth
- treat Markdown files as human-readable operating status
- do not mark work complete unless files and implementation agree
- do not leave `.dev/ROADMAP.md` behind when a roadmap phase is actually done
- preserve enough detail for safe resume after interruption

## Roadmap Alignment

Prefer roadmap execution in this order unless the user redirects the priority:

1. Phase 1. Core Foundation and Repository Bootstrap
2. Phase 2. `.dev` State Model and Template Generation
3. Phase 3. Agent CLI Adapter and Single-Run Execution
4. Phase 4. Supervisor Validation, Continuation Loop, and Resume
5. Phase 6. Installer, Commands, and Environment Diagnostics
6. Phase 5. Local Web UI and Progress Visibility
7. Phase 7. Hardening, Multi-Session, and Productization

Agents should optimize for getting the smallest useful, resumable slice working
first, then extend the product phase by phase.

## Resume Behavior

When resuming work after interruption:

1. read current `.dev` state
2. verify whether dashboard, tasks, and machine state agree
3. identify the earliest uncertain phase
4. resume from that phase rather than assuming later phases are valid

If evidence is missing, prefer re-validation over optimistic continuation.

## Default Agent Posture

When working in this repository, agents should:

- be explicit about the active phase
- use the mapped workflow skill for that phase
- let the supervisor govern transitions
- keep progress visible in `.dev`
- prefer deterministic checks before semantic judgment
- preserve resumability at every step

The goal is not just to write code. The goal is to operate a reliable,
recoverable workflow that can repeatedly move `dormammu` toward the product
described in `.dev/PROJECT.md` and `.dev/ROADMAP.md`.
