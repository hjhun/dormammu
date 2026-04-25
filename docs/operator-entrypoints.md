# Operator Entry Points

This document is the human-readable companion to
`backend/dormammu/operator_commands.py`. The Python matrix is the test fixture;
this document explains the ownership boundary.

## Boundary

Dormammu remains CLI-only. Operator surfaces are:

- CLI commands from `dormammu`.
- The interactive shell started by `dormammu` or `dormammu shell`.
- The long-running `daemonize` worker.
- Telegram bot commands attached to the daemon worker.

Shared domain behavior lives in `backend/dormammu/operator_services.py`:

| Service | Owns | Used by |
|---------|------|---------|
| `ConfigOperatorService` | resolved config reads and supported config writes | CLI and shell |
| `DaemonOperatorService` | daemon config loading, queue listing, enqueue, status, stop, and log tail | shell |
| `GoalsOperatorService` | goals directory listing, goal file creation, and deletion | Telegram |

The CLI still owns command-line parsing. Runtime execution remains owned by
`PipelineRunner`, `LoopRunner`, `RecoveryManager`, `DaemonRunner`, and
`CliAdapter`.

## Command Matrix

| Surface | Command | Domain | Service | State transition |
|---------|---------|--------|---------|------------------|
| CLI | `show-config` | config | `ConfigOperatorService` | read |
| CLI | `set-config` | config | `ConfigOperatorService` | write |
| CLI | `init-state` | session | `StateRepository` | write |
| CLI | `start-session` | session | `StateRepository` | write |
| CLI | `sessions` | session | `StateRepository` | read |
| CLI | `restore-session` | session | `StateRepository` | write |
| CLI | `run-once` | run | `PipelineRunner` / `CliAdapter` | write |
| CLI | `run`, `run-loop` | run | `PipelineRunner` / `LoopRunner` | write |
| CLI | `resume`, `resume-loop` | run | `RecoveryManager` | write |
| CLI | `inspect-cli` | config | `CliAdapter` | read |
| CLI | `doctor` | config | `Doctor` | read |
| CLI | `daemonize` | daemon | `DaemonRunner` | write |
| CLI | `shell` | shell | `InteractiveShellRunner` | read |
| shell | `/show-config` | config | `ConfigOperatorService` | read |
| shell | `/config` | config | `ConfigOperatorService` | write |
| shell | `/run` | run | CLI `run` | write |
| shell | `/run-once` | run | CLI `run-once` | write |
| shell | `/resume` | run | CLI `resume` | write |
| shell | `/sessions` | session | CLI `sessions` | read |
| shell | `/daemon start` | daemon | `DaemonOperatorService` plus process launch | write |
| shell | `/daemon stop` | daemon | `DaemonOperatorService` | write |
| shell | `/daemon status` | daemon | `DaemonOperatorService` | read |
| shell | `/daemon logs` | daemon | `DaemonOperatorService` | read |
| shell | `/daemon enqueue` | daemon | `DaemonOperatorService` | write |
| shell | `/daemon queue` | daemon | `DaemonOperatorService` | read |
| Telegram | `/status` | daemon | `DaemonRunner` | read |
| Telegram | `/run` | daemon | `DaemonRunner` | write |
| Telegram | `/queue` | daemon | `DaemonRunner` | read |
| Telegram | `/tail` | daemon | `TelegramProgressStream` | write |
| Telegram | `/result` | daemon | `DaemonRunner` | read |
| Telegram | `/sessions` | session | `StateRepository` | read |
| Telegram | `/repo` | session | `StateRepository` | write |
| Telegram | `/clear_sessions` | session | `StateRepository` | write |
| Telegram | `/goals` | goals | `GoalsOperatorService` | write |
| Telegram | `/shutdown` | daemon | `DaemonRunner` | write |

## Lifecycle Wording

Operator-facing daemon and goals queue status should use the same result-model
status words when describing completed prompt work:

- `completed`
- `failed`
- `manual_review_needed`

Queue observation commands may still use operational terms such as `queued`,
`running`, `waiting`, and `shutdown requested` before a result exists.
