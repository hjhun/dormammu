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
    LifecycleEventType,
    LifecycleRecorder,
    RunEventPayload,
    StageEventPayload,
)
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

    @staticmethod
    def _seed_repo(root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")
