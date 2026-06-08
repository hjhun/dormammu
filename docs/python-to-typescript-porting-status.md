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
- `backend/dormammu/agent/models.py` agent run started/result artifact payload
  helpers
  -> `runtime/src/agent/runArtifacts.ts`
- `backend/dormammu/agent/cli_adapter.py` prompt persistence, subprocess
  execution, stdout/stderr mirroring, timeout handling, and run metadata
  artifact writing
  -> `runtime/src/agent/cliAdapter.ts`
- `backend/dormammu/agent/help_parser.py` and
  `backend/dormammu/agent/presets.py` deterministic CLI capability parsing,
  known CLI preset matching, and auto-approve candidate detection
  -> `runtime/src/agent/helpParser.ts`, `runtime/src/agent/presets.ts`
- `backend/dormammu/agent/cli_adapter.py` default known-CLI extra argument
  injection and Gemini duplicate approval/include argument sanitization
  -> `runtime/src/agent/presetArgs.ts`
- `backend/dormammu/agent/cli_adapter.py` help-command capability discovery,
  prefixed help discovery for known CLI presets, and help output parsing
  orchestration
  -> `runtime/src/agent/cliAdapter.ts`
- `backend/dormammu/agent/cli_adapter.py` fallback CLI candidate selection,
  CLI invocation override merging, token-exhaustion detection, and nonzero-exit
  fallback result enrichment
  -> `runtime/src/agent/cliAdapter.ts`
- `backend/dormammu/agent/cli_adapter.py` shutdown interruption handling for
  active agent subprocesses and operator-visible shutdown output
  -> `runtime/src/agent/cliAdapter.ts`
- `backend/dormammu/agent/permissions.py` permission decisions, named policy
  evaluation, filesystem specificity evaluation, policy override merging, and
  permission override parsing
  -> `runtime/src/agent/permissions.ts`
- `backend/dormammu/agent/profiles.py`,
  `backend/dormammu/agent/role_config.py`, and
  `backend/dormammu/agent/role_taxonomy.py` built-in role profile catalog,
  role agent config parsing/merging, and effective profile normalization
  -> `runtime/src/agent/profiles.ts`
- `backend/dormammu/agent/manifests.py` and
  `backend/dormammu/agent/manifest_loader.py` manifest schema parsing,
  manifest candidate enumeration, selected-profile tolerant discovery,
  scope precedence, shadowing, same-scope duplicate rejection, and loaded
  runtime definition conversion
  -> `runtime/src/agent/manifests.ts`
- config-backed manifest profile resolution from
  `backend/dormammu/config_resolvers.py`, including requested manifest profile
  name derivation, selected manifest loading, normalized role profile snapshots,
  and runtime manifest metadata projection
  -> `runtime/src/agent/profiles.ts`, `runtime/src/agent/manifests.ts`
- TypeScript configured runner profile wiring, including profile CLI override
  selection before global active CLI fallback and entrypoint role/profile based
  runtime skill summary projection
  -> `runtime/src/agent/configuredRunner.ts`,
  `runtime/src/agent/runnerEntrypoint.ts`
- agent runtime config fields from `backend/dormammu/config.py` including
  `active_agent_cli`, `fallback_agent_clis`, `cli_overrides`,
  `token_exhaustion_patterns`, `process_timeout_seconds`, and
  `fallback_on_nonzero_exit`
  -> `runtime/src/agent/configuredRunner.ts`
- JSON payload based TypeScript agent runner entrypoint for configured
  single-agent execution
  -> `runtime/src/agent/runnerEntrypoint.ts`
- Node CLI wrapper for the configured TypeScript runner entrypoint
  -> `runtime/src/agent/runnerCli.ts`
- Python opt-in compatibility bridge for delegating `CliAdapter.run_once` to
  `dormammu-agent-runner`
  -> `backend/dormammu/agent/cli_adapter.py`
- bridge safety fallback that keeps Python `CliAdapter` semantics for calls
  requiring `on_started` current-run timing or `stop_event` shutdown handling
  -> `backend/dormammu/agent/cli_adapter.py`
- structured `dormammu-agent-runner` event stream for started callbacks, live
  output forwarding, and stop-event shutdown propagation through the Python
  bridge
  -> `runtime/src/agent/runnerCli.ts`, `backend/dormammu/agent/cli_adapter.py`
- setup/install wiring for building `runtime/` and exposing
  `dormammu-agent-runner` as an installed launcher
  -> `setup.sh`, `install.sh`
- installed-environment smoke coverage for the opt-in TypeScript runner bridge
  through the real `dormammu-agent-runner` launcher
  -> `tests/test_install_script.py`
- setup-time default config wiring that records the installed
  `dormammu-agent-runner` launcher as `typescript_agent_runner_cli` when the
  operator has not already configured a runner
  -> `setup.sh`
- `run` / `LoopRunner` contract coverage proving configured TypeScript runner
  delegation preserves live output streaming, current-run clearing, latest-run
  projection, and required-path supervision
  -> `tests/test_loop_runner.py`
- daemon `PipelineRunner` stage contract coverage proving one-shot role stages
  consume the configured TypeScript runner bridge, write stage reports, and
  mirror event-streamed output to progress logs
  -> `tests/test_pipeline_runner.py`
- goals automation role-agent contract coverage proving `GoalsScheduler`
  consumes the configured TypeScript runner bridge and mirrors event-streamed
  output into scheduler progress logs
  -> `tests/test_goals_scheduler.py`
- typed `SKILL.md` document parsing, metadata validation, source scope
  normalization, source precedence helpers, candidate enumeration,
  discovery/shadowing resolution, profile permission filtering, preload
  classification, missing preload reporting, runtime skill resolution summary,
  prompt-line projection, and log-line projection from
  `backend/dormammu/skills.py`
  -> `runtime/src/agent/skills.ts`
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
- managed worktree state mutation and runtime skill resolution state recording
  from `backend/dormammu/state/repository.py`
  -> `runtime/src/state/repository.ts`
- search-root/profile-backed runtime skill resolution recording from
  `backend/dormammu/state/repository.py`
  -> `runtime/src/state/repository.ts`
- operator task synchronization, agent run projection, and run/stage result
  projection from `backend/dormammu/state/repository.py`
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

Port the remaining runtime orchestration surface:

- runtime skill resolution and manifest-backed profile discovery/loading can
  now be projected from TypeScript search roots, selected manifest-backed
  profiles can be normalized into TypeScript runtime role profile snapshots,
  and the TypeScript runner entrypoint can resolve role/profile-backed CLI and
  runtime skill payloads when given the required search roots
- Python runtime call sites still own daemon, supervisor, and pipeline
  execution while TypeScript parity surfaces are assembled

The next slice should use the accumulated contract coverage to start replacing
remaining Python runtime fallback internals with TypeScript-owned
implementations, beginning with passing role/profile search-root context from
the Python bridge into the TypeScript runner payload.
