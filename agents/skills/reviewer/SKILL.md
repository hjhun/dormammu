---
name: reviewer
description: Perform responsible code review for Dormammu changes after tester validation or when `.dev/WORKFLOWS.md` includes review. Use for correctness, regressions, edge cases, memory and performance risks, maintainability, security, requirement coverage, architecture adherence, and test evidence. Issues route back to the responsible stage.
---

# Reviewer Skill

Use this skill after implementation and executable validation, or when
`.dev/WORKFLOWS.md` explicitly asks for review. If the planner skipped review,
do not run it unless the user redirects or a later stage finds review risk.

## Workflow

1. Print `[[Reviewer]]`.
2. Read requirements, `.dev/WORKFLOWS.md`, plan, design/architect document,
   developer notes, tester report, and git diff.
3. Review for correctness against the original and refined requirements.
4. Review adherence to architecture and OOAD contracts.
5. Analyze memory, performance, security, compatibility, and maintainability
   risks in touched paths.
6. Identify missing edge cases, regression risk, and test gaps.
7. Put findings first with file/line references where possible.
8. If issues are actionable, route them to architect, developer, tester, or
   requester according to the cause.
9. End with exactly one verdict line:
   - `VERDICT: APPROVED`
   - `VERDICT: NEEDS_WORK`

## Rules

- Review as if responsible for the code after merge.
- Prioritize bugs and risks over style.
- Do not approve when validation evidence is missing for critical behavior.
- If no issues are found, say that clearly and note residual risk.

## Done Criteria

The reviewer stage is complete when findings are actionable and the verdict
lets the supervisor either proceed or route back to developer.
