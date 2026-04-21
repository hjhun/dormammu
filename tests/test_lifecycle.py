from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.lifecycle import (
    ArtifactPersistedPayload,
    ArtifactRef,
    EvaluatorCheckpointPayload,
    LifecycleEventType,
    LifecycleRecorder,
    RunEventPayload,
    StageEventPayload,
)
from dormammu.results import RunResult, StageResult
from dormammu.state import StateRepository


class LifecycleModelTests(unittest.TestCase):
    def test_event_serialization_keeps_optional_metadata_stable_when_absent(self) -> None:
        recorder = LifecycleRecorder.for_execution(
            repository=None,
            scope="loop",
            session_id="session-1",
            label="demo",
        )

        event = recorder.emit(
            event_type=LifecycleEventType.RUN_REQUESTED,
            role="developer",
            stage="developer",
            status="requested",
            payload=RunEventPayload(
                source="loop_runner",
                entrypoint="LoopRunner.run",
            ),
        )

        payload = event.to_dict()
        self.assertEqual(payload["event_type"], "run.requested")
        self.assertEqual(payload["artifact_refs"], [])
        self.assertEqual(payload["metadata"], {})
        self.assertEqual(payload["payload"]["source"], "loop_runner")
        self.assertEqual(payload["payload"]["entrypoint"], "LoopRunner.run")
        self.assertIsNone(payload["payload"]["prompt_summary"])

    def test_recorder_emits_realistic_stage_sequence_with_shared_run_id(self) -> None:
        recorder = LifecycleRecorder.for_execution(
            repository=None,
            scope="pipeline",
            session_id="session-2",
            label="phase-7",
        )

        events = [
            recorder.emit(
                event_type=LifecycleEventType.RUN_REQUESTED,
                role="pipeline",
                stage="pipeline",
                status="requested",
                payload=RunEventPayload(
                    source="pipeline_runner",
                    entrypoint="PipelineRunner.run",
                    trigger="pipeline",
                ),
            ),
            recorder.emit(
                event_type=LifecycleEventType.STAGE_QUEUED,
                role="developer",
                stage="developer",
                status="queued",
                payload=StageEventPayload(reason="Developer stage is queued."),
            ),
            recorder.emit(
                event_type=LifecycleEventType.STAGE_STARTED,
                role="developer",
                stage="developer",
                status="started",
                payload=StageEventPayload(reason="Developer stage entered active execution."),
            ),
            recorder.emit(
                event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                role="developer",
                stage="developer",
                status="persisted",
                payload=ArtifactPersistedPayload(
                    artifact_kind="stage_report",
                    summary="Persisted the developer stage report.",
                ),
                artifact_refs=(
                    ArtifactRef.from_path(
                        kind="stage_report",
                        path=Path("/tmp/developer-report.md"),
                        label="developer_report",
                        content_type="text/markdown",
                    ),
                ),
            ),
            recorder.emit(
                event_type=LifecycleEventType.STAGE_COMPLETED,
                role="developer",
                stage="developer",
                status="completed",
                payload=StageEventPayload(verdict="completed"),
            ),
            recorder.emit(
                event_type=LifecycleEventType.RUN_FINISHED,
                role="pipeline",
                stage="pipeline",
                status="completed",
                payload=RunEventPayload(
                    source="pipeline_runner",
                    entrypoint="PipelineRunner.run",
                    outcome="completed",
                ),
            ),
        ]

        self.assertEqual(
            [item.identity.event_type.value for item in events],
            [
                "run.requested",
                "stage.queued",
                "stage.started",
                "artifact.persisted",
                "stage.completed",
                "run.finished",
            ],
        )
        self.assertEqual({item.identity.run_id for item in events}, {recorder.run_id})


class LifecycleRepositoryTests(unittest.TestCase):
    def test_record_lifecycle_event_persists_to_session_and_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Lifecycle persistence test")

            recorder = LifecycleRecorder.for_execution(
                repository,
                scope="loop",
                session_id=repository.read_session_state()["session_id"],
                label="lifecycle-test",
            )
            event = recorder.emit(
                event_type=LifecycleEventType.STAGE_COMPLETED,
                role="developer",
                stage="developer",
                status="completed",
                payload=StageEventPayload(verdict="approved"),
            )

            session_state = repository.read_session_state()
            workflow_state = repository.read_workflow_state()
            self.assertEqual(
                session_state["lifecycle"]["latest_event"]["event_id"],
                event.identity.event_id,
            )
            self.assertEqual(
                workflow_state["lifecycle"]["latest_event"]["event_type"],
                "stage.completed",
            )
            self.assertEqual(len(session_state["lifecycle"]["history"]), 1)
            self.assertEqual(
                session_state["execution"]["latest_stage_result"]["stage_name"],
                "developer",
            )
            self.assertEqual(
                workflow_state["execution"]["latest_stage_result"]["verdict"],
                "approved",
            )

    def test_record_lifecycle_event_projects_current_run_and_checkpoint_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Lifecycle projection test")

            recorder = LifecycleRecorder.for_execution(
                repository,
                scope="pipeline",
                session_id=repository.read_session_state()["session_id"],
                label="projection-test",
            )
            recorder.emit(
                event_type=LifecycleEventType.RUN_REQUESTED,
                role="pipeline",
                stage="pipeline",
                status="requested",
                payload=RunEventPayload(
                    source="pipeline_runner",
                    entrypoint="PipelineRunner.run",
                    trigger="pipeline",
                ),
            )
            recorder.emit(
                event_type=LifecycleEventType.RUN_STARTED,
                role="pipeline",
                stage="pipeline",
                status="started",
                payload=RunEventPayload(
                    source="pipeline_runner",
                    entrypoint="PipelineRunner.run",
                    trigger="pipeline",
                ),
            )
            recorder.emit(
                event_type=LifecycleEventType.EVALUATOR_CHECKPOINT_DECISION,
                role="evaluator",
                stage="plan_evaluator",
                status="completed",
                payload=EvaluatorCheckpointPayload(
                    checkpoint_kind="plan",
                    decision="proceed",
                ),
            )

            session_state = repository.read_session_state()
            execution = session_state["execution"]
            assert execution["current_run"]["status"] == "started"
            assert execution["current_run"]["entrypoint"] == "PipelineRunner.run"
            assert execution["latest_checkpoint"]["decision"] == "proceed"

    def test_record_lifecycle_event_projects_latest_artifact_and_failed_stage_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Lifecycle artifact projection test")

            session_id = repository.read_session_state()["session_id"]
            recorder = LifecycleRecorder.for_execution(
                repository,
                scope="pipeline",
                session_id=session_id,
                label="artifact-projection-test",
            )
            artifact_ref = ArtifactRef.from_path(
                kind="stage_report",
                path=root / "logs" / "reviewer-report.md",
                label="reviewer_report",
                content_type="text/markdown",
                run_id=recorder.run_id,
                role="reviewer",
                stage_name="reviewer",
                session_id=session_id,
            )

            recorder.emit(
                event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                role="reviewer",
                stage="reviewer",
                status="persisted",
                payload=ArtifactPersistedPayload(
                    artifact_kind="stage_report",
                    summary="Persisted the reviewer report.",
                ),
                artifact_refs=(artifact_ref,),
            )
            recorder.emit(
                event_type=LifecycleEventType.STAGE_FAILED,
                role="reviewer",
                stage="reviewer",
                status="completed",
                payload=StageEventPayload(
                    attempt=1,
                    verdict="needs_work",
                    reason="Reviewer requested follow-up work.",
                ),
            )

            execution = repository.read_session_state()["execution"]
            assert execution["latest_artifact"]["artifact_kind"] == "stage_report"
            assert execution["latest_artifact"]["artifacts"][0]["kind"] == "stage_report"
            assert execution["latest_artifact"]["artifacts"][0]["path"] == str(artifact_ref.path)
            assert execution["latest_stage_result"]["stage_name"] == "reviewer"
            assert execution["latest_stage_result"]["status"] == "completed"
            assert execution["latest_stage_result"]["verdict"] == "needs_work"

    def test_record_stage_result_and_run_result_persist_explicit_execution_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Run result projection test")

            artifact = ArtifactRef.from_path(
                kind="stage_report",
                path=root / ".dev" / "logs" / "stage.md",
                label="stage_report",
                content_type="text/markdown",
                role="tester",
                stage_name="tester",
            )
            stage = StageResult(
                role="tester",
                stage_name="tester",
                verdict="pass",
                artifacts=(artifact,),
                summary="Tests passed.",
            )
            repository.record_stage_result(stage, run_id="pipeline:test")
            repository.record_run_result(
                RunResult(
                    status="completed",
                    attempts_completed=1,
                    retries_used=0,
                    max_retries=0,
                    max_iterations=1,
                    latest_run_id="pipeline:test",
                    supervisor_verdict="approved",
                    report_path=None,
                    continuation_prompt_path=None,
                    stage_results=(stage,),
                    artifacts=(artifact,),
                    summary="Pipeline finished cleanly.",
                ),
                run_id="pipeline:test",
            )

            session_state = repository.read_session_state()
            execution = session_state["execution"]
            assert execution["latest_run_id"] == "pipeline:test"
            assert execution["latest_execution_id"] == "pipeline:test"
            assert execution["latest_run"]["status"] == "completed"
            assert execution["latest_run"]["stage_results"][0]["stage_name"] == "tester"
            assert execution["stage_results"]["tester"]["verdict"] == "pass"

    def test_record_stage_result_populates_latest_run_id_before_run_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Stage result projection test")

            stage = StageResult(
                role="tester",
                stage_name="tester",
                verdict="pass",
                summary="Tests passed.",
            )

            repository.record_stage_result(stage, run_id="run-123")

            session_execution = repository.read_session_state()["execution"]
            workflow_execution = repository.read_workflow_state()["execution"]
            assert session_execution["latest_run_id"] == "run-123"
            assert session_execution["latest_execution_id"] == "run-123"
            assert workflow_execution["latest_run_id"] == "run-123"
            assert workflow_execution["latest_execution_id"] == "run-123"

    def test_record_run_result_prefers_explicit_execution_run_id_over_nested_agent_run_id(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Execution run id projection test")

            stage = StageResult(
                role="developer",
                stage_name="developer",
                verdict="done",
                summary="Developer loop completed.",
            )

            repository.record_run_result(
                RunResult(
                    status="completed",
                    attempts_completed=1,
                    retries_used=0,
                    max_retries=0,
                    max_iterations=1,
                    latest_run_id="agent-run-42",
                    supervisor_verdict="approved",
                    report_path=None,
                    continuation_prompt_path=None,
                    stage_results=(stage,),
                    summary="Pipeline finished cleanly.",
                ),
                run_id="pipeline-run-9",
            )

            execution = repository.read_session_state()["execution"]
            assert execution["latest_run_id"] == "pipeline-run-9"
            assert execution["latest_execution_id"] == "pipeline-run-9"
            assert execution["latest_run"]["run_id"] == "pipeline-run-9"
            assert execution["latest_run"]["execution_run_id"] == "pipeline-run-9"
            assert execution["latest_run"]["latest_run_id"] == "agent-run-42"

    @staticmethod
    def _seed_repo(root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")
