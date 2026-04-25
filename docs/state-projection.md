# State Projection Boundaries

작성일: 2026-04-25

## 목적

`StateRepository`는 파일 위치와 orchestration facade 역할을 유지하고,
구조화된 execution projection 계산은 `state/execution_projection.py`가
담당한다. `.dev` Markdown files are operator projections, while
`session.json`, `workflow_state.json`, and lifecycle/execution blocks are
machine-readable state.

## Write Path Classification

| Write path | Primary owner | Notes |
| --- | --- | --- |
| Bootstrap files | `StateRepository` | Creates session-local state and root index. |
| Prompt persistence | `StateRepository` | Writes prompt artifacts into the active session. |
| Agent run snapshots | `StateRepository` + `execution_projection` | Repository reads/writes files; projection service updates execution facts. |
| Stage results | `execution_projection` | Maintains latest stage result per stage key. |
| Run results | `execution_projection` | Maintains latest run, latest stage, and stage-result map. |
| Lifecycle events | `StateRepository` + `execution_projection` | Repository appends history; projection service derives execution snapshot. |
| Worktrees | `StateRepository` | Still owns managed worktree state updates. |
| Operator Markdown mirrors | `OperatorSync` | Root `.dev/*.md` is a derived active-session mirror. |

## Root Mirror Rule

The root `.dev` Markdown files are not independent truth. They are the
operator-facing mirror of the active session:

- root `.dev/DASHBOARD.md`, `.dev/PLAN.md`, `.dev/TASKS.md`, and
  `.dev/WORKFLOWS.md` are copied into the active session during
  `sync_operator_state()`
- session-local `session.json` and `workflow_state.json` remain the durable
  machine state for resumed execution
- lifecycle `history` records chronology; `execution` records the latest
  structured projection used by supervisor, recovery, daemon, and reporting

## Conflict Rule

When root Markdown and session-local Markdown differ, the active-session
operator sync step may import root Markdown edits into the session, then rebuild
task summaries. JSON execution facts are not inferred from Markdown projection
text when structured `RunResult`, `StageResult`, or lifecycle facts exist.

## Migration Rule

New state write behavior should be placed according to its responsibility:

- pure execution snapshot calculation belongs in `state/execution_projection.py`
- file reads, file writes, session selection, and root index updates remain in
  `StateRepository`
- Markdown checklist parsing and mirror synchronization remain in
  `OperatorSync`

This keeps `StateRepository` closer to a facade while avoiding a broad migration
of the session and root mirror machinery in one step.
