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
   - session index (next)
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

Port the state repository execution projection and session manager:

- `backend/dormammu/state/execution_projection.py`
- `backend/dormammu/state/session_manager.py`
- selected pure helpers from `backend/dormammu/state/repository.py`

The next slice should introduce TypeScript tests for session id normalization,
session listing, latest run projection, and stage result projection before any
Python call site is removed.
