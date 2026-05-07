---
name: refiner
description: Refine a raw Dormammu user request, daemon prompt, or scheduled goal into durable requirements before planning. Use when scope, acceptance criteria, constraints, dependencies, risks, or non-functional requirements need to be captured in `.dev/REQUIREMENTS.md` so the planner can decide the workflow without reinterpreting intent.
---

# Refiner

## Purpose

Turn the original request into requirements that planner, architect, developer,
tester, reviewer, committer, and coding-workflow stages can execute. Preserve
the user's intent, separate facts from assumptions, and ask only for decisions
that block safe planning.

The legacy packaged skill `refining-agent` is an alias for this role.

## Inputs

Read before refining:

- the original user request, daemon prompt, or scheduled goal
- `.dev/DASHBOARD.md`, `.dev/PLAN.md`, and `.dev/WORKFLOWS.md` when present
- `.dev/workflow_state.json` when present
- `.dev/PROJECT.md` and `.dev/ROADMAP.md` when relevant
- repository context needed to avoid inventing scope

Treat `.dev/...` paths as relative to the active prompt workspace from runtime
path guidance. For new prompt runs, that workspace normally resolves under:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

## Outputs

Write:

- `.dev/REQUIREMENTS.md`: refined requirements and acceptance criteria
- `.dev/DASHBOARD.md`: refiner status and next action
- `.dev/workflow_state.json`: refinement mode and blocker state when available
- `.dev/logs/<date>_refiner_<stem>.md` or the runtime-specified stage log

Do not write `.dev/WORKFLOWS.md`; the planner owns workflow selection.

## Refinement Modes

### Normalize

Use normalize mode by default when planning can proceed safely.

1. Restate the goal in implementation-neutral language.
2. Extract functional requirements.
3. Extract non-functional requirements and quality attributes.
4. Define in-scope and out-of-scope boundaries.
5. Convert expectations into verifiable acceptance criteria.
6. Record constraints, dependencies, assumptions, risks, and open questions.
7. Write `.dev/REQUIREMENTS.md`.
8. Record `refinement.mode = normalize` and `blocked = false`.

### Clarify

Use clarify mode only when a missing answer would materially change the plan or
cause meaningful rework.

1. Ask at most five blocking questions.
2. Offer short options when that reduces back-and-forth.
3. Write partial `.dev/REQUIREMENTS.md` with the blockers in `## Open Questions`.
4. Record `refinement.mode = clarify` and `blocked = true`.
5. Stop before planning.

## REQUIREMENTS.md Format

```markdown
# Requirements

## Original Prompt
<brief source summary>

## Goal
<one-paragraph refined goal>

## Refinement Mode
<normalize or clarify, with reason>

## Functional Requirements
- <system behavior the implementation must provide>

## Non-Functional Requirements
- <quality attribute, constraint, operability, compatibility, security, or performance requirement>

## Scope
### In Scope
- <included work>

### Out of Scope
- <excluded work>

## Acceptance Criteria
- [ ] <verifiable repository, command, artifact, or behavior criterion>

## Constraints
- <technical, workflow, environment, or policy constraint>

## Dependencies
- <dependency or "None identified">

## Assumptions
- <safe assumption or "None">

## Open Questions
- <blocking question or "None - no clarification needed">

## Risks
- <risk and mitigation>
```

## Rules

- Normalize clear prompts instead of asking for nice-to-have details.
- Do not expand scope beyond the prompt; record assumptions instead.
- Preserve user language intent even when writing the artifact in English.
- Make every acceptance criterion independently checkable.
- Keep requirements implementation-neutral unless the user explicitly specified
  a file, API, framework, or tool.
- Route to planner only after `.dev/REQUIREMENTS.md` is usable.

## Done Criteria

This skill is complete when `.dev/REQUIREMENTS.md` gives the planner enough
context to decide `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and `.dev/TASKS.md`
without asking follow-up questions about scope or acceptance criteria.
