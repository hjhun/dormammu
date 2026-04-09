# Develop And Test Authoring Workflow

Use this workflow after planning and design are complete and the active slice is ready for implementation.

## Covers

- Phase 3. Develop
- Phase 4. Test Authoring

## Skills To Use

- `skills/developing-agent/SKILL.md`
- `skills/test-authoring-agent/SKILL.md`

## Sequence

1. Use `skills/developing-agent/SKILL.md` for product-code changes in the active scope.
2. Use `skills/test-authoring-agent/SKILL.md` for unit and integration test code that matches the same scope.
3. Keep product-code ownership and test-code ownership separate even when both tracks move in parallel.
4. Route back to `workflows/planning-design.md` if implementation exposes a missing decision or incomplete interface.

## Outputs

- Incremental product-code changes
- Matching unit and integration test code by default
- Updated `.dev` state with implementation progress, authored coverage, and blockers
