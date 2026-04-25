---
name: designing-agent
description: Performs the architect stage for Dormammu work. Use when the planner decides architecture is needed, when OOAD/design documents are requested, or when functional and non-functional requirements must be translated into modules, interfaces, contracts, state models, quality-attribute tradeoffs, and implementation-ready design.
---

# Designing / Architect Agent Skill

Use this skill after planning when design decisions are needed before safe
development. The runtime role may be named `designer` for compatibility, but
the responsibility is the architect role described by the workflow.

Related skills:

- Consume `.dev/REQUIREMENTS.md`, `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and
  `.dev/TASKS.md`.
- Hand implementation to `developing-agent`.
- Hand validation expectations to `test-authoring-agent`, `tester`, and
  `reviewer`.

## Inputs

- Original prompt and refined requirements.
- Planner output and active task list.
- Existing code, module boundaries, state files, and tests.
- Any ISO-style quality attributes implied by the requirements.

## Workspace Persistence

Treat `.dev/...` paths as relative to the active prompt workspace from the
runtime path guidance:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

Write architecture notes, design documents, and status updates inside that
workspace. Stage reports belong in `.dev/logs/`.

## Workflow

1. Print `[[Designer]]` or `[[Architect]]` according to the runtime contract.
2. Read the original prompt, refined requirements, plan, tasks, and workflow.
3. Identify functional requirements and their owning modules/classes.
4. Identify non-functional requirements and quality attributes.
5. Produce an OOAD-oriented design:
   - responsibilities and collaborations
   - interfaces and data contracts
   - state transitions and persistence rules
   - error handling and recovery behavior
   - test seams and observability points
6. Evaluate quality attributes such as reliability, maintainability,
   performance, security, compatibility, usability, portability, and
   operability.
7. Define file ownership and cross-track contracts when work is parallel.
8. Record assumptions, tradeoffs, rejected alternatives, and design risks.
9. Update `.dev/DASHBOARD.md` and `.dev/PLAN.md` only for real progress.

## Design Document Format

```markdown
# Architecture Design

## Context
<original and refined requirement summary>

## Functional Design
- <module/class/component responsibility>

## Non-Functional Design
- <quality attribute and design response>

## OOAD Model
- <objects, responsibilities, collaborations, and boundaries>

## Interfaces And Contracts
- <API, function, file, schema, CLI, or state contract>

## State And Recovery
- <state files, resumability, idempotency, failure handling>

## Validation Strategy
- <unit, integration, smoke, and optional system test expectations>

## File Ownership
- <files or modules owned by each track or agent>

## Risks And Tradeoffs
- <risk, mitigation, and explicit tradeoff>
```

## Rules

- Design only enough to unblock implementation safely.
- Do not invent architecture unrelated to the active requirements.
- Treat quality attributes as design constraints, not review afterthoughts.
- Make contracts specific enough for TDD and review.
- If requirements are incomplete, route back to `refining-agent`.
- If the plan is unsafe or missing a needed stage, route back to
  `planning-agent`.

## Done Criteria

The skill is complete when developers can implement without inventing module
contracts, testers can derive user scenarios, and reviewers can compare code
against explicit design decisions.
