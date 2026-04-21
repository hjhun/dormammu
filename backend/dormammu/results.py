from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dormammu.artifacts import ArtifactRef


class ResultStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    MANUAL_REVIEW_NEEDED = "manual_review_needed"


class ResultVerdict(str, Enum):
    DONE = "done"
    PROCEED = "proceed"
    REWORK = "rework"
    PASS = "pass"
    FAIL = "fail"
    APPROVED = "approved"
    NEEDS_WORK = "needs_work"
    COMMITTED = "committed"
    GOAL_ACHIEVED = "goal_achieved"
    PARTIAL = "partial"
    NOT_ACHIEVED = "not_achieved"
    UNKNOWN = "unknown"
    PROMISE_COMPLETE = "promise_complete"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"
    MANUAL_REVIEW_NEEDED = "manual_review_needed"


ResultArtifact = ArtifactRef


@dataclass(frozen=True, slots=True)
class RetryMetadata:
    attempt: int | None = None
    next_attempt: int | None = None
    retries_used: int | None = None
    max_retries: int | None = None
    max_iterations: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "next_attempt": self.next_attempt,
            "retries_used": self.retries_used,
            "max_retries": self.max_retries,
            "max_iterations": self.max_iterations,
        }


@dataclass(frozen=True, slots=True)
class TimingMetadata:
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
        }


def normalize_result_status(value: ResultStatus | str | None) -> ResultStatus | None:
    if value is None:
        return None
    if isinstance(value, ResultStatus):
        return value
    return ResultStatus(str(value).strip().lower())


def normalize_result_verdict(value: ResultVerdict | str | None) -> ResultVerdict | None:
    if value is None:
        return None
    if isinstance(value, ResultVerdict):
        return value
    normalized = str(value).strip().lower()
    normalized = normalized.replace(" ", "_")
    return ResultVerdict(normalized)


def artifact_from_path(
    *,
    kind: str,
    path: Path | None,
    label: str | None = None,
    content_type: str | None = None,
    created_at: str | None = None,
    run_id: str | None = None,
    role: str | None = None,
    stage_name: str | None = None,
    session_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    require_exists: bool = False,
) -> ResultArtifact | None:
    if path is None:
        return None
    if require_exists and not path.exists():
        return None
    return ResultArtifact.from_path(
        kind=kind,
        path=path,
        label=label,
        content_type=content_type,
        created_at=created_at,
        run_id=run_id,
        role=role,
        stage_name=stage_name,
        session_id=session_id,
        metadata=metadata,
    )


def _merge_artifacts(
    artifacts: Iterable[ResultArtifact],
    extras: Iterable[ResultArtifact | None],
) -> tuple[ResultArtifact, ...]:
    merged: list[ResultArtifact] = [item for item in artifacts]
    seen = {(item.kind, str(item.path), item.label) for item in merged}
    for item in extras:
        if item is None:
            continue
        key = (item.kind, str(item.path), item.label)
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class StageResult:
    role: str
    verdict: ResultVerdict | str | None
    output: str = ""
    status: ResultStatus | str = ResultStatus.COMPLETED
    stage_name: str | None = None
    summary: str | None = None
    report_path: Path | None = None
    artifacts: tuple[ResultArtifact, ...] = ()
    retry: RetryMetadata | None = None
    timing: TimingMetadata | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", normalize_result_status(self.status))
        object.__setattr__(self, "verdict", normalize_result_verdict(self.verdict))
        object.__setattr__(self, "metadata", dict(self.metadata))
        report_artifact = None
        if self.report_path is not None and not any(
            artifact.path == self.report_path for artifact in self.artifacts
        ):
            report_artifact = artifact_from_path(
                kind="report",
                path=self.report_path,
                label="report",
                content_type="text/markdown",
                role=self.role,
                stage_name=self.stage_name or self.role,
            )
        object.__setattr__(
            self,
            "artifacts",
            _merge_artifacts(
                self.artifacts,
                (report_artifact,),
            ),
        )

    @property
    def key(self) -> str:
        return self.stage_name or self.role

    def to_dict(self, *, include_output: bool = False) -> dict[str, Any]:
        payload = {
            "role": self.role,
            "stage_name": self.stage_name,
            "status": self.status.value if self.status is not None else None,
            "verdict": self.verdict.value if self.verdict is not None else None,
            "summary": self.summary,
            "report_path": str(self.report_path) if self.report_path else None,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "retry": self.retry.to_dict() if self.retry is not None else None,
            "timing": self.timing.to_dict() if self.timing is not None else None,
            "metadata": dict(self.metadata),
        }
        if include_output:
            payload["output"] = self.output
        return payload


@dataclass(frozen=True, slots=True)
class RunResult:
    status: ResultStatus | str
    attempts_completed: int
    retries_used: int
    max_retries: int
    max_iterations: int
    latest_run_id: str | None
    supervisor_verdict: ResultVerdict | str | None
    report_path: Path | None
    continuation_prompt_path: Path | None
    summary: str | None = None
    output: str | None = None
    stage_results: tuple[StageResult, ...] = ()
    artifacts: tuple[ResultArtifact, ...] = ()
    retry: RetryMetadata | None = None
    timing: TimingMetadata | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", normalize_result_status(self.status))
        object.__setattr__(
            self,
            "supervisor_verdict",
            normalize_result_verdict(self.supervisor_verdict),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(
            self,
            "artifacts",
            _merge_artifacts(
                self.artifacts,
                (
                    artifact_from_path(
                        kind="supervisor_report",
                        path=self.report_path,
                        label="supervisor_report",
                        content_type="text/markdown",
                        run_id=self.latest_run_id,
                    ),
                    artifact_from_path(
                        kind="continuation_prompt",
                        path=self.continuation_prompt_path,
                        label="continuation_prompt",
                        content_type="text/plain",
                        run_id=self.latest_run_id,
                    ),
                ),
            ),
        )
        if self.retry is None:
            object.__setattr__(
                self,
                "retry",
                RetryMetadata(
                    attempt=self.attempts_completed,
                    retries_used=self.retries_used,
                    max_retries=self.max_retries,
                    max_iterations=self.max_iterations,
                ),
            )
        object.__setattr__(self, "stage_results", tuple(self.stage_results))

    @property
    def verdict(self) -> ResultVerdict | None:
        return self.supervisor_verdict

    def to_dict(self, *, include_output: bool = False) -> dict[str, Any]:
        payload = {
            "status": self.status.value if self.status is not None else None,
            "attempts_completed": self.attempts_completed,
            "retries_used": self.retries_used,
            "max_retries": self.max_retries,
            "max_iterations": self.max_iterations,
            "latest_run_id": self.latest_run_id,
            "supervisor_verdict": (
                self.supervisor_verdict.value
                if self.supervisor_verdict is not None
                else None
            ),
            "report_path": str(self.report_path) if self.report_path else None,
            "continuation_prompt_path": (
                str(self.continuation_prompt_path)
                if self.continuation_prompt_path
                else None
            ),
            "summary": self.summary,
            "stage_results": [
                item.to_dict(include_output=include_output)
                for item in self.stage_results
            ],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "retry": self.retry.to_dict() if self.retry is not None else None,
            "timing": self.timing.to_dict() if self.timing is not None else None,
            "metadata": dict(self.metadata),
        }
        if include_output:
            payload["output"] = self.output
        return payload


_TESTER_VERDICT_RE = re.compile(r"OVERALL\s*:\s*(PASS|FAIL)", re.IGNORECASE)
_REVIEWER_VERDICT_RE = re.compile(
    r"VERDICT\s*:\s*(APPROVED|NEEDS[_\s]WORK)",
    re.IGNORECASE,
)
_CHECKPOINT_PROCEED_RE = re.compile(r"DECISION\s*:\s*PROCEED", re.IGNORECASE)
_EVALUATOR_VERDICT_RE = re.compile(
    r"VERDICT\s*:\s*(goal_achieved|partial|not_achieved)",
    re.IGNORECASE,
)

_FAILURE_STATUSES = frozenset(
    {
        ResultStatus.FAILED,
        ResultStatus.BLOCKED,
        ResultStatus.MANUAL_REVIEW_NEEDED,
    }
)
_FAILURE_VERDICTS = frozenset(
    {
        ResultVerdict.FAIL,
        ResultVerdict.NEEDS_WORK,
        ResultVerdict.REWORK,
        ResultVerdict.BLOCKED,
        ResultVerdict.MANUAL_REVIEW_NEEDED,
    }
)
_RETRY_VERDICTS = frozenset(
    {
        ResultVerdict.FAIL,
        ResultVerdict.NEEDS_WORK,
        ResultVerdict.REWORK,
        ResultVerdict.REWORK_REQUIRED,
    }
)


def _parse_last_normalized_verdict(
    output: str,
    pattern: re.Pattern[str],
) -> ResultVerdict | None:
    matches = pattern.findall(output)
    if not matches:
        return None
    raw_verdict = matches[-1]
    if isinstance(raw_verdict, tuple):
        raw_verdict = next(
            (part for part in reversed(raw_verdict) if part),
            "",
        )
    return normalize_result_verdict(str(raw_verdict))


def parse_tester_verdict(output: str) -> ResultVerdict | None:
    return _parse_last_normalized_verdict(output, _TESTER_VERDICT_RE)


def parse_reviewer_verdict(output: str) -> ResultVerdict | None:
    return _parse_last_normalized_verdict(output, _REVIEWER_VERDICT_RE)


def parse_plan_evaluator_verdict(output: str) -> ResultVerdict:
    return (
        ResultVerdict.PROCEED
        if _CHECKPOINT_PROCEED_RE.search(output)
        else ResultVerdict.REWORK
    )


def parse_final_evaluator_verdict(output: str) -> ResultVerdict:
    verdict = _parse_last_normalized_verdict(output, _EVALUATOR_VERDICT_RE)
    if verdict is None:
        return ResultVerdict.UNKNOWN
    return verdict


def effective_stage_verdict(
    stage: StageResult,
    *,
    default: ResultVerdict | str | None = None,
) -> ResultVerdict | None:
    if stage.verdict is not None:
        return stage.verdict
    if stage.status == ResultStatus.BLOCKED:
        return ResultVerdict.BLOCKED
    if stage.status == ResultStatus.MANUAL_REVIEW_NEEDED:
        return ResultVerdict.MANUAL_REVIEW_NEEDED
    if stage.status == ResultStatus.FAILED:
        return ResultVerdict.UNKNOWN
    return normalize_result_verdict(default)


def stage_result_is_failure(stage: StageResult) -> bool:
    if stage.status in _FAILURE_STATUSES:
        return True
    return stage.verdict in _FAILURE_VERDICTS


def stage_result_requests_retry(stage: StageResult) -> bool:
    return stage.verdict in _RETRY_VERDICTS


def latest_stage_results(stage_results: Sequence[StageResult]) -> tuple[StageResult, ...]:
    latest_reversed: list[StageResult] = []
    seen: set[str] = set()
    for stage in reversed(stage_results):
        key = stage.key
        if key in seen:
            continue
        latest_reversed.append(stage)
        seen.add(key)
    return tuple(reversed(latest_reversed))


def aggregate_run_verdict(
    stage_results: Sequence[StageResult],
    *,
    default: ResultVerdict | str | None = None,
) -> ResultVerdict | None:
    latest = latest_stage_results(stage_results)
    normalized_default = normalize_result_verdict(default)
    if not latest:
        return normalized_default

    if any(stage.status == ResultStatus.BLOCKED for stage in latest):
        return ResultVerdict.BLOCKED
    if any(stage.status == ResultStatus.MANUAL_REVIEW_NEEDED for stage in latest):
        return ResultVerdict.MANUAL_REVIEW_NEEDED

    failed_stages = [stage for stage in latest if stage.status == ResultStatus.FAILED]
    if failed_stages:
        return effective_stage_verdict(
            failed_stages[-1],
            default=ResultVerdict.UNKNOWN,
        )

    failing_verdicts = [stage for stage in latest if stage.verdict in _FAILURE_VERDICTS]
    if failing_verdicts:
        return effective_stage_verdict(
            failing_verdicts[-1],
            default=normalized_default,
        )

    for stage in reversed(latest):
        verdict = effective_stage_verdict(stage)
        if verdict is not None:
            return verdict
    return normalized_default


def aggregate_run_summary(
    stage_results: Sequence[StageResult],
    *,
    default: str | None = None,
) -> str | None:
    latest = latest_stage_results(stage_results)
    for stage in reversed(latest):
        if not stage_result_is_failure(stage):
            continue
        if stage.summary:
            return stage.summary
        verdict = effective_stage_verdict(stage)
        if verdict is not None:
            return f"Stage '{stage.key}' concluded with verdict '{verdict.value}'."
        if stage.status is not None:
            return f"Stage '{stage.key}' finished with status '{stage.status.value}'."

    for stage in reversed(latest):
        if stage.summary:
            return stage.summary
    return default


def aggregate_run_status(
    stage_results: Sequence[StageResult],
    *,
    default: ResultStatus | str = ResultStatus.COMPLETED,
) -> ResultStatus:
    default_status = normalize_result_status(default) or ResultStatus.COMPLETED
    latest = latest_stage_results(stage_results)
    if any(stage.status == ResultStatus.BLOCKED for stage in latest):
        return ResultStatus.BLOCKED
    if any(stage.status == ResultStatus.MANUAL_REVIEW_NEEDED for stage in latest):
        return ResultStatus.MANUAL_REVIEW_NEEDED
    if any(stage.status == ResultStatus.FAILED for stage in latest):
        return ResultStatus.FAILED
    return default_status
