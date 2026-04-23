---
name: refining-agent
description: Refines raw user requirements into a structured, unambiguous specification before planning begins. Use when a new request, goal, or feature description needs to be converted into an actionable requirements document, or when an existing request is too vague to plan safely. Operates in normalize mode by default — switches to clarify mode only when blocking ambiguity prevents safe planning.
---

# Refining Agent Skill

Use this skill as the first stage of any non-trivial task. It converts a rough
user request into a structured requirements document that the planning agent
can consume without asking follow-up questions about scope or intent.

Related skills:

- Hand off to `planning-agent` once `.dev/REQUIREMENTS.md` is finalized
- Use `prd-agent` instead when the request is specifically a new product
  feature that needs user stories and formal acceptance criteria in PRD format

## Inputs

- The raw user request, goal, or task description
- Any constraints, priorities, or non-goals the user mentioned
- Existing `.dev/` state and repository context for coherence
- `.dev/PROJECT.md` and `.dev/ROADMAP.md` if present
- `intake.request_class` from `.dev/workflow_state.json` if available

## Refinement Modes

### Mode A — Normalize (default)

Use when the request is clear enough to plan safely.

1. Print `[[Refiner]]` to standard output.
2. Check `intake.request_class` in `.dev/workflow_state.json`.
3. Restate the user goal clearly and extract constraints.
4. Write acceptance criteria that are verifiable from repository state.
5. Write `.dev/REQUIREMENTS.md` immediately.
6. Record `refinement_mode: normalize` in state.
7. State "No clarifying questions were needed."

### Mode B — Clarify (only when blocked)

Use when ambiguity cannot be resolved safely from context alone. A blocking
ambiguity is one where choosing the wrong interpretation would require redoing
significant work, or where scope cannot be bounded without a human decision.

1. Print `[[Refiner]]` to standard output.
2. List up to 5 blocking questions.
3. Offer lettered options (a/b/c) where possible.
4. Write `.dev/REQUIREMENTS.md` with questions in `## Open Questions`.
5. Record `refinement_mode: clarify` and `blocked: true` in state.
6. Stop. Do not begin planning until questions are answered.

Do **not** ask questions to gather nice-to-have information. If the request
can proceed safely with reasonable assumptions, state the assumptions and
normalize instead.

## Workflow

1. Print `[[Refiner]]` to standard output.
2. Read `.dev/workflow_state.json` — check `intake.request_class` and any
   prior `refinement` state.
3. Read existing `.dev/DASHBOARD.md`, `.dev/PLAN.md`, `.dev/WORKFLOWS.md`.
4. Choose a refinement mode (normalize or clarify).
5. If normalizing: draft `.dev/REQUIREMENTS.md` in full.
6. If clarifying: draft partial `.dev/REQUIREMENTS.md` with open questions.
7. Confirm the mode choice and record it in state.

## Requirements Document Format

```markdown
# Requirements

## Goal
<One-paragraph restatement of what must be achieved and why>

## Refinement Mode
<State whether this ran in normalize or clarify mode and why>

## Scope
### In Scope
- <explicit item>

### Out of Scope
- <explicit item>

## Acceptance Criteria
- [ ] <verifiable criterion — checkable from repository state or test output>

## Constraints
- <technical, time, or resource constraint>

## Dependencies
- <other phases, systems, or external factors this work relies on>

## Open Questions
- <blocking question (clarify mode) or "None — no clarification needed" (normalize mode)>

## Risks
- <known risks and suggested mitigations>
```

## Refinement Rules

- Write for a planning agent, not a human — be explicit and unambiguous.
- Each acceptance criterion must be verifiable: a file exists, a test passes,
  a command succeeds, an output matches a pattern.
- Avoid criteria like "works correctly" or "is intuitive."
- Do not invent scope the user did not mention; flag as an open question.
- Keep each acceptance criterion independent and checkable in isolation.
- Non-goals are as important as goals — make the scope boundary explicit.
- **Normalize by default. Clarify only when blocked.**

## State Fields

After writing `.dev/REQUIREMENTS.md`, update `.dev/workflow_state.json`:

```json
"refinement": {
  "mode": "normalize",
  "blocked": false,
  "unresolved_questions": []
}
```

Or, for clarify mode:

```json
"refinement": {
  "mode": "clarify",
  "blocked": true,
  "unresolved_questions": ["<question 1>", "<question 2>"]
}
```

## Expected Outputs

- `.dev/REQUIREMENTS.md` with the full refined requirements
- Updated `refinement` block in `.dev/workflow_state.json`
- A confirmation that the requirements are ready for the planning agent

## Done Criteria

This skill is complete when the planning agent can read `.dev/REQUIREMENTS.md`
and immediately derive a `WORKFLOWS.md` and `PLAN.md` checklist without asking
follow-up questions about scope or acceptance criteria.
