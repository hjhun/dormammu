# Python To TypeScript Porting Status

## Goal

Move Dormammu from a Python runtime to a TypeScript runtime while preserving the
current CLI, web, Telegram, daemon, goals, `.agents`, and `.dev` behavior.

## Current Slice

The first TypeScript runtime package lives under `runtime/`.

Ported modules:

- `backend/dormammu/agent/prompt_identity.py`
  -> `runtime/src/agent/promptIdentity.ts`
- `backend/dormammu/agent/command_builder.py`
  -> `runtime/src/agent/commandBuilder.ts`
- `backend/dormammu/workflow_policy.py`
  -> `runtime/src/workflowPolicy.ts`
- pure verdict/status helpers from `backend/dormammu/results.py`
  -> `runtime/src/results.ts`
- `backend/dormammu/state/persistence.py`
  -> `runtime/src/state/persistence.ts`
- pure prompt, guidance, roadmap, dashboard, and plan helpers from
  `backend/dormammu/state/models.py`
  -> `runtime/src/state/models.ts`
- `backend/dormammu/state/execution_projection.py`
  -> `runtime/src/state/executionProjection.ts`
- `backend/dormammu/state/session_manager.py`
  -> `runtime/src/state/sessionManager.ts`
- `backend/dormammu/state/tasks.py`
  -> `runtime/src/state/tasks.ts`
- `backend/dormammu/state/operator_sync.py`
  -> `runtime/src/state/operatorSync.ts`
- session/workflow read-write, paired state synchronization, hook event, and
  lifecycle event helpers from `backend/dormammu/state/repository.py`
  -> `runtime/src/state/repository.ts`
- root/session bootstrap orchestration slice from
  `backend/dormammu/state/repository.py`
  -> `runtime/src/state/repository.ts`
- prompt-fingerprint bootstrap regeneration and guidance-aware state defaults
  from `backend/dormammu/state/repository.py`
  -> `runtime/src/state/repository.ts`
- filesystem guidance discovery and session restore orchestration from
  `backend/dormammu/state/repository.py`
  -> `runtime/src/state/repository.ts`
- start-session lifecycle orchestration from
  `backend/dormammu/state/repository.py`
  -> `runtime/src/state/repository.ts`
- supervisor report artifact writing, continuation prompt artifact writing, and
  input prompt persistence from `backend/dormammu/state/repository.py`
  -> `runtime/src/state/repository.ts`

Validation:

- `cd runtime && npm test`
- existing Python regression suite remains in place while parity is built.

## Migration Rules

- Port behavior in vertical slices, not by blind file translation.
- Add TypeScript tests before replacing Python call sites.
- Keep Python tests running until the matching TypeScript surface has equivalent
  unit, smoke, and e2e coverage.
- Remove Python modules only after TypeScript call sites own the behavior.
- Keep `.agents` and `.dev` file formats stable during the migration.

## Porting Order

1. Pure deterministic helpers
   - prompt identity
   - command planning
   - result verdict parsing
   - workflow policy
   - path and workspace projections

2. State model and repository
   - `.dev` state schemas (in progress)
   - session index (ported)
   - execution projection (ported)
   - task parsing and operator sync (ported)
   - repository read/write synchronization (in progress)
   - task and dashboard projections
   - JSON and Markdown persistence

3. Agent runtime
   - CLI adapter
   - help parser
   - command execution
   - continuation prompts
   - result artifact collection

4. Supervisor and pipeline
   - stage result model
   - refiner/planner prelude
   - developer/reviewer/committer loops
   - retry and re-entry limits

5. Daemon and goals
   - prompt queue
   - file watchers
   - goals scheduler
   - lifecycle and recovery

6. Web and Telegram backend
   - replace FastAPI with a Node HTTP/WebSocket server
   - keep the existing React app
   - port Telegram command/session/tail services

7. Packaging and installers
   - replace Python package entrypoint with a Node CLI
   - update `setup.sh` and `install.sh`
   - keep `.agents` packaged with the runtime

8. Final removal
   - delete Python runtime modules
   - delete Python tests after equivalent TypeScript coverage exists
   - remove Python package metadata when no compatibility shim remains

## Completion Criteria

- `npm test` passes for the TypeScript runtime.
- unit, smoke, and e2e TypeScript tests cover CLI, daemon, web, Telegram, and
  goals flows.
- no Python runtime entrypoint is required for normal operation.
- no Python files remain except historical migration notes or explicitly
  retained compatibility shims.

## Next Slice

Port the remaining state repository orchestration surface:

- runtime skill resolution and worktree state mutation helpers still owned by
  `backend/dormammu/state/repository.py`
- task, dashboard, and workflow-state projections that still depend on Python
  repository methods

The next slice should introduce TypeScript tests around runtime skill
resolution summaries, managed worktree state mutations, and the root index
projections they affect before any Python call site is removed.
