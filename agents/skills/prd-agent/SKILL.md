---
name: prd-agent
description: Generates a structured Product Requirements Document (PRD) for a new feature or scope. Use when the user asks to plan a feature, create requirements, write a PRD, or convert a rough idea into actionable user stories.
---

# PRD Agent Skill

Use this skill before planning or development begins on a new feature or significant scope. It converts a rough goal into a structured PRD with user stories that are small enough to implement in a single agent session.

Related skills:

- Hand off to `planning-agent` once the PRD is finalized
- Use `designing-agent` to convert PRD decisions into implementation interfaces

## Inputs

- The user goal or feature description
- Any constraints, non-goals, or priorities the user mentions
- Existing `.dev/` state and repository context for coherence

## Workflow

1. Print `[[PRD]]` to standard output.
2. Ask 3–5 clarifying questions to understand scope, acceptance criteria, and non-goals. Offer lettered options (a/b/c) where possible to keep answers quick.
3. Draft a PRD in `tasks/prd-<feature-name>.md` with these sections:
   - **Overview** — one-paragraph summary of the feature and its purpose
   - **Goals** — 3–5 measurable outcomes this feature achieves
   - **User Stories** — ordered list of implementable stories (see format below)
   - **Non-Goals** — explicit scope exclusions
   - **Technical Considerations** — key constraints, dependencies, or design decisions
   - **Success Metrics** — how to verify the feature is working correctly
   - **Open Questions** — unresolved decisions that need answers before or during development
4. Validate each user story against the sizing rules below.
5. Save the final PRD to `tasks/prd-<feature-name>.md`.

## User Story Format

```
### US-NNN: <Story Title>

**As a** <user type>
**I want** <action or capability>
**So that** <outcome or benefit>

**Acceptance Criteria:**
- [ ] <verifiable criterion 1>
- [ ] <verifiable criterion 2>
- [ ] Typecheck and tests pass
- [ ] (for UI stories) Verified in browser

**Priority:** high | medium | low
**Dependencies:** US-NNN (if any)
**Notes:** ""
```

## Story Sizing Rules

Each story must be implementable in a single agent context window (one dormammu session):

- Schema or data model changes → one story
- Backend logic or API endpoint → one story per endpoint
- UI component or page → one story per view
- Test coverage for a story → include in same story, not separate
- If a story feels too large, split it at natural interface boundaries (schema → service → UI)

Dependency order must flow: schema → backend → UI → integration. Never let a later story depend on an earlier story that has not been listed above it.

## PRD Writing Rules

- Write for a coding agent, not a human developer — be explicit and unambiguous
- Each acceptance criterion must be verifiable from the repository state (file exists, test passes, etc.)
- Avoid acceptance criteria like "works correctly" or "is intuitive" — these cannot be verified automatically
- Keep each story completable without reading beyond its own section
- Non-goals are as important as goals — make the scope boundary explicit

## Expected Outputs

- `tasks/prd-<feature-name>.md` with full PRD content
- User stories ready to be converted into `.dev/PLAN.md` items by `planning-agent`

## Done Criteria

This skill is complete when a planning agent can read the PRD and immediately derive a PLAN.md checklist without asking follow-up questions about scope or acceptance criteria.
