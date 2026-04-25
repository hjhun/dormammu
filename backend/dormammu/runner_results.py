from __future__ import annotations

from typing import Sequence

from dormammu.loop_runner import LoopRunResult
from dormammu.results import (
    ResultStatus,
    ResultVerdict,
    StageResult,
    aggregate_run_status,
    aggregate_run_summary,
    aggregate_run_verdict,
    collect_result_artifacts,
    effective_stage_verdict,
    normalize_result_status,
    normalize_result_verdict,
)


def finalize_loop_run_result(
    result: LoopRunResult,
    *,
    stage_results: Sequence[StageResult] | None = None,
    terminal_error: str | None = None,
    status: ResultStatus | str | None = None,
    supervisor_verdict: ResultVerdict | str | None = None,
    summary: str | None = None,
) -> LoopRunResult:
    """Aggregate stage results into the final loop-compatible run result."""
    resolved_stage_results = tuple(stage_results if stage_results is not None else result.stage_results)
    final_status = (
        normalize_result_status(status)
        if status is not None
        else aggregate_run_status(resolved_stage_results, default=result.status)
    )
    final_verdict = (
        normalize_result_verdict(supervisor_verdict)
        if supervisor_verdict is not None
        else aggregate_run_verdict(
            resolved_stage_results,
            default=result.supervisor_verdict,
        )
    )
    final_summary = (
        summary
        if summary is not None
        else aggregate_run_summary(
            resolved_stage_results,
            default=result.summary or terminal_error,
        )
    )
    return LoopRunResult(
        status=final_status or ResultStatus.COMPLETED,
        attempts_completed=result.attempts_completed,
        retries_used=result.retries_used,
        max_retries=result.max_retries,
        max_iterations=result.max_iterations,
        latest_run_id=result.latest_run_id,
        supervisor_verdict=final_verdict,
        report_path=result.report_path,
        continuation_prompt_path=result.continuation_prompt_path,
        summary=final_summary,
        output=result.output,
        stage_results=resolved_stage_results,
        artifacts=collect_result_artifacts(resolved_stage_results, result.artifacts),
        retry=result.retry,
        timing=result.timing,
        metadata=result.metadata,
    )


def terminal_loop_result(
    loop_result: LoopRunResult | None,
    *,
    status: ResultStatus | str,
    stage_results: Sequence[StageResult],
    supervisor_verdict: ResultVerdict | str | None = None,
    stage: StageResult | None = None,
    summary: str | None = None,
) -> LoopRunResult:
    """Build a terminal result for pipeline branches that stop before completion."""
    normalized_status = normalize_result_status(status) or ResultStatus.FAILED
    normalized_verdict = (
        normalize_result_verdict(supervisor_verdict)
        if supervisor_verdict is not None
        else effective_stage_verdict(stage) if stage is not None else ResultVerdict.UNKNOWN
    )
    resolved_stage_results = tuple(stage_results)
    source_artifacts = loop_result.artifacts if loop_result is not None else ()
    return LoopRunResult(
        status=normalized_status,
        attempts_completed=loop_result.attempts_completed if loop_result else 0,
        retries_used=loop_result.retries_used if loop_result else 0,
        max_retries=loop_result.max_retries if loop_result else 0,
        max_iterations=loop_result.max_iterations if loop_result else 1,
        latest_run_id=loop_result.latest_run_id if loop_result else None,
        supervisor_verdict=normalized_verdict,
        report_path=loop_result.report_path if loop_result else None,
        continuation_prompt_path=(
            loop_result.continuation_prompt_path if loop_result else None
        ),
        summary=summary if summary is not None else (stage.summary if stage is not None else None),
        stage_results=resolved_stage_results,
        artifacts=collect_result_artifacts(resolved_stage_results, source_artifacts),
        retry=loop_result.retry if loop_result is not None else None,
        timing=loop_result.timing if loop_result is not None else None,
        metadata=loop_result.metadata if loop_result is not None else {},
    )
