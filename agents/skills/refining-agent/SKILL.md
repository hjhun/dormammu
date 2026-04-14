---
name: refining-agent
description: Refines raw user requirements into a structured, unambiguous specification before planning begins. Use when a new request, goal, or feature description needs clarification before it can be turned into an actionable plan.
---

# Refining Agent Skill

Use this skill as the first stage of any non-trivial task. It converts a rough
user request into a structured requirements document that the planning agent can
consume without asking follow-up questions about scope or intent.

Related skills:

- Hand off to `planning-agent` once `.dev/REQUIREMENTS.md` is finalized
- Use `prd-agent` instead when the request is specifically a new product feature
  that needs user stories and formal acceptance criteria in PRD format

## Inputs

- The raw user request, goal, or task description
- Any constraints, priorities, or non-goals the user mentioned
- Existing `.dev/` state and repository context for coherence
- `.dev/PROJECT.md` if present

## Workflow

1. Read the raw request and any existing `.dev/` context.
2. Identify ambiguities, missing constraints, and open decisions that would block
   planning or design.
3. Ask 3–6 targeted clarifying questions. Offer lettered options (a/b/c) where
   possible to keep answers quick. Focus on:
   - Scope boundaries (what is in and what is out)
   - Acceptance criteria (how to verify the work is done)
   - Constraints (performance, compatibility, deadline, tooling)
   - Dependencies (other systems, phases, or people this work relies on)
   - Risk factors (irreversibility, breakage, data migration)
4. Incorporate the answers and draft `.dev/REQUIREMENTS.md`.
5. Confirm the refined requirements with the operator before handing off.

## Requirements Document Format

Write `.dev/REQUIREMENTS.md` with these sections:

```markdown
# Requirements

## Goal
<One-paragraph restatement of what must be achieved and why>

## Scope
### In Scope
- <explicit item>

### Out of Scope
- <explicit item>

## Acceptance Criteria
- [ ] <verifiable criterion — must be checkable from repository state or test output>

## Constraints
- <technical, time, or resource constraint>

## Dependencies
- <other phases, systems, or external factors this work relies on>

## Open Questions
- <unresolved decisions that planning or design must address>

## Risks
- <known risks and suggested mitigations>
```

## Refinement Rules

- Write for a planning agent, not a human — be explicit and unambiguous.
- Each acceptance criterion must be verifiable: a file exists, a test passes, a
  command succeeds, an output matches a pattern.
- Avoid criteria like "works correctly" or "is intuitive" — these cannot be
  verified automatically.
- Do not invent scope that the user did not mention; flag it as an open question
  instead.
- Keep each acceptance criterion independent and checkable in isolation.
- Non-goals are as important as goals — make the scope boundary explicit.
- If the user's request is clear enough to plan without questions, skip straight
  to drafting `.dev/REQUIREMENTS.md` and note that no clarification was needed.

## Expected Outputs

- `.dev/REQUIREMENTS.md` with the full refined requirements
- A confirmation that the requirements are ready for the planning agent

## Done Criteria

This skill is complete when the planning agent can read `.dev/REQUIREMENTS.md`
and immediately derive a `WORKFLOWS.md` and `PLAN.md` checklist without asking
follow-up questions about scope or acceptance criteria.
