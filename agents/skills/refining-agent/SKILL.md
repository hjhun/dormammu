---
name: refining-agent
description: Refines raw prompts into requirements-engineering-grade specifications before planning. Use whenever a user request, daemon prompt, scheduled goal, or feature idea must become explicit functional requirements, non-functional requirements, constraints, assumptions, risks, and verifiable acceptance criteria. Normalize clear prompts by default; ask clarifying questions only when planning would be unsafe.
---

# Refining Agent Skill

Use this skill as the first substantial stage. It turns the original prompt
into requirements that a planner, architect, developer, tester, reviewer, and
supervisor can execute without reinterpreting intent.

Related skills:

- Hand off to `planning-agent` after `.dev/REQUIREMENTS.md` is ready.
- Use `prd-agent` only when the request specifically needs a product PRD.

## Inputs

- The original user prompt, daemon prompt, or scheduled goal.
- Any stated constraints, priorities, non-goals, dependencies, or risks.
- Existing `.dev/` state, `.dev/PROJECT.md`, and `.dev/ROADMAP.md` when present.
- Repository context needed to avoid inventing scope.

## Workspace Persistence

Treat `.dev/...` paths as relative to the operational state directory shown in
the runtime path guidance. For new prompt runs, the runtime workspace should be
under:

```text
~/.dormammu/workspace/<home-relative-repo-path>/<date_with_time>_<prompt_name>/
```

Store the refined requirements, stage output, and state updates inside that
active prompt workspace. Do not write operational state into the source tree
unless the runtime path guidance explicitly says that is the active state root.

## Refinement Modes

### Normalize (default)

Use when the request is clear enough to plan safely.

1. Print `[[Refiner]]`.
2. Restate the goal in implementation-neutral language.
3. Extract functional requirements.
4. Extract non-functional requirements, including quality attributes.
5. Define scope boundaries and non-goals.
6. Convert success expectations into verifiable acceptance criteria.
7. Record assumptions, dependencies, risks, and open questions.
8. Write `.dev/REQUIREMENTS.md`.
9. Record `refinement.mode = normalize` and `blocked = false`.

### Clarify (only when blocked)

Use when the wrong interpretation would cause meaningful rework, or acceptance
criteria cannot be written without a human decision.

1. Print `[[Refiner]]`.
2. Ask at most 5 blocking questions, with short options where possible.
3. Write partial `.dev/REQUIREMENTS.md` with `## Open Questions`.
4. Record `refinement.mode = clarify` and `blocked = true`.
5. Stop before planning.

Do not ask questions for nice-to-have detail. If reasonable assumptions are
safe, normalize and document them.

## Requirements Document Format

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

- Write for downstream agents, not for casual reading.
- Separate functional and non-functional requirements.
- Make every acceptance criterion independently checkable.
- Avoid vague criteria such as "works correctly" or "is high quality."
- Do not expand scope beyond the prompt; record assumptions instead.
- Preserve user language intent even when the artifact is written in English.

## Done Criteria

The skill is complete when `.dev/REQUIREMENTS.md` lets the planner produce an
adaptive plan without asking follow-up questions about scope, constraints, or
acceptance criteria.
