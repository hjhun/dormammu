---
schema_version: 1
name: architect
description: Use this skill before implementation when requirements affect architecture, interfaces, SW/HW constraints, performance, reliability, deployment, or cross-module behavior.
metadata: {"visibility": "profile_scoped", "role": "architect"}
---

# Architect

Design the structure that best satisfies the requirements and constraints.

## Inputs

- `REQUIREMENTS.md`
- `ROADMAP.md`
- Existing architecture, APIs, schemas, and deployment constraints
- SW/HW specifications when available

## Workflow

1. Identify impacted modules and ownership boundaries.
2. Analyze software and hardware constraints.
3. Define interfaces, schemas, state transitions, and error handling.
4. Consider memory, performance, concurrency, security, and recovery.
5. Compare viable approaches and choose one with clear trade-offs.
6. Define validation strategy for the chosen design.
7. Write or update `ARCHITECTURE.md` and `DECISIONS.md`.

## Output

Use this structure:

```markdown
# Architecture

## Context
## Constraints
## Proposed Structure
## Interfaces And Data Flow
## Error Handling And Recovery
## Performance And Memory Considerations
## Validation Strategy
```

