---
schema_version: 1
name: analyzer
description: Use this skill at the start of non-trivial Dormammu work to analyze the raw goal, repository context, constraints, risks, and unclear assumptions before requirements are rewritten.
metadata: {"visibility": "profile_scoped", "role": "analyzer"}
---

# Analyzer

Analyze the raw goal before requirements are refined.

## Inputs

- User goal or prompt
- Current repository context
- Existing `.dev/GOAL.md`, `.dev/DASHBOARD.md`, and `.dev/workflow_state.json`
  when present

## Workflow

1. Restate the goal in concrete terms.
2. Identify in-scope and out-of-scope areas.
3. Inspect relevant code, docs, config, and tests before making claims.
4. Identify constraints, dependencies, affected surfaces, and likely risks.
5. List ambiguities and assumptions that downstream roles must resolve.
6. Recommend whether the work should use the default loop or simple-task path.
7. Write or update `ANALYSIS.md` with findings.

## Output

Use this structure:

```markdown
# Analysis

## Goal
## In Scope
## Out Of Scope
## Current Context
## Risks
## Ambiguities
## Recommended Workflow
```

