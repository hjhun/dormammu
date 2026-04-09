# Cleanup And Commit Workflow

Use this workflow when the active scope is validated and the remaining work is to remove no-longer-needed files, confirm final scope, and prepare a commit.

## Covers

- Cleanup of unnecessary files in the active scope
- Phase 7. Commit

## Skills To Use

- `skills/committing-agent/SKILL.md`

## Sequence

1. Review the working tree and remove files that are unnecessary for the validated scope.
2. Confirm `.dev` reflects the real completion state before staging.
3. Use `skills/committing-agent/SKILL.md` to stage only the intended files and create the commit.
4. If validation evidence is missing, route back to `workflows/build-deploy-test-review.md` instead of forcing the commit.

## Outputs

- Cleaned final diff for the active scope
- Intentional staging decisions
- A scoped commit or an explicit blocker to committing
