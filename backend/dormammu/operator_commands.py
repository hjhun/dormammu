from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperatorCommandSpec:
    surface: str
    command: str
    domain: str
    service: str
    state_transition: str
    description: str


COMMAND_MATRIX: tuple[OperatorCommandSpec, ...] = (
    OperatorCommandSpec("cli", "show-config", "config", "ConfigOperatorService", "read", "Print resolved runtime config."),
    OperatorCommandSpec("cli", "set-config", "config", "ConfigOperatorService", "write", "Mutate supported runtime config keys."),
    OperatorCommandSpec("cli", "init-state", "session", "StateRepository", "write", "Create or merge bootstrap .dev state."),
    OperatorCommandSpec("cli", "start-session", "session", "StateRepository", "write", "Archive active session and start a new one."),
    OperatorCommandSpec("cli", "sessions", "session", "StateRepository", "read", "List saved session snapshots."),
    OperatorCommandSpec("cli", "restore-session", "session", "StateRepository", "write", "Restore a saved session into the active view."),
    OperatorCommandSpec("cli", "run-once", "run", "PipelineRunner/CliAdapter", "write", "Run one bounded prompt execution."),
    OperatorCommandSpec("cli", "run", "run", "PipelineRunner/LoopRunner", "write", "Run the supervised prompt loop."),
    OperatorCommandSpec("cli", "run-loop", "run", "PipelineRunner/LoopRunner", "write", "Alias for run."),
    OperatorCommandSpec("cli", "resume", "run", "RecoveryManager", "write", "Resume the saved supervised loop state."),
    OperatorCommandSpec("cli", "resume-loop", "run", "RecoveryManager", "write", "Alias for resume."),
    OperatorCommandSpec("cli", "inspect-cli", "config", "CliAdapter", "read", "Inspect external CLI prompt handling."),
    OperatorCommandSpec("cli", "doctor", "config", "Doctor", "read", "Check local runtime readiness."),
    OperatorCommandSpec("cli", "daemonize", "daemon", "DaemonRunner", "write", "Process daemon prompt queue."),
    OperatorCommandSpec("cli", "shell", "shell", "InteractiveShellRunner", "read", "Start operator shell."),
    OperatorCommandSpec("shell", "/show-config", "config", "ConfigOperatorService", "read", "Print resolved runtime config."),
    OperatorCommandSpec("shell", "/config", "config", "ConfigOperatorService", "write", "Read or mutate config values."),
    OperatorCommandSpec("shell", "/run", "run", "cli run", "write", "Submit a supervised prompt."),
    OperatorCommandSpec("shell", "/run-once", "run", "cli run-once", "write", "Submit a bounded prompt."),
    OperatorCommandSpec("shell", "/resume", "run", "cli resume", "write", "Resume the saved run."),
    OperatorCommandSpec("shell", "/sessions", "session", "cli sessions", "read", "List session snapshots."),
    OperatorCommandSpec("shell", "/daemon start", "daemon", "DaemonOperatorService", "write", "Start daemon worker process."),
    OperatorCommandSpec("shell", "/daemon stop", "daemon", "DaemonOperatorService", "write", "Request daemon shutdown."),
    OperatorCommandSpec("shell", "/daemon status", "daemon", "DaemonOperatorService", "read", "Show daemon paths, heartbeat, and queue depth."),
    OperatorCommandSpec("shell", "/daemon logs", "daemon", "DaemonOperatorService", "read", "Show latest daemon log tail."),
    OperatorCommandSpec("shell", "/daemon enqueue", "daemon", "DaemonOperatorService", "write", "Queue a prompt file."),
    OperatorCommandSpec("shell", "/daemon queue", "daemon", "DaemonOperatorService", "read", "List queued prompt files."),
    OperatorCommandSpec("telegram", "/status", "daemon", "DaemonRunner", "read", "Show daemon status and active prompt."),
    OperatorCommandSpec("telegram", "/run", "daemon", "DaemonRunner", "write", "Queue a prompt for daemon execution."),
    OperatorCommandSpec("telegram", "/queue", "daemon", "DaemonRunner", "read", "List pending prompts."),
    OperatorCommandSpec("telegram", "/tail", "daemon", "TelegramProgressStream", "write", "Toggle progress streaming."),
    OperatorCommandSpec("telegram", "/result", "daemon", "DaemonRunner", "read", "Show result report content."),
    OperatorCommandSpec("telegram", "/sessions", "session", "StateRepository", "read", "Show recent session list."),
    OperatorCommandSpec("telegram", "/repo", "session", "StateRepository", "write", "Switch active repository context."),
    OperatorCommandSpec("telegram", "/clear_sessions", "session", "StateRepository", "write", "Delete current repo session data."),
    OperatorCommandSpec("telegram", "/goals", "goals", "GoalsOperatorService", "write", "List, add, or delete goal files."),
    OperatorCommandSpec("telegram", "/shutdown", "daemon", "DaemonRunner", "write", "Request daemon shutdown."),
)


def command_names_for_surface(surface: str) -> tuple[str, ...]:
    return tuple(item.command for item in COMMAND_MATRIX if item.surface == surface)
