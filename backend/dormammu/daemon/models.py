from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dormammu.results import (
    ResultArtifact,
    RunResult,
    RetryMetadata,
    StageResult,
    TimingMetadata,
    artifact_from_path,
)

if TYPE_CHECKING:
    from dormammu.daemon.autonomous_config import AutonomousConfig
    from dormammu.daemon.goals_config import GoalsConfig


def _artifact_created_at(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _merge_result_artifacts(*groups: tuple[ResultArtifact, ...]) -> tuple[ResultArtifact, ...]:
    merged: list[ResultArtifact] = []
    seen: set[tuple[str, str, str | None]] = set()
    for group in groups:
        for artifact in group:
            key = (artifact.kind, str(artifact.path), artifact.label)
            if key in seen:
                continue
            merged.append(artifact)
            seen.add(key)
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class WatchConfig:
    backend: str = "auto"
    poll_interval_seconds: int = 60
    settle_seconds: int = 2


@dataclass(frozen=True, slots=True)
class QueueConfig:
    allowed_extensions: tuple[str, ...] = ()
    ignore_hidden_files: bool = True


@dataclass(frozen=True, slots=True)
class DaemonConfig:
    schema_version: int
    config_path: Path
    prompt_path: Path
    result_path: Path
    watch: WatchConfig
    queue: QueueConfig
    goals: GoalsConfig | None = None
    autonomous: AutonomousConfig | None = None


@dataclass(frozen=True, slots=True)
class QueuedPrompt:
    path: Path
    filename: str
    sort_key: tuple[int, object, str]
    detected_at: str


@dataclass(frozen=True, slots=True)
class PhaseExecutionResult:
    phase_name: str
    cli_path: Path
    exit_code: int
    run_id: str | None
    started_at: str | None
    completed_at: str | None
    stdout_path: Path | None
    stderr_path: Path | None
    prompt_path: Path | None
    metadata_path: Path | None
    command: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_name": self.phase_name,
            "cli_path": str(self.cli_path),
            "exit_code": self.exit_code,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stdout_path": str(self.stdout_path) if self.stdout_path else None,
            "stderr_path": str(self.stderr_path) if self.stderr_path else None,
            "prompt_path": str(self.prompt_path) if self.prompt_path else None,
            "metadata_path": str(self.metadata_path) if self.metadata_path else None,
            "command": list(self.command),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DaemonPromptResult:
    prompt_path: Path
    result_path: Path
    status: str
    started_at: str
    completed_at: str | None
    watcher_backend: str
    sort_key: tuple[int, object, str]
    session_id: str | None
    daemon_run_id: str | None = None
    run_result: RunResult | None = None
    phase_results: tuple[PhaseExecutionResult, ...] = field(default_factory=tuple)
    daemon_artifacts: tuple[ResultArtifact, ...] = field(default_factory=tuple)
    error: str | None = None
    plan_all_completed: bool | None = None
    next_pending_task: str | None = None

    @property
    def attempts_completed(self) -> int | None:
        return self.run_result.attempts_completed if self.run_result is not None else None

    @property
    def latest_run_id(self) -> str | None:
        return self.run_result.latest_run_id if self.run_result is not None else None

    @property
    def supervisor_verdict(self) -> str | None:
        if self.run_result is None or self.run_result.supervisor_verdict is None:
            return None
        return self.run_result.supervisor_verdict.value

    @property
    def supervisor_report_path(self) -> Path | None:
        return self.run_result.report_path if self.run_result is not None else None

    @property
    def continuation_prompt_path(self) -> Path | None:
        return self.run_result.continuation_prompt_path if self.run_result is not None else None

    @property
    def summary(self) -> str | None:
        return self.run_result.summary if self.run_result is not None else None

    @property
    def output(self) -> str | None:
        return self.run_result.output if self.run_result is not None else None

    @property
    def stage_results(self) -> tuple[StageResult, ...]:
        return self.run_result.stage_results if self.run_result is not None else ()

    @property
    def artifacts(self) -> tuple[ResultArtifact, ...]:
        run_artifacts = tuple(self.run_result.artifacts) if self.run_result is not None else ()
        daemon_artifacts = tuple(self.daemon_artifacts)
        result_report_artifact = self.result_report_artifact
        if result_report_artifact is None:
            return _merge_result_artifacts(run_artifacts, daemon_artifacts)
        return _merge_result_artifacts(
            run_artifacts,
            daemon_artifacts,
            (result_report_artifact,),
        )

    @property
    def result_report_artifact(self) -> ResultArtifact | None:
        for artifact in self.daemon_artifacts:
            if artifact.kind == "result_report" and artifact.path == self.result_path:
                return artifact
        return artifact_from_path(
            kind="result_report",
            path=self.result_path,
            label="result_report",
            content_type="text/markdown",
            created_at=_artifact_created_at(self.result_path),
            run_id=self.daemon_run_id or self.latest_run_id,
            role="daemon",
            stage_name="daemon",
            session_id=self.session_id,
            require_exists=True,
        )

    @property
    def retry(self) -> RetryMetadata | None:
        return self.run_result.retry if self.run_result is not None else None

    @property
    def timing(self) -> TimingMetadata | None:
        if self.run_result is not None and self.run_result.timing is not None:
            return self.run_result.timing
        return TimingMetadata(
            started_at=self.started_at,
            completed_at=self.completed_at,
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.run_result.metadata) if self.run_result is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_path": str(self.prompt_path),
            "result_path": str(self.result_path),
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "watcher_backend": self.watcher_backend,
            "sort_key": list(self.sort_key),
            "session_id": self.session_id,
            "daemon_run_id": self.daemon_run_id,
            "phase_results": [item.to_dict() for item in self.phase_results],
            "error": self.error,
            "plan_all_completed": self.plan_all_completed,
            "next_pending_task": self.next_pending_task,
            "attempts_completed": self.attempts_completed,
            "latest_run_id": self.latest_run_id,
            "supervisor_verdict": self.supervisor_verdict,
            "summary": self.summary,
            "stage_results": [item.to_dict() for item in self.stage_results],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "retry": self.retry.to_dict() if self.retry is not None else None,
            "timing": self.timing.to_dict() if self.timing is not None else None,
            "metadata": self.metadata,
            "run_result": (
                self.run_result.to_dict(include_output=True)
                if self.run_result is not None
                else None
            ),
            "supervisor_report_path": str(self.supervisor_report_path) if self.supervisor_report_path else None,
            "continuation_prompt_path": (
                str(self.continuation_prompt_path) if self.continuation_prompt_path else None
            ),
        }
