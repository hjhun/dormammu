# Build Deploy And Test Review Workflow

Use this workflow after the active implementation slice is complete and the work needs packaging or executed validation.

## Covers

- Phase 5. Build and Deploy
- Phase 6. Test and Review

## Skills To Use

- `skills/building-and-deploying/SKILL.md`
- `skills/testing-and-reviewing/SKILL.md`

## Sequence

1. Use `skills/building-and-deploying/SKILL.md` when the scope requires installers, archives, release artifacts, or deployability checks.
2. Use `skills/testing-and-reviewing/SKILL.md` after development is complete to run executed validation and review the changed files.
3. Run unit and integration tests by default, then add build checks, linters, smoke checks, or explicit system tests when the scope requires them.
4. Route back to `workflows/develop-test-authoring.md` when build failures or review findings expose implementation gaps.

## Outputs

- Build or packaging evidence when relevant
- Executed validation results
- Findings, residual risks, and updated `.dev` status
