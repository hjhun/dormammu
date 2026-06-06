# Codex Adapter

Codex should load `.agents/AGENTS.md` and the role skill matching the active
stage.

## Role Mapping

- analyzer: `.agents/roles/analyzer/SKILL.md`
- refiner: `.agents/roles/refiner/SKILL.md`
- planner: `.agents/roles/planner/SKILL.md`
- architect: `.agents/roles/architect/SKILL.md`
- developer: `.agents/roles/developer/SKILL.md`
- reviewer: `.agents/roles/reviewer/SKILL.md`
- committer: `.agents/roles/committer/SKILL.md`
- coordinator: `.agents/roles/coordinator/SKILL.md`
- supervisor: `.agents/roles/supervisor/SKILL.md`

Use `.agents/workflows/simple-task.md` for small tasks and
`.agents/workflows/autonomous-development-loop.md` for normal development.

