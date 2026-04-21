from __future__ import annotations

import json
from pathlib import Path

from dormammu.agent.models import AgentRunResult, AgentRunStarted, CliCapabilities
from dormammu.artifacts import ArtifactRef, ArtifactWriter


def test_artifact_writer_generates_deterministic_runtime_paths(tmp_path: Path) -> None:
    dev_dir = tmp_path / ".dev"
    writer = ArtifactWriter(base_dir=dev_dir, logs_dir=dev_dir / "logs")

    assert writer.stage_report_path(
        role="tester",
        stem="artifact-writer",
        date_str="20260422",
    ) == dev_dir / "logs" / "20260422_tester_artifact-writer.md"
    assert writer.checkpoint_report_path(
        checkpoint_kind="plan",
        stem="artifact-writer",
        date_str="20260422",
    ) == dev_dir / "logs" / "check_plan_artifact-writer_20260422.md"
    assert writer.evaluator_report_path(
        stem="artifact-writer",
        date_str="20260422",
    ) == dev_dir / "logs" / "20260422_evaluator_artifact-writer.md"
    assert writer.supervisor_report_path() == dev_dir / "supervisor_report.md"
    assert writer.continuation_prompt_path() == dev_dir / "continuation_prompt.txt"
    assert writer.run_prompt_path(run_id="run-123") == dev_dir / "logs" / "run-123.prompt.txt"
    assert writer.run_metadata_path(run_id="run-123") == dev_dir / "logs" / "run-123.meta.json"

    assert writer.checkpoint_report_path(
        checkpoint_kind="plan",
        stem="artifact-writer-2",
        date_str="20260422",
    ) != writer.checkpoint_report_path(
        checkpoint_kind="plan",
        stem="artifact-writer",
        date_str="20260422",
    )


def test_artifact_writer_persists_markdown_and_json_with_typed_references(
    tmp_path: Path,
) -> None:
    dev_dir = tmp_path / ".dev"
    writer = ArtifactWriter(
        base_dir=dev_dir,
        logs_dir=dev_dir / "logs",
        now_factory=lambda: "2026-04-22T00:30:00+09:00",
        default_session_id="session-1",
    )

    report_ref = writer.write_markdown_report(
        kind="stage_report",
        markdown="# Tester\n\nOVERALL: PASS\n",
        path=writer.stage_report_path(
            role="tester",
            stem="artifact-writer",
            date_str="20260422",
        ),
        label="tester_report",
        run_id="run-1",
        role="tester",
        stage_name="tester",
    )
    metadata_ref = writer.write_json_metadata(
        kind="metadata",
        payload={"status": "ok", "count": 1},
        path=writer.run_metadata_path(run_id="run-1"),
        label="metadata",
        run_id="run-1",
        role="tester",
        stage_name="tester",
    )

    assert report_ref.path.read_text(encoding="utf-8") == "# Tester\n\nOVERALL: PASS\n"
    assert json.loads(metadata_ref.path.read_text(encoding="utf-8")) == {
        "status": "ok",
        "count": 1,
    }
    assert report_ref.created_at == "2026-04-22T00:30:00+09:00"
    assert report_ref.run_id == "run-1"
    assert report_ref.role == "tester"
    assert report_ref.stage_name == "tester"
    assert report_ref.session_id == "session-1"
    assert metadata_ref.content_type == "application/json"


def test_artifact_writer_bind_propagates_execution_identity_into_written_refs(
    tmp_path: Path,
) -> None:
    dev_dir = tmp_path / ".dev"
    writer = ArtifactWriter(
        base_dir=dev_dir,
        logs_dir=dev_dir / "logs",
        now_factory=lambda: "2026-04-22T00:31:00+09:00",
    ).bind(
        run_id="pipeline:run-1",
        role="evaluator",
        stage_name="plan_evaluator",
        session_id="session-7",
    )

    checkpoint_ref = writer.write_text_output(
        kind="checkpoint_report",
        text="DECISION: PROCEED\n",
        path=writer.checkpoint_report_path(
            checkpoint_kind="plan",
            stem="artifact-bind",
            date_str="20260422",
        ),
        label="plan_checkpoint_report",
        content_type="text/markdown",
    )

    assert checkpoint_ref.path.read_text(encoding="utf-8") == "DECISION: PROCEED\n"
    assert checkpoint_ref.created_at == "2026-04-22T00:31:00+09:00"
    assert checkpoint_ref.run_id == "pipeline:run-1"
    assert checkpoint_ref.role == "evaluator"
    assert checkpoint_ref.stage_name == "plan_evaluator"
    assert checkpoint_ref.session_id == "session-7"


def test_artifact_ref_round_trips_through_dict_payload() -> None:
    artifact = ArtifactRef.from_path(
        kind="continuation_prompt",
        path="/tmp/continuation_prompt.txt",
        label="continuation_prompt",
        content_type="text/plain",
        created_at="2026-04-22T00:30:00+09:00",
        run_id="run-1",
        role="reviewer",
        stage_name="reviewer",
        session_id="session-1",
        metadata={"source": "test"},
    )

    restored = ArtifactRef.from_dict(artifact.to_dict())

    assert restored == artifact


def test_agent_run_models_serialize_artifact_refs(tmp_path: Path) -> None:
    capabilities = CliCapabilities(
        help_flag="--help",
        prompt_file_flag="--prompt-file",
        prompt_arg_flag="--prompt",
        workdir_flag=None,
        help_text="help",
        help_exit_code=0,
    )
    logs_dir = tmp_path / ".dev" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = logs_dir / "run.prompt.txt"
    stdout_path = logs_dir / "run.stdout.log"
    stderr_path = logs_dir / "run.stderr.log"
    metadata_path = logs_dir / "run.meta.json"
    for path in (prompt_path, stdout_path, stderr_path, metadata_path):
        path.write_text("x\n", encoding="utf-8")

    started = AgentRunStarted(
        run_id="run-1",
        cli_path=Path("codex"),
        workdir=tmp_path,
        prompt_mode="file",
        command=("codex",),
        started_at="2026-04-22T00:31:00+09:00",
        prompt_path=prompt_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        metadata_path=metadata_path,
        capabilities=capabilities,
    )
    result = AgentRunResult(
        run_id="run-1",
        cli_path=Path("codex"),
        workdir=tmp_path,
        prompt_mode="file",
        command=("codex",),
        exit_code=0,
        started_at="2026-04-22T00:31:00+09:00",
        completed_at="2026-04-22T00:31:10+09:00",
        prompt_path=prompt_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        metadata_path=metadata_path,
        capabilities=capabilities,
    )

    started_payload = started.to_dict()
    result_payload = result.to_dict()

    assert {artifact["kind"] for artifact in started_payload["artifact_refs"]} == {
        "prompt",
        "stdout",
        "stderr",
        "metadata",
    }
    assert all(artifact["run_id"] == "run-1" for artifact in result_payload["artifact_refs"])
