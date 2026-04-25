from __future__ import annotations

from pathlib import Path

from dormammu.artifacts import ArtifactRef
from dormammu.results import (
    aggregate_run_summary,
    effective_stage_verdict,
    collect_result_artifacts,
    ResultStatus,
    ResultVerdict,
    RunResult,
    StageResult,
    aggregate_run_status,
    aggregate_run_verdict,
    latest_stage_results,
    parse_final_evaluator_verdict,
    parse_plan_evaluator_verdict,
    parse_reviewer_verdict,
    parse_tester_verdict,
    run_result_has_clean_terminal_stage_evidence,
    stage_results_have_clean_terminal_evidence,
)
from dormammu.runner_results import finalize_loop_run_result, terminal_loop_result


def test_stage_result_separates_status_from_verdict_and_attaches_report_artifact(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "review.md"
    stage = StageResult(
        role="reviewer",
        status=ResultStatus.COMPLETED,
        verdict=ResultVerdict.NEEDS_WORK,
        output="VERDICT: NEEDS_WORK",
        report_path=report_path,
    )

    assert stage.status == ResultStatus.COMPLETED
    assert stage.verdict == ResultVerdict.NEEDS_WORK
    assert stage.report_path == report_path
    assert any(artifact.path == report_path for artifact in stage.artifacts)
    assert any(
        artifact.role == "reviewer" and artifact.stage_name == "reviewer"
        for artifact in stage.artifacts
    )
    assert "output" not in stage.to_dict()
    assert stage.to_dict(include_output=True)["output"] == "VERDICT: NEEDS_WORK"


def test_stage_result_preserves_canonical_report_artifact_without_adding_alias(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "review.md"
    canonical_ref = ArtifactRef.from_path(
        kind="stage_report",
        path=report_path,
        label="reviewer_report",
        content_type="text/markdown",
        role="reviewer",
        stage_name="reviewer",
    )
    stage = StageResult(
        role="reviewer",
        stage_name="reviewer",
        status=ResultStatus.COMPLETED,
        verdict=ResultVerdict.APPROVED,
        report_path=report_path,
        artifacts=(canonical_ref,),
    )

    assert stage.artifacts == (canonical_ref,)
    assert [artifact.path for artifact in stage.artifacts].count(report_path) == 1


def test_run_result_preserves_canonical_continuation_artifact_without_losing_metadata() -> None:
    continuation_path = Path("/tmp/continuation.txt")
    canonical_ref = ArtifactRef.from_path(
        kind="continuation_prompt",
        path=continuation_path,
        label="continuation_prompt",
        content_type="text/plain",
        created_at="2026-04-22T03:00:00+09:00",
        run_id="run-123",
        role="reviewer",
        stage_name="reviewer",
        session_id="session-123",
    )
    result = RunResult(
        status="failed",
        attempts_completed=1,
        retries_used=0,
        max_retries=0,
        max_iterations=1,
        latest_run_id="run-123",
        supervisor_verdict="needs_work",
        report_path=None,
        continuation_prompt_path=continuation_path,
        artifacts=(canonical_ref,),
    )

    assert result.artifacts == (canonical_ref,)
    assert [artifact.path for artifact in result.artifacts].count(continuation_path) == 1


def test_latest_stage_results_and_aggregate_run_status_use_latest_attempt_per_stage() -> None:
    stage_results = (
        StageResult(role="tester", stage_name="tester", verdict="fail", output="OVERALL: FAIL"),
        StageResult(role="tester", stage_name="tester", verdict="pass", output="OVERALL: PASS"),
        StageResult(role="reviewer", stage_name="reviewer", verdict="approved", output="VERDICT: APPROVED"),
    )

    latest = latest_stage_results(stage_results)

    assert len(latest) == 2
    assert next(stage for stage in latest if stage.role == "tester").verdict == "pass"
    assert aggregate_run_status(stage_results, default="completed") == ResultStatus.COMPLETED


def test_latest_stage_results_preserve_chronology_of_latest_attempts() -> None:
    stage_results = (
        StageResult(role="reviewer", stage_name="reviewer", verdict="needs_work"),
        StageResult(role="developer", stage_name="developer", verdict="approved"),
        StageResult(role="reviewer", stage_name="reviewer", verdict="approved"),
    )

    latest = latest_stage_results(stage_results)

    assert [stage.role for stage in latest] == ["developer", "reviewer"]


def test_clean_terminal_stage_evidence_uses_latest_attempts_only() -> None:
    stage_results = (
        StageResult(role="tester", stage_name="tester", verdict="fail"),
        StageResult(role="tester", stage_name="tester", verdict="pass"),
        StageResult(role="reviewer", stage_name="reviewer", verdict="approved"),
    )

    assert stage_results_have_clean_terminal_evidence(stage_results)


def test_clean_terminal_stage_evidence_rejects_latest_failure_verdict() -> None:
    stage_results = (
        StageResult(role="tester", stage_name="tester", verdict="pass"),
        StageResult(role="reviewer", stage_name="reviewer", verdict="needs_work"),
    )

    assert not stage_results_have_clean_terminal_evidence(stage_results)


def test_run_result_clean_terminal_stage_evidence_requires_completed_run() -> None:
    result = RunResult(
        status="failed",
        attempts_completed=1,
        retries_used=0,
        max_retries=0,
        max_iterations=1,
        latest_run_id="run-123",
        supervisor_verdict="approved",
        report_path=None,
        continuation_prompt_path=None,
        stage_results=(StageResult(role="developer", verdict="approved"),),
    )

    assert not run_result_has_clean_terminal_stage_evidence(result)


def test_collect_result_artifacts_uses_only_latest_stage_attempt_per_key(
    tmp_path: Path,
) -> None:
    stale_artifact = ArtifactRef.from_path(
        kind="stage_report",
        path=tmp_path / "tester-stale.md",
        label="tester_report",
        content_type="text/markdown",
        role="tester",
        stage_name="tester",
    )
    latest_artifact = ArtifactRef.from_path(
        kind="stage_report",
        path=tmp_path / "tester-latest.md",
        label="tester_report",
        content_type="text/markdown",
        role="tester",
        stage_name="tester",
    )

    artifacts = collect_result_artifacts(
        (
            StageResult(
                role="tester",
                stage_name="tester",
                verdict="fail",
                artifacts=(stale_artifact,),
            ),
            StageResult(
                role="tester",
                stage_name="tester",
                verdict="pass",
                artifacts=(latest_artifact,),
            ),
        )
    )

    assert artifacts == (latest_artifact,)


def test_aggregate_run_status_preserves_completed_default_for_domain_verdict_failures() -> None:
    stage_results = (
        StageResult(role="tester", verdict="pass", output="OVERALL: PASS"),
        StageResult(role="reviewer", verdict="needs_work", output="VERDICT: NEEDS_WORK"),
    )

    assert aggregate_run_status(stage_results, default="completed") == ResultStatus.COMPLETED


def test_aggregate_run_status_fails_when_latest_stage_status_failed() -> None:
    stage_results = (
        StageResult(role="tester", verdict="pass", output="OVERALL: PASS"),
        StageResult(role="developer", status="failed", verdict=None, summary="loop failed"),
    )

    assert aggregate_run_status(stage_results, default="completed") == ResultStatus.FAILED


def test_effective_stage_verdict_uses_failure_status_when_no_domain_verdict_exists() -> None:
    stage = StageResult(role="evaluator", status="failed", verdict=None, summary="missing verdict")

    assert effective_stage_verdict(stage) == ResultVerdict.UNKNOWN


def test_aggregate_run_verdict_prefers_latest_failure_verdict_over_stale_success() -> None:
    stage_results = (
        StageResult(role="developer", verdict="approved", summary="developer approved"),
        StageResult(role="reviewer", verdict="needs_work", output="VERDICT: NEEDS_WORK"),
        StageResult(role="committer", verdict="committed", output="commit ok"),
    )

    assert aggregate_run_verdict(stage_results, default="approved") == ResultVerdict.NEEDS_WORK


def test_aggregate_run_summary_does_not_preserve_stale_success_summary_after_failure() -> None:
    stage_results = (
        StageResult(role="developer", verdict="approved", summary="developer approved"),
        StageResult(role="reviewer", verdict="needs_work", output="VERDICT: NEEDS_WORK"),
    )

    assert aggregate_run_summary(stage_results, default="developer approved") == (
        "Stage 'reviewer' concluded with verdict 'needs_work'."
    )


def test_run_result_serializes_stage_results_and_retry_metadata() -> None:
    result = RunResult(
        status="completed",
        attempts_completed=2,
        retries_used=1,
        max_retries=3,
        max_iterations=4,
        latest_run_id="run-123",
        supervisor_verdict="approved",
        report_path=Path("/tmp/report.md"),
        continuation_prompt_path=Path("/tmp/continuation.txt"),
        stage_results=(
            StageResult(role="developer", status="completed", verdict="approved", summary="approved"),
        ),
    )

    payload = result.to_dict()

    assert payload["status"] == "completed"
    assert payload["supervisor_verdict"] == "approved"
    assert payload["retry"]["attempt"] == 2
    assert payload["stage_results"][0]["role"] == "developer"


def test_finalize_loop_run_result_aggregates_latest_stage_verdict_and_artifacts(
    tmp_path: Path,
) -> None:
    latest_artifact = ArtifactRef.from_path(
        kind="stage_report",
        path=tmp_path / "review.md",
        label="reviewer_report",
        content_type="text/markdown",
        role="reviewer",
        stage_name="reviewer",
    )
    base = RunResult(
        status="completed",
        attempts_completed=1,
        retries_used=0,
        max_retries=1,
        max_iterations=2,
        latest_run_id="run-1",
        supervisor_verdict="approved",
        report_path=None,
        continuation_prompt_path=None,
        stage_results=(
            StageResult(role="reviewer", stage_name="reviewer", verdict="approved"),
        ),
    )

    result = finalize_loop_run_result(
        base,
        stage_results=(
            StageResult(role="tester", stage_name="tester", verdict="pass"),
            StageResult(
                role="reviewer",
                stage_name="reviewer",
                verdict="needs_work",
                artifacts=(latest_artifact,),
            ),
        ),
    )

    assert result.status == ResultStatus.COMPLETED
    assert result.supervisor_verdict == ResultVerdict.NEEDS_WORK
    assert result.artifacts == (latest_artifact,)
    assert result.summary == "Stage 'reviewer' concluded with verdict 'needs_work'."


def test_terminal_loop_result_standardizes_manual_review_from_stage() -> None:
    stage = StageResult(
        role="reviewer",
        stage_name="reviewer",
        verdict="manual_review_needed",
        summary="Iteration limit reached.",
    )

    result = terminal_loop_result(
        None,
        status="manual_review_needed",
        supervisor_verdict="manual_review_needed",
        stage=stage,
        stage_results=(stage,),
    )

    assert result.status == ResultStatus.MANUAL_REVIEW_NEEDED
    assert result.supervisor_verdict == ResultVerdict.MANUAL_REVIEW_NEEDED
    assert result.summary == "Iteration limit reached."
    assert result.stage_results == (stage,)


def test_verdict_parsers_return_normalized_values() -> None:
    assert parse_tester_verdict("OVERALL: FAIL") == ResultVerdict.FAIL
    assert (
        parse_tester_verdict("OVERALL: MANUAL_REVIEW_NEEDED")
        == ResultVerdict.MANUAL_REVIEW_NEEDED
    )
    assert parse_reviewer_verdict("VERDICT: NEEDS_WORK") == ResultVerdict.NEEDS_WORK
    assert parse_plan_evaluator_verdict("DECISION: PROCEED") == ResultVerdict.PROCEED
    assert parse_final_evaluator_verdict("VERDICT: partial") == ResultVerdict.PARTIAL


def test_tester_and_reviewer_parsers_require_explicit_markers() -> None:
    assert parse_tester_verdict("no tester verdict here") is None
    assert parse_reviewer_verdict("no reviewer verdict here") is None
