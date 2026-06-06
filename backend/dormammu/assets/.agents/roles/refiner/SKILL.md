---
schema_version: 1
name: refiner
description: Use this skill after analyzer output exists to rewrite the goal into clear functional requirements, non-functional requirements, acceptance criteria, and test cases.
metadata: {"visibility": "profile_scoped", "role": "refiner"}
---

# Refiner

Turn analysis into implementation-ready requirements.

## Inputs

- Raw goal
- `ANALYSIS.md`
- Existing requirements or prior review feedback

## Workflow

1. Preserve the user's intent.
2. Rewrite functional requirements as explicit behavior.
3. Rewrite non-functional requirements for performance, memory, reliability,
   security, compatibility, and maintainability where relevant.
4. Define acceptance criteria that can be checked.
5. Define required unit, smoke, and e2e test cases.
6. Mark assumptions and open questions separately from confirmed requirements.
7. Write or update `REQUIREMENTS.md`.
8. Hand off to the planner role when requirements are complete.

## Output

Use this structure:

```markdown
# Requirements

## Functional Requirements
## Non-Functional Requirements
## Acceptance Criteria
## Test Cases
## Assumptions
## Open Questions
```
