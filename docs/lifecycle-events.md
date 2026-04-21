# Lifecycle Events

`dormammu` now records runtime lifecycle activity through a shared typed event
contract in [backend/dormammu/lifecycle.py](../backend/dormammu/lifecycle.py).

## Contract

Every persisted event has the same envelope:

- `event_id`: unique event identifier
- `event_type`: explicit lifecycle type such as `run.requested` or `stage.completed`
- `run_id`: execution-scoped identifier shared by related events
- `session_id`: active session when available
- `timestamp`: ISO-8601 emission time
- `role`: runtime role when applicable
- `stage`: pipeline or loop stage when applicable
- `status`: compact outcome marker
- `payload`: typed event-specific payload
- `artifact_refs`: references to persisted artifacts instead of embedded blobs
- `metadata`: optional additive context

The envelope is intentionally small. Large reports and logs stay on disk and
are linked through `artifact_refs`.

Each `artifact_ref` uses the shared `ArtifactRef` contract from
`backend/dormammu/artifacts.py`, so persisted events can carry the artifact
kind, filesystem path, creation timestamp, and run/stage association metadata
without embedding the artifact body itself.

For loop, pipeline, and daemon executions, runtime hook events reuse the
parent execution `run_id` so hook activity can be reconstructed from the same
timeline as the surrounding lifecycle events. The hook controller only falls
back to a standalone hook-scoped `run_id` when no caller execution identifier
is available.

## Event Families

The initial schema covers these lifecycle types:

- run: `run.requested`, `run.started`, `run.finished`
- stage: `stage.queued`, `stage.started`, `stage.completed`, `stage.failed`, `stage.retried`
- evaluator: `evaluator.checkpoint_decision`
- coordination: `supervisor.handoff`
- hooks: `hook.execution_started`, `hook.execution_finished`
- permissions: `permission.gate`
- worktrees: `worktree.prepared`, `worktree.released`
- artifacts: `artifact.persisted`

Each family uses a dedicated typed payload dataclass rather than free-form
dictionaries. New event variants should extend the schema with new payload
types instead of overloading existing ones.

Negative stage verdicts are persisted as `stage.failed` events with the
verdict preserved in both `status` and the typed payload. For example, tester
`fail`, reviewer `needs_work`, evaluator `rework`, and blocked/failed terminal
states are all represented as failed stage events instead of being folded into
successful completion records.

## Persistence

Session and workflow machine state now keep a `lifecycle` block with:

- `updated_at`
- `latest_event`
- `history`

This block is the machine-truth event stream for the active execution. It is
designed so `.dev` operator files can be derived as projections from lifecycle
history plus the existing state snapshots.

The runtime also keeps an additive `execution` projection beside the raw
lifecycle history. It stores the latest explicit run, stage, checkpoint, and
artifact facts that were emitted or recorded during execution, so resume and
supervisor flows do not need to reconstruct those facts from ad hoc strings.

## Current Emitters

The active runtime integrations emit lifecycle events from:

- `LoopRunner` for loop admission, stage completion or failure, retries, supervisor handoff, worktree prep, and persisted artifacts
- `PipelineRunner` for pipeline run boundaries, one-shot stage transitions, retry loops, stage-result completion records, and evaluator checkpoint decisions
- `StateRepository` for projecting explicit run/stage/checkpoint facts into the session and workflow `execution` blocks
- `RuntimeHookController` for hook execution start and finish
- `DaemonRunner` for daemon prompt processing, prompt/result artifacts, and planner-to-developer handoff

`worktree.released` means the current execution stopped using the isolated
checkout. It does not imply that the underlying managed worktree was removed
from disk or forgotten from state.

The contract is additive. New emitters should preserve the existing event
shapes so stored histories remain backward-compatible.
