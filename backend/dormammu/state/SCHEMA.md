# `.dev` State File Schemas

This document describes the machine-readable state files written and maintained
by `StateRepository` under the operational `.dev/` root.

In the workspace-shadow runtime model, the operational `.dev/` root is not the
repository-local `./.dev` directory by default. It is the workspace project
shadow under `~/.dormammu/workspace/<mapped-project>/.dev`, with temporary
artifacts stored alongside it in `~/.dormammu/workspace/<mapped-project>/.tmp`.
When this document refers to `.dev/...`, it means the operational state root
resolved by the runtime config.

---

## session.json

**Role**: Session-scoped machine truth. Tracks the active session, run status,
task sync state, and latest run metadata.

**Written by**: `StateRepository.ensure_bootstrap_state`, `record_latest_run`,
`record_current_run`, `write_session_state`, `persist_input_prompt`.

**Schema version constant**: `STATE_SCHEMA_VERSION` in `state/models.py`.

### Root-level index (`.dev/session.json`)

When a session is active, `.dev/session.json` acts as an **index** pointing to
the active session subdirectory. It is never the canonical run state itself.

| Field | Type | Description |
|-------|------|-------------|
| `active_session_id` | string | ID of the currently active session |
| `default_session_id` | string | Same as `active_session_id` at selection time |
| `selected_at` | ISO-8601 string | When this session was last activated |
| `updated_at` | ISO-8601 string | Last mutation timestamp |
| `state_schema_version` | int | Schema version from `STATE_SCHEMA_VERSION` |
| `current_session` | object | Summary of the active session (see below) |

`current_session` sub-object:

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Active session ID |
| `state_root` | string | Relative path to the session's `.dev/sessions/<id>/` directory |
| `session_path` | string | Relative path to session `session.json` |
| `workflow_path` | string | Relative path to `workflow_state.json` |
| `dashboard_path` | string | Relative path to `DASHBOARD.md` |
| `plan_path` | string | Relative path to `PLAN.md` |
| `tasks_path` | string | Relative path to `TASKS.md` |
| `logs_dir` | string | Relative path to `logs/` |
| `goal` | string or null | Bootstrap goal summary |
| `updated_at` | ISO-8601 string | Last update in this session |
| `active_phase` | string or null | Current workflow phase |
| `active_roadmap_phase_ids` | list[string] | Active roadmap phase IDs |
| `active_worktree_id` | string or null | Active managed worktree for the session summary |
| `managed_worktree_count` | int | Number of tracked managed worktrees in the session |

### Per-session file (`.dev/sessions/<id>/session.json`)

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Unique session identifier |
| `created_at` | ISO-8601 string | Session creation timestamp |
| `updated_at` | ISO-8601 string | Last mutation timestamp |
| `run_type` | string | `"bootstrap"` or `"session"` |
| `status` | string | `"active"` while in use |
| `state_schema_version` | int | Schema version |
| `active_phase` | string | Current workflow phase (e.g. `"plan"`) |
| `active_roadmap_phase_ids` | list[string] | Active roadmap phase IDs (e.g. `["phase_1"]`) |
| `resume_token` | string | Phase + checkpoint for resume (e.g. `"plan:bootstrap"`) |
| `last_safe_checkpoint` | object | Last verified resume point (`phase`, `timestamp`, `description`) |
| `bootstrap` | object | Bootstrap context (see below) |
| `task_sync` | object | Parsed operator task state (see below) |
| `next_action` | string | Human-readable description of what to do next |
| `notes` | list[string] | Operator notes |
| `loop` | object | Loop execution state (`status`, `attempts_completed`, etc.) |
| `supervisor_report` | object | Supervisor verdict path and status |
| `latest_continuation_prompt` | string or null | Most recent continuation prompt text |
| `current_run` | object or null | Metadata for the in-flight run (cleared on completion) |
| `latest_run` | object or null | Metadata for the most recently completed run |
| `operator_state_mtime` | float or null | mtime of the operator task file at last sync |
| `worktrees` | object, optional | Session-scoped managed worktree registry (see below) |

`current_run` and `latest_run` include the serialized agent run metadata from
`AgentRunStarted.to_dict()` / `AgentRunResult.to_dict()`. For worktree-aware
execution the most relevant fields are:

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | string | Stable runtime identifier for the agent call |
| `workdir` | string | Effective working directory used for the external CLI |
| `artifacts` | object | Paths to prompt/stdout/stderr/metadata artifacts |
| `artifact_refs` | list[object] | Typed artifact references for the same prompt/stdout/stderr/metadata files |

When managed worktree isolation is active, `workdir` points at the isolated
checkout path rather than the primary repository root.

`bootstrap` sub-object:

| Field | Type | Description |
|-------|------|-------------|
| `goal` | string | Full goal text |
| `captured_at` | ISO-8601 string | When the goal was recorded |
| `state_root` | string | Relative path to this session's directory |
| `prompt_summary` | string | Short summary of the prompt goal |
| `prompt_fingerprint` | string or null | Hash of the prompt text for change detection |
| `prompt_path` | string | (added by `persist_input_prompt`) Relative path to `PROMPT.md` |
| `global_prompt_path` | string | (added by `persist_input_prompt`) Global mirror path |
| `repo_guidance` | object | Resolved guidance files (`rule_files`, `workflow_files`) |

`task_sync` sub-object (produced by `tasks.parse_tasks_document`):

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Path of the operator task document parsed |
| `synced_at` | ISO-8601 string | Timestamp of last sync |
| `resume_checkpoint` | string or null | Task item used as resume target |
| `items` | list[object] | Parsed task items (`text`, `completed`, `is_checkpoint`) |

`worktrees` sub-object:

This block is omitted until the runtime tracks at least one managed worktree.
Readers must treat an absent block as "no tracked worktrees".

| Field | Type | Description |
|-------|------|-------------|
| `active_worktree_id` | string or null | Currently active managed worktree for the session |
| `managed` | list[object] | Tracked managed worktree records |

Consistency rule:
When `active_worktree_id` is present, it identifies the sole managed record
whose lifecycle `status` is treated as `active`. Conflicting payloads are
normalized on read so stale `active` records do not make resume or cleanup
behavior ambiguous. Duplicate `worktree_id` entries are collapsed into one
canonical record during normalization.

`managed[]` item shape:

| Field | Type | Description |
|-------|------|-------------|
| `worktree_id` | string | Stable managed worktree identifier |
| `source_repo_root` | string | Absolute source repository root |
| `isolated_path` | string | Absolute managed worktree path |
| `owner` | object | Ownership metadata (`session_id`, `run_id`, `agent_role`) |
| `status` | string | Lifecycle status such as `planned`, `active`, or `removed` |

---

## workflow_state.json

**Role**: Workflow-scoped machine truth. Tracks the active workflow phase,
pipeline configuration, roadmap progress, operator sync status, and run
metadata. Mirrors the session state but is scoped to the workflow rather than
the session lifecycle.

**Written by**: `StateRepository.ensure_bootstrap_state`, `write_workflow_state`,
`record_latest_run`, `record_current_run`, `persist_input_prompt`,
`OperatorSync.refresh_active_roadmap_phase_ids`, `sync_operator_state`.

### Root-level index (`.dev/workflow_state.json`)

Like `session.json`, the root file acts as an **index** when a session is active.

| Field | Type | Description |
|-------|------|-------------|
| `version` | int | File format version (currently `1`) |
| `state_schema_version` | int | Schema version |
| `updated_at` | ISO-8601 string | Last mutation timestamp |
| `mode` | string | Execution mode, typically `"supervised"` |
| `active_session_id` | string | Active session ID |
| `default_session_id` | string | Default session ID |
| `source_of_truth` | object | Paths to authoritative state files |
| `session_index` | object | Active session ID and sessions dir |
| `current_session` | object | Summary of the active session |
| `sessions` | list[object] | All known sessions from `list_sessions()` |

### Per-session file (`.dev/sessions/<id>/workflow_state.json`)

| Field | Type | Description |
|-------|------|-------------|
| `version` | int | `1` |
| `state_schema_version` | int | Schema version |
| `initialized_at` | ISO-8601 string | When this state was first written |
| `updated_at` | ISO-8601 string | Last mutation timestamp |
| `mode` | string | `"supervised"` |
| `source_of_truth` | object | Paths to authoritative goal and state files |
| `state_schema` | object | Template paths and task marker configuration |
| `workflow` | object | Active phase, phase sequence, resume target |
| `roadmap` | object | Active phase IDs and priority order |
| `supervisor` | object | Verdict, escalation status, reason |
| `bootstrap` | object | Same structure as session `bootstrap` sub-object |
| `session` | object | `path` and `status` of the session file |
| `artifacts` | object | Paths to all generated state files |
| `operator_sync` | object | Task sync state (mirrors `task_sync` in session) |
| `current_run` | object or null | In-flight run metadata |
| `latest_run` | object or null | Most recently completed run metadata |
| `intake` | object | Request classification result from `intake.classify_request` |
| `workflow_policy` | object | Phase enablement policy from `workflow_policy` |
| `worktrees` | object, optional | Workflow-scoped managed worktree registry (same shape as `session.json`) |

As in `session.json`, the serialized `current_run` and `latest_run` payloads
record the effective `workdir`. This is the quickest machine-readable signal
for whether a run used the primary checkout or a managed worktree.

`workflow` sub-object:

| Field | Type | Description |
|-------|------|-------------|
| `active_phase` | string | Current phase (e.g. `"develop"`) |
| `last_completed_phase` | string | Most recently finished phase |
| `allowed_sequence` | list[string] | Ordered list of valid phases |
| `resume_from_phase` | string | Phase to resume from after interruption |

### Worktree Compatibility

- `worktrees` is optional in both per-session state files.
- Older payloads that omit `worktrees` remain valid and are interpreted as
  "no tracked managed worktrees".
- Conflicting `worktrees` payloads are normalized on read so only the selected
  `active_worktree_id` remains `status: active`; any stale extra `active`
  records are demoted to non-active lifecycle state.
- Duplicate `worktree_id` entries are collapsed to a single canonical managed
  record during normalization and later updates.
- Root index files expose worktree summary fields only in `current_session`
  metadata; they do not become the canonical worktree registry.
- When managed worktree isolation is active for a run, `current_run.workdir`
  and `latest_run.workdir` point at the isolated checkout while `worktrees`
  remains the canonical registry for resume and cleanup decisions.

`roadmap` sub-object:

| Field | Type | Description |
|-------|------|-------------|
| `active_phase_ids` | list[string] | Currently active roadmap phase IDs |
| `priority_order` | list[string] | Ordered phase IDs from the improvement roadmap |

---

## Migration Notes

### Legacy flat-root layout

Before the session model was introduced, state files lived directly under
`.dev/` rather than `.dev/sessions/<id>/`. `SessionManager.migrate_legacy_root_snapshot`
detects this layout and moves files into a generated session directory. The
migration is idempotent.

### Detecting schema version

Both `session.json` and `workflow_state.json` include `state_schema_version`.
The current constant is defined in `state/models.py` as `STATE_SCHEMA_VERSION`.
A missing or older value indicates a pre-migration file.
