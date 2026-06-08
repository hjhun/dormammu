from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config
from dormammu.daemon.models import DaemonPromptResult
from dormammu.daemon import runner as daemon_runner_module
from dormammu.daemon.runner import (
    DaemonAlreadyRunningError,
    DaemonRunner,
    SessionProgressLogStream,
)
from dormammu.daemon.watchers import InotifyWatcher
from dormammu.agent import cli_adapter as cli_adapter_module
from dormammu.loop_runner import LoopRunResult
from dormammu.results import StageResult
from dormammu.state import StateRepository


class DaemonConfigTests(unittest.TestCase):
    def test_load_daemon_config_resolves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config_path = root / "ops" / "daemon.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "../queue/prompts",
                        "result_path": "../queue/results",
                    }
                ),
                encoding="utf-8",
            )

            config = load_daemon_config(config_path, app_config=self._app_config(root))

            self.assertEqual(config.prompt_path, (root / "queue" / "prompts").resolve())
            self.assertEqual(
                config.result_path,
                (root / ".test-home" / ".dormammu" / "results").resolve(),
            )

    def test_load_daemon_config_rejects_legacy_phase_cli_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config_path = root / "daemonize.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "./prompts",
                        "result_path": "./results",
                        "phases": {"plan": {"agent_cli": {"path": "codex"}}},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeError):
                load_daemon_config(config_path, app_config=self._app_config(root))

    @staticmethod
    def _seed_repo(root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")

    @staticmethod
    def _app_config(root: Path) -> AppConfig:
        env = dict(os.environ)
        env["HOME"] = str(root / ".test-home")
        env["DORMAMMU_SESSIONS_DIR"] = str(root / "sessions")
        return AppConfig.load(repo_root=root, env=env)


class DaemonRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    def test_run_pending_once_processes_prompt_via_loop_runner_and_removes_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            processed = DaemonRunner(app_config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertIn("PLAN complete: `yes`", result_text)
            self.assertIn("Supervisor verdict: `approved`", result_text)
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_completes_when_agent_marks_active_root_plan_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1, mark_root_plan=True)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("Finish the plan from the active root mirror\n", encoding="utf-8")

            processed = DaemonRunner(app_config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertIn("PLAN complete: `yes`", result_text)
            self.assertIn("Supervisor verdict: `approved`", result_text)
            self.assertEqual((root / ".attempt-count").read_text(encoding="utf-8").strip(), "1")
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_preserves_completed_status_when_terminal_stage_evidence_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            loop_result = LoopRunResult(
                status="completed",
                attempts_completed=1,
                retries_used=0,
                max_retries=1,
                max_iterations=2,
                latest_run_id="pipeline-success",
                supervisor_verdict="committed",
                report_path=None,
                continuation_prompt_path=None,
                stage_results=(
                    StageResult(role="developer", status="completed", verdict="approved"),
                    StageResult(role="tester", status="completed", verdict="pass"),
                    StageResult(role="reviewer", status="completed", verdict="approved"),
                    StageResult(role="committer", status="completed", verdict="committed"),
                ),
            )
            runner = DaemonRunner(app_config, daemon_config, progress_stream=io.StringIO())

            with (
                mock.patch.object(runner, "_run_prompt_loop", return_value=loop_result),
                mock.patch.object(runner, "_sync_plan_state", return_value=(False, None)),
            ):
                processed = runner.run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertIn("PLAN complete: `no`", result_text)
            self.assertNotIn("Loop returned completed but session PLAN.md is not fully complete.", result_text)
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_uses_active_agent_cli_from_dormammu_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1, name="configured-loop-agent")
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")

            DaemonRunner(app_config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertTrue((root / "configured-loop-agent-used.txt").exists())

    def test_run_pending_once_processes_one_prompt_at_a_time_in_sorted_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            (daemon_config.prompt_path / "002-second.md").write_text("Second prompt\n", encoding="utf-8")
            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")

            stderr = io.StringIO()
            runner = DaemonRunner(app_config, daemon_config, progress_stream=stderr)
            self.assertEqual(runner.run_pending_once(watcher_backend="polling"), 1)
            self.assertTrue((daemon_config.result_path / "001-first_RESULT.md").exists())
            self.assertFalse((daemon_config.result_path / "002-second_RESULT.md").exists())
            self.assertIn(
                "keeping queued prompts pending until the current prompt finishes",
                stderr.getvalue(),
            )

            self.assertEqual(runner.run_pending_once(watcher_backend="polling"), 1)
            self.assertTrue((daemon_config.result_path / "002-second_RESULT.md").exists())

    def test_run_pending_once_can_use_typescript_pending_decision_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            first = daemon_config.prompt_path / "001-first.md"
            second = daemon_config.prompt_path / "002-second.md"
            first.write_text("First prompt\n", encoding="utf-8")
            second.write_text("Second prompt\n", encoding="utf-8")
            progress = io.StringIO()
            runner = DaemonRunner(app_config, daemon_config, progress_stream=progress)

            with mock.patch.object(runner, "_process_prompt") as process_prompt:
                processed = runner.run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            process_prompt.assert_called_once_with(first, watcher_backend="polling")
            self.assertIn(
                "keeping queued prompts pending until the current prompt finishes: 002-second.md",
                progress.getvalue(),
            )
            captured = json.loads(
                (root / "captured-runner-payload.json").read_text(encoding="utf-8")
            )
            self.assertEqual(captured["entrypoint"], "daemon_pending_decision")
            self.assertEqual(captured["processed_count"], 0)
            self.assertEqual(captured["ready_prompt_paths"], [str(first), str(second)])

    def test_run_prompt_loop_can_use_typescript_prompt_route_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            active_cli = root / "agent-cli"
            self._write_typescript_runner_config(
                root,
                ts_runner,
                active_agent_cli=active_cli,
            )
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            progress = io.StringIO()
            runner = DaemonRunner(app_config, daemon_config, progress_stream=progress)
            prompt_path = daemon_config.prompt_path / "001-plan.md"
            prompt_text = "DORMAMMU_REQUEST_CLASS: planning_only\n\nPlan the next step."
            session_repository, scoped_config, _ = runner._start_prompt_session(
                prompt_path=prompt_path,
                prompt_text=prompt_text,
            )
            loop_result = LoopRunResult(
                status="completed",
                attempts_completed=1,
                retries_used=0,
                max_retries=1,
                max_iterations=1,
                latest_run_id="pipeline-planning",
                supervisor_verdict="approved",
                report_path=None,
                continuation_prompt_path=None,
            )

            with mock.patch("dormammu.daemon.runner.PipelineRunner") as pipeline_cls:
                pipeline_cls.return_value.run.return_value = loop_result
                result = runner._run_prompt_loop(
                    scoped_config=scoped_config,
                    session_repository=session_repository,
                    prompt_path=prompt_path,
                    prompt_text=prompt_text,
                )

            self.assertIs(result, loop_result)
            pipeline_cls.return_value.run.assert_called_once()
            self.assertIn(
                "source=typescript, reason=fake_planning_pipeline",
                progress.getvalue(),
            )
            captured = json.loads(
                (root / "captured-runner-payload.json").read_text(encoding="utf-8")
            )
            self.assertEqual(captured["entrypoint"], "daemon_prompt_route_decision")
            self.assertFalse(captured["has_agents_config"])
            self.assertEqual(captured["request_class"], "planning_only")
            self.assertFalse(captured["has_goal_file"])

    def test_extract_goal_file_path_can_use_typescript_goal_source_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            goal_file = root / "goals" / "ship-it.md"
            goal_file.parent.mkdir(parents=True, exist_ok=True)
            goal_file.write_text("# Goal\n\nShip it\n", encoding="utf-8")
            prompt_text = (
                f"<!-- dormammu:goal_source={goal_file} -->\n\n"
                "# Generated prompt\n"
            )

            result = DaemonRunner(app_config, daemon_config)._extract_goal_file_path(
                prompt_text,
            )

            self.assertEqual(result, goal_file)
            captured = json.loads(
                (root / "captured-runner-payload.json").read_text(encoding="utf-8")
            )
            self.assertEqual(captured["entrypoint"], "daemon_goal_source_decision")
            self.assertEqual(captured["prompt_text"], prompt_text)

    def test_run_pending_once_writes_terminal_failed_result_when_loop_budget_is_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=999, plan_completion_attempt=999)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            with mock.patch("dormammu.daemon.runner.DEFAULT_DAEMON_MAX_RETRIES", 0):
                processed = DaemonRunner(app_config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `failed`", result_text)
            self.assertIn("PLAN complete: `no`", result_text)
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_reprocesses_prompt_when_stale_completed_result_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            result_path = daemon_config.result_path / "001-first_RESULT.md"
            result_path.write_text("# Result\n\n## Summary\n\n- Status: `completed`\n", encoding="utf-8")

            processed = DaemonRunner(app_config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            self.assertIn("Status: `completed`", result_path.read_text(encoding="utf-8"))
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_can_use_typescript_existing_result_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_typescript_runner_config(
                root,
                ts_runner,
                active_agent_cli=loop_cli,
            )
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            result_path = daemon_config.result_path / "001-first_RESULT.md"
            result_path.write_text(
                "# Result\n\n## Summary\n\n- Status: `completed`\n",
                encoding="utf-8",
            )

            processed = DaemonRunner(app_config, daemon_config).run_pending_once(
                watcher_backend="polling",
            )

            self.assertEqual(processed, 1)
            self.assertFalse(prompt_path.exists())
            existing_result_payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_existing_result_decision"
            )
            self.assertEqual(
                existing_result_payload,
                {
                    "entrypoint": "daemon_existing_result_decision",
                    "prompt_path": str(prompt_path),
                    "result_path": str(result_path),
                    "result_exists": True,
                    "existing_result_status": "completed",
                },
            )
            result_status_payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_result_status_decision"
            )
            self.assertEqual(
                result_status_payload,
                {
                    "entrypoint": "daemon_result_status_decision",
                    "result_text": "# Result\n\n## Summary\n\n- Status: `completed`\n",
                },
            )

    def test_scan_prompt_queue_can_use_typescript_settle_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            config_path = self._write_daemon_config(root)
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            config_payload["watch"]["settle_seconds"] = 5
            config_path.write_text(
                json.dumps(config_payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(config_path, app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            ready_prompt_paths, retry_after_seconds = DaemonRunner(
                app_config,
                daemon_config,
            )._scan_prompt_queue()

            self.assertEqual(ready_prompt_paths, [])
            self.assertIsNotNone(retry_after_seconds)
            assert retry_after_seconds is not None
            self.assertGreater(retry_after_seconds, 0)
            settle_payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_prompt_settle_decision"
            )
            self.assertEqual(settle_payload["prompt_path"], str(prompt_path))
            self.assertEqual(settle_payload["settle_seconds"], 5)
            self.assertGreaterEqual(settle_payload["age_seconds"], 0)

    def test_scan_prompt_queue_can_use_typescript_queue_file_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "notes.txt"
            prompt_path.write_text("Not a markdown prompt\n", encoding="utf-8")

            ready_prompt_paths, retry_after_seconds = DaemonRunner(
                app_config,
                daemon_config,
            )._scan_prompt_queue()

            self.assertEqual(ready_prompt_paths, [])
            self.assertIsNone(retry_after_seconds)
            queue_file_payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_queue_file_decision"
            )
            self.assertEqual(
                queue_file_payload,
                {
                    "entrypoint": "daemon_queue_file_decision",
                    "prompt_path": str(prompt_path),
                    "in_progress": False,
                    "prompt_candidate": False,
                },
            )

    def test_run_pending_once_publishes_completed_result_only_after_prompt_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            result_path = daemon_config.result_path / "001-first_RESULT.md"

            original_replace = Path.replace

            def wrapped_replace(path_self: Path, target: Path | str) -> Path:
                if Path(target) == result_path:
                    self.assertFalse(
                        prompt_path.exists(),
                        "Prompt file must be removed before publishing the final result report",
                    )
                return original_replace(path_self, target)

            with mock.patch.object(Path, "replace", autospec=True, side_effect=wrapped_replace):
                processed = DaemonRunner(app_config, daemon_config).run_pending_once(
                    watcher_backend="polling"
                )

            self.assertEqual(processed, 1)
            self.assertIn("Status: `completed`", result_path.read_text(encoding="utf-8"))
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_falls_back_when_result_report_cli_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_invalid_result_report_loop_cli(root)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            processed = DaemonRunner(app_config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertIn("Configured CLI result report authoring failed", result_text)
            self.assertFalse(prompt_path.exists())

    def test_process_prompt_emits_input_prompt_artifact_ref_with_execution_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            lifecycle = mock.MagicMock()
            lifecycle.run_id = "daemon:test-run"

            with mock.patch(
                "dormammu.daemon.runner.LifecycleRecorder.for_execution",
                return_value=lifecycle,
            ):
                prompt_result = DaemonRunner(app_config, daemon_config)._process_prompt(
                    prompt_path,
                    watcher_backend="polling",
                )

            self.assertEqual(prompt_result.daemon_run_id, "daemon:test-run")

            daemon_artifact_calls = [
                call_args.kwargs
                for call_args in lifecycle.emit.call_args_list
                if call_args.kwargs.get("event_type").value == "artifact.persisted"
                and call_args.kwargs.get("role") == "daemon"
            ]
            input_prompt_call = next(
                kwargs
                for kwargs in daemon_artifact_calls
                if kwargs["payload"].artifact_kind == "input_prompt"
            )
            prompt_ref = input_prompt_call["artifact_refs"][0]

            self.assertEqual(prompt_ref.kind, "input_prompt")
            self.assertEqual(prompt_ref.run_id, "daemon:test-run")
            self.assertEqual(prompt_ref.role, "daemon")
            self.assertEqual(prompt_ref.stage_name, "daemon")
            self.assertEqual(prompt_ref.session_id, prompt_result.session_id)
            self.assertIsNotNone(prompt_ref.created_at)
            self.assertEqual(
                prompt_ref.path,
                app_config.sessions_dir / prompt_result.session_id / "PROMPT.md",
            )

    def test_process_prompt_attaches_daemon_artifact_metadata_to_result_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            prompt_result = DaemonRunner(app_config, daemon_config)._process_prompt(
                prompt_path,
                watcher_backend="polling",
            )

            self.assertEqual(prompt_result.status, "completed")
            self.assertIsNotNone(prompt_result.daemon_run_id)

            result_report_ref = next(
                artifact
                for artifact in prompt_result.artifacts
                if artifact.kind == "result_report"
            )
            self.assertEqual(result_report_ref.path, prompt_result.result_path)
            self.assertEqual(result_report_ref.run_id, prompt_result.daemon_run_id)
            self.assertEqual(result_report_ref.role, "daemon")
            self.assertEqual(result_report_ref.stage_name, "daemon")
            self.assertEqual(result_report_ref.session_id, prompt_result.session_id)
            self.assertIsNotNone(result_report_ref.created_at)

            session_repository = StateRepository(app_config, session_id=prompt_result.session_id)
            history = session_repository.read_session_state()["lifecycle"]["history"]

            daemon_artifact_events = [
                event
                for event in history
                if event["event_type"] == "artifact.persisted" and event["role"] == "daemon"
            ]
            self.assertEqual(
                [event["payload"]["artifact_kind"] for event in daemon_artifact_events],
                ["result_report"],
            )

            result_event_ref = daemon_artifact_events[0]["artifact_refs"][0]
            self.assertEqual(result_event_ref["path"], str(prompt_result.result_path))
            self.assertEqual(result_event_ref["run_id"], prompt_result.daemon_run_id)
            self.assertEqual(result_event_ref["role"], "daemon")
            self.assertEqual(result_event_ref["stage_name"], "daemon")
            self.assertEqual(result_event_ref["session_id"], prompt_result.session_id)
            self.assertEqual(result_event_ref["created_at"], result_report_ref.created_at)

            daemon_finished_events = [
                event
                for event in history
                if event["event_type"] == "run.finished" and event["role"] == "daemon"
            ]
            self.assertEqual(len(daemon_finished_events), 1)
            finished_ref = daemon_finished_events[0]["artifact_refs"][0]
            self.assertEqual(finished_ref["path"], str(prompt_result.result_path))
            self.assertEqual(finished_ref["run_id"], prompt_result.daemon_run_id)
            self.assertEqual(finished_ref["role"], "daemon")
            self.assertEqual(finished_ref["stage_name"], "daemon")
            self.assertEqual(finished_ref["session_id"], prompt_result.session_id)

    def test_publish_result_report_can_use_typescript_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            result_path = daemon_config.result_path / "001-first_RESULT.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            prompt_result = DaemonPromptResult(
                prompt_path=prompt_path,
                result_path=result_path,
                status="completed",
                started_at="2026-06-08T03:00:00+00:00",
                completed_at="2026-06-08T03:00:01+00:00",
                watcher_backend="polling",
                sort_key=(0, "001-first.md", "001-first.md"),
                session_id="session-123",
                daemon_run_id="daemon:test-run",
            )
            runner = DaemonRunner(app_config, daemon_config)

            with mock.patch.object(
                runner,
                "_render_result_report",
                return_value="# Result\n",
            ):
                published = runner._publish_result_report(prompt_result)

            self.assertFalse(prompt_path.exists())
            self.assertEqual(result_path.read_text(encoding="utf-8"), "# Result\n")
            result_ref = published.result_report_artifact
            self.assertIsNotNone(result_ref)
            assert result_ref is not None
            self.assertEqual(result_ref.kind, "result_report")
            self.assertEqual(result_ref.label, "result_report")
            self.assertEqual(result_ref.content_type, "text/markdown")
            self.assertEqual(result_ref.run_id, "daemon:test-run")
            self.assertEqual(result_ref.role, "daemon")
            self.assertEqual(result_ref.stage_name, "daemon")
            self.assertEqual(result_ref.session_id, "session-123")
            payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_result_report_decision"
            )
            self.assertEqual(
                payload,
                {
                    "entrypoint": "daemon_result_report_decision",
                    "prompt_path": str(prompt_path),
                    "result_path": str(result_path),
                    "prompt_exists": True,
                    "daemon_run_id": "daemon:test-run",
                    "latest_run_id": None,
                    "session_id": "session-123",
                },
            )

    def test_process_prompt_can_use_typescript_run_finished_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            runner = DaemonRunner(app_config, daemon_config)
            lifecycle = mock.MagicMock()
            lifecycle.run_id = "daemon:test-run"
            loop_result = LoopRunResult(
                status="completed",
                attempts_completed=2,
                retries_used=1,
                max_retries=3,
                max_iterations=4,
                latest_run_id="agent:test-run",
                supervisor_verdict="approved",
                report_path=None,
                continuation_prompt_path=None,
            )

            with (
                mock.patch(
                    "dormammu.daemon.runner.LifecycleRecorder.for_execution",
                    return_value=lifecycle,
                ),
                mock.patch.object(
                    runner,
                    "_run_prompt_loop",
                    return_value=loop_result,
                ),
                mock.patch.object(
                    runner,
                    "_sync_plan_state",
                    return_value=(True, None),
                ),
                mock.patch.object(
                    runner,
                    "_render_result_report",
                    return_value="# Result\n",
                ),
            ):
                prompt_result = runner._process_prompt(
                    prompt_path,
                    watcher_backend="polling",
                )

            self.assertEqual(prompt_result.status, "completed")
            run_finished_payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_run_finished_decision"
            )
            self.assertEqual(
                run_finished_payload,
                {
                    "entrypoint": "daemon_run_finished_decision",
                    "attempts_completed": 2,
                    "retries_used": 1,
                    "supervisor_verdict": "approved",
                    "outcome": "completed",
                    "error": None,
                },
            )

            finished_call = next(
                call_args.kwargs
                for call_args in lifecycle.emit.call_args_list
                if call_args.kwargs.get("event_type").value == "run.finished"
            )
            payload = finished_call["payload"]
            self.assertEqual(payload.source, "daemon_runner")
            self.assertEqual(payload.entrypoint, "DaemonRunner._process_prompt")
            self.assertEqual(payload.attempts_completed, 2)
            self.assertEqual(payload.retries_used, 1)
            self.assertEqual(payload.supervisor_verdict, "approved")
            self.assertEqual(payload.outcome, "completed")
            self.assertIsNone(payload.error)

    def test_terminal_error_message_can_use_typescript_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            loop_result = LoopRunResult(
                status="failed",
                attempts_completed=2,
                retries_used=2,
                max_retries=2,
                max_iterations=3,
                latest_run_id="agent:test-run",
                supervisor_verdict=None,
                report_path=None,
                continuation_prompt_path=None,
            )
            runner = DaemonRunner(app_config, daemon_config)

            message = runner._terminal_error_message(
                loop_result,
                " Phase 2. Validate ",
            )

            self.assertEqual(
                message,
                (
                    "Loop retry budget was exhausted before PLAN.md completed."
                    " Next pending PLAN task: Phase 2. Validate."
                ),
            )
            terminal_error_payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_terminal_error_decision"
            )
            self.assertEqual(
                terminal_error_payload,
                {
                    "entrypoint": "daemon_terminal_error_decision",
                    "status": "failed",
                    "next_pending_task": "Phase 2. Validate",
                },
            )

    def test_process_prompt_can_use_typescript_terminal_status_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            loop_result = LoopRunResult(
                status="completed",
                attempts_completed=1,
                retries_used=0,
                max_retries=1,
                max_iterations=2,
                latest_run_id="pipeline-success",
                supervisor_verdict="committed",
                report_path=None,
                continuation_prompt_path=None,
                stage_results=(
                    StageResult(role="developer", status="completed", verdict="approved"),
                    StageResult(role="tester", status="completed", verdict="pass"),
                    StageResult(role="reviewer", status="completed", verdict="approved"),
                    StageResult(role="committer", status="completed", verdict="committed"),
                ),
            )
            runner = DaemonRunner(
                app_config,
                daemon_config,
                progress_stream=io.StringIO(),
            )

            with (
                mock.patch.object(runner, "_run_prompt_loop", return_value=loop_result),
                mock.patch.object(runner, "_sync_plan_state", return_value=(False, None)),
                mock.patch.object(runner, "_render_result_report", return_value="# Result\n"),
            ):
                prompt_result = runner._process_prompt(
                    prompt_path,
                    watcher_backend="polling",
                )

            self.assertEqual(prompt_result.status, "completed")
            self.assertIsNone(prompt_result.error)
            terminal_status_payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_terminal_status_decision"
            )
            self.assertEqual(
                terminal_status_payload,
                {
                    "entrypoint": "daemon_terminal_status_decision",
                    "status": "completed",
                    "plan_all_completed": False,
                    "has_clean_terminal_stage_evidence": True,
                    "next_pending_task": None,
                },
            )

    def test_prompt_paths_can_use_typescript_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            prompt_path = daemon_config.prompt_path / "001-first.md"
            runner = DaemonRunner(app_config, daemon_config)

            result_path = runner._result_path_for_prompt(prompt_path)
            progress_log_path = runner._session_progress_log_path(prompt_path)

            self.assertEqual(
                result_path,
                daemon_config.result_path / "001-first_RESULT.md",
            )
            self.assertEqual(
                progress_log_path,
                daemon_config.result_path.parent
                / "progress"
                / "001-first_progress.log",
            )
            prompt_path_payloads = [
                json.loads(line)
                for line in (root / "captured-runner-payloads.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if json.loads(line)["entrypoint"] == "daemon_prompt_path_decision"
            ]
            self.assertEqual(len(prompt_path_payloads), 2)
            self.assertEqual(
                prompt_path_payloads[0],
                {
                    "entrypoint": "daemon_prompt_path_decision",
                    "prompt_path": str(prompt_path),
                    "result_path_root": str(daemon_config.result_path),
                },
            )

    def test_daemon_prompt_result_omits_result_report_artifact_when_file_was_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            missing_result_path = root / "missing_RESULT.md"
            prompt_result = DaemonPromptResult(
                prompt_path=root / "001-interrupted.md",
                result_path=missing_result_path,
                status="interrupted",
                started_at="2026-04-22T03:00:00+09:00",
                completed_at="2026-04-22T03:00:01+09:00",
                watcher_backend="polling",
                sort_key=(0, "001-interrupted.md", "001-interrupted.md"),
                session_id="session-123",
                daemon_run_id="daemon:test-run",
            )

            self.assertIsNone(prompt_result.result_report_artifact)
            self.assertEqual(prompt_result.artifacts, ())

    def test_result_report_artifact_ref_can_use_typescript_bridge(self) -> None:
        class PromptResultWithoutArtifact:
            result_report_artifact = None

            def __init__(self, *, result_path: Path) -> None:
                self.result_path = result_path
                self.daemon_run_id = ""
                self.latest_run_id = "agent:test-run"
                self.session_id = "session-123"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_path = daemon_config.result_path / "001-first_RESULT.md"
            result_path.write_text("# Result\n", encoding="utf-8")
            runner = DaemonRunner(app_config, daemon_config)

            artifact_ref = runner._result_report_artifact_ref(
                PromptResultWithoutArtifact(result_path=result_path)  # type: ignore[arg-type]
            )

            self.assertIsNotNone(artifact_ref)
            assert artifact_ref is not None
            self.assertEqual(artifact_ref.kind, "result_report")
            self.assertEqual(artifact_ref.path, result_path)
            self.assertEqual(artifact_ref.label, "result_report")
            self.assertEqual(artifact_ref.content_type, "text/markdown")
            self.assertEqual(artifact_ref.run_id, "agent:test-run")
            self.assertEqual(artifact_ref.role, "daemon")
            self.assertEqual(artifact_ref.stage_name, "daemon")
            self.assertEqual(artifact_ref.session_id, "session-123")
            payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_result_artifact_ref_decision"
            )
            self.assertEqual(
                payload,
                {
                    "entrypoint": "daemon_result_artifact_ref_decision",
                    "result_path": str(result_path),
                    "result_exists": True,
                    "created_at": artifact_ref.created_at,
                    "daemon_run_id": "",
                    "latest_run_id": "agent:test-run",
                    "session_id": "session-123",
                },
            )

    def test_expected_roadmap_phase_id_can_use_typescript_bridge(self) -> None:
        class WorkflowStateRepository:
            def read_workflow_state(self) -> dict[str, object]:
                return {
                    "roadmap": {
                        "active_phase_ids": ["", "phase_6", "phase_7"],
                    },
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            runner = DaemonRunner(app_config, daemon_config)

            phase_id = runner._expected_roadmap_phase_id(  # type: ignore[arg-type]
                WorkflowStateRepository()
            )

            self.assertEqual(phase_id, "phase_6")
            payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_roadmap_phase_decision"
            )
            self.assertEqual(
                payload,
                {
                    "entrypoint": "daemon_roadmap_phase_decision",
                    "active_phase_ids": ["", "phase_6", "phase_7"],
                },
            )

    def test_process_prompt_can_use_typescript_lifecycle_skip_for_missing_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-missing.md"

            prompt_result = DaemonRunner(app_config, daemon_config)._process_prompt(
                prompt_path,
                watcher_backend="polling",
            )

            self.assertEqual(prompt_result.status, "skipped")
            self.assertEqual(
                prompt_result.error,
                "Prompt file was deleted before processing.",
            )
            self.assertFalse(prompt_result.result_path.exists())
            payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_prompt_lifecycle_decision"
            )
            self.assertEqual(
                payload,
                {
                    "entrypoint": "daemon_prompt_lifecycle_decision",
                    "prompt_path": str(prompt_path),
                    "result_path": str(prompt_result.result_path),
                    "prompt_exists": False,
                },
            )

    def test_process_prompt_does_not_emit_missing_result_report_artifact_on_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-interrupt.md"
            prompt_path.write_text("Interrupt this prompt\n", encoding="utf-8")

            lifecycle = mock.MagicMock()
            lifecycle.run_id = "daemon:test-run"
            runner = DaemonRunner(app_config, daemon_config)

            with (
                mock.patch(
                    "dormammu.daemon.runner.LifecycleRecorder.for_execution",
                    return_value=lifecycle,
                ),
                mock.patch.object(runner, "_run_prompt_loop", side_effect=KeyboardInterrupt),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner._process_prompt(prompt_path, watcher_backend="polling")

            daemon_artifact_calls = [
                call_args.kwargs
                for call_args in lifecycle.emit.call_args_list
                if call_args.kwargs.get("event_type").value == "artifact.persisted"
                and call_args.kwargs.get("role") == "daemon"
            ]
            self.assertEqual(
                [call["payload"].artifact_kind for call in daemon_artifact_calls],
                ["input_prompt"],
            )

            daemon_finished_calls = [
                call_args.kwargs
                for call_args in lifecycle.emit.call_args_list
                if call_args.kwargs.get("event_type").value == "run.finished"
                and call_args.kwargs.get("role") == "daemon"
            ]
            self.assertEqual(len(daemon_finished_calls), 1)
            self.assertEqual(daemon_finished_calls[0]["status"], "interrupted")
            self.assertEqual(daemon_finished_calls[0]["artifact_refs"], ())
            self.assertFalse((daemon_config.result_path / "001-interrupt_RESULT.md").exists())

    def test_debug_progress_log_is_written_per_prompt_and_contains_runtime_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            progress_stream = SessionProgressLogStream(io.StringIO())
            self.addCleanup(progress_stream.close_log)
            runner = DaemonRunner(app_config, daemon_config, progress_stream=progress_stream)
            first_progress_log = daemon_config.result_path.parent / "progress" / "001-first_progress.log"
            second_progress_log = daemon_config.result_path.parent / "progress" / "002-second_progress.log"

            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")
            self.assertEqual(runner.run_pending_once(watcher_backend="polling"), 1)

            self.assertTrue(first_progress_log.exists())
            first_log_text = first_progress_log.read_text(encoding="utf-8")
            self.assertIn(str(first_progress_log), first_log_text)
            self.assertIn("daemon prompt detected: 001-first.md", first_log_text)
            self.assertIn("=== dormammu loop attempt ===", first_log_text)
            self.assertIn("attempt: 1", first_log_text)
            self.assertFalse(second_progress_log.exists())

            (daemon_config.prompt_path / "002-second.md").write_text("Second prompt\n", encoding="utf-8")
            self.assertEqual(runner.run_pending_once(watcher_backend="polling"), 1)

            self.assertTrue(second_progress_log.exists())
            second_log_text = second_progress_log.read_text(encoding="utf-8")
            self.assertIn(str(second_progress_log), second_log_text)
            self.assertIn("daemon prompt detected: 002-second.md", second_log_text)
            self.assertNotIn("001-first.md", second_log_text)
            self.assertIn("=== dormammu loop attempt ===", second_log_text)

    def test_run_pending_once_requires_active_agent_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            processed = DaemonRunner(app_config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `failed`", result_text)
            self.assertIn("active_agent_cli", result_text)
            self.assertFalse(prompt_path.exists())

    def test_run_forever_starts_watcher_before_emitting_startup_banner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(self._write_daemon_config(root), app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            progress_stream = io.StringIO()

            class RecordingWatcher:
                backend_name = "inotify"

                def __init__(self, owner: DaemonRunner) -> None:
                    self._owner = owner

                def start(self) -> None:
                    print("WATCHER_STARTED", file=progress_stream)

                def close(self) -> None:
                    return None

                def wait_for_changes(self) -> list[Path]:
                    self._owner.request_shutdown()
                    return []

            runner = DaemonRunner(app_config, daemon_config, progress_stream=progress_stream)
            runner._heartbeat_path = None
            runner.watcher = RecordingWatcher(runner)

            self.assertIsNone(runner.run_forever())

            log_text = progress_stream.getvalue()
            self.assertIn("WATCHER_STARTED", log_text)
            self.assertIn("watcher: inotify", log_text)
            self.assertLess(
                log_text.index("WATCHER_STARTED"),
                log_text.index("watcher: inotify"),
                "Watcher readiness must be established before the daemon advertises watcher startup.",
            )

    def test_startup_banner_lines_can_use_typescript_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            runner = DaemonRunner(app_config, daemon_config)

            projected = runner._project_typescript_startup_banner_decision(
                watcher_backend="polling"
            )
            lines = runner._startup_banner_lines(watcher_backend="polling")

            self.assertIsNotNone(projected)
            self.assertEqual(projected, lines)
            self.assertIn("extensions=.md", "\n".join(lines))
            self.assertEqual(lines[-2:], ["goals: disabled", "autonomous: disabled"])
            payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_startup_banner_decision"
            )
            self.assertEqual(
                payload,
                {
                    "entrypoint": "daemon_startup_banner_decision",
                    "repo_root": str(app_config.repo_root.resolve()),
                    "config_path": str(daemon_config.config_path),
                    "prompt_path": str(daemon_config.prompt_path),
                    "result_path": str(daemon_config.result_path),
                    "watcher_backend": "polling",
                    "requested_watcher_backend": "polling",
                    "poll_interval_seconds": 1,
                    "settle_seconds": 0,
                    "ignore_hidden_files": True,
                    "allowed_extensions": [".md"],
                    "goals_path": None,
                    "goals_interval_minutes": None,
                    "autonomous_enabled": False,
                    "autonomous_interval_minutes": None,
                    "autonomous_focus": None,
                    "autonomous_max_queued_tasks": None,
                },
            )

    def test_run_forever_can_use_typescript_loop_iteration_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            progress_stream = io.StringIO()

            class RecordingWatcher:
                backend_name = "polling"

                def __init__(self, owner: DaemonRunner) -> None:
                    self._owner = owner
                    self.wait_count = 0

                def start(self) -> None:
                    return None

                def close(self) -> None:
                    return None

                def wait_for_changes(self) -> list[Path]:
                    self.wait_count += 1
                    self._owner.request_shutdown()
                    return []

            runner = DaemonRunner(app_config, daemon_config, progress_stream=progress_stream)
            watcher = RecordingWatcher(runner)
            runner.watcher = watcher
            heartbeat_statuses: list[str] = []

            with (
                mock.patch.object(
                    runner,
                    "_write_heartbeat",
                    side_effect=lambda *, status: heartbeat_statuses.append(status),
                ),
                mock.patch.object(runner, "_remove_heartbeat"),
                mock.patch.object(runner, "run_pending_once", return_value=0),
            ):
                self.assertIsNone(runner.run_forever())

            self.assertEqual(watcher.wait_count, 1)
            self.assertEqual(heartbeat_statuses, ["idle", "idle"])
            captured = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_loop_iteration_decision"
            )
            self.assertEqual(captured["entrypoint"], "daemon_loop_iteration_decision")
            self.assertEqual(captured["processed_count"], 0)
            self.assertEqual(captured["in_progress_count"], 0)
            self.assertFalse(captured["shutdown_requested"])
            watcher_wait_payload = next(
                payload
                for payload in (
                    json.loads(line)
                    for line in (root / "captured-runner-payloads.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                if payload["entrypoint"] == "daemon_watcher_wait_decision"
            )
            self.assertEqual(
                watcher_wait_payload,
                {
                    "entrypoint": "daemon_watcher_wait_decision",
                    "wait_requested": True,
                    "shutdown_requested": False,
                    "watcher_backend": "polling",
                },
            )

    def test_run_forever_can_use_typescript_startup_shutdown_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            progress_stream = io.StringIO()

            class RecordingWatcher:
                backend_name = "polling"

                def __init__(self, owner: DaemonRunner) -> None:
                    self._owner = owner
                    self.close_count = 0

                def start(self) -> None:
                    return None

                def close(self) -> None:
                    self.close_count += 1

                def wait_for_changes(self) -> list[Path]:
                    self._owner.request_shutdown()
                    return []

            runner = DaemonRunner(app_config, daemon_config, progress_stream=progress_stream)
            watcher = RecordingWatcher(runner)
            runner.watcher = watcher
            goals_scheduler = mock.MagicMock()
            autonomous_scheduler = mock.MagicMock()
            runner._goals_scheduler = goals_scheduler
            runner._autonomous_scheduler = autonomous_scheduler
            heartbeat_statuses: list[str] = []

            with (
                mock.patch.object(
                    runner,
                    "_write_heartbeat",
                    side_effect=lambda *, status: heartbeat_statuses.append(status),
                ),
                mock.patch.object(runner, "_remove_heartbeat") as remove_heartbeat,
                mock.patch.object(runner, "run_pending_once", return_value=0),
            ):
                self.assertIsNone(runner.run_forever())

            self.assertEqual(heartbeat_statuses, ["idle", "idle"])
            goals_scheduler.start.assert_called_once()
            goals_scheduler.trigger_now.assert_called_once()
            goals_scheduler.stop.assert_called_once()
            autonomous_scheduler.start.assert_called_once()
            autonomous_scheduler.trigger_now.assert_called_once()
            autonomous_scheduler.stop.assert_called_once()
            self.assertEqual(watcher.close_count, 1)
            remove_heartbeat.assert_called_once()
            payloads = [
                json.loads(line)
                for line in (root / "captured-runner-payloads.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            payloads_by_entrypoint = {
                payload["entrypoint"]: payload for payload in payloads
            }
            self.assertEqual(
                payloads_by_entrypoint["daemon_startup_decision"],
                {
                    "entrypoint": "daemon_startup_decision",
                    "goals_scheduler_configured": True,
                    "autonomous_scheduler_configured": True,
                },
            )
            self.assertEqual(
                payloads_by_entrypoint["daemon_shutdown_decision"],
                {
                    "entrypoint": "daemon_shutdown_decision",
                    "goals_scheduler_configured": True,
                    "autonomous_scheduler_configured": True,
                    "progress_log_active": False,
                },
            )

    def test_run_forever_can_use_typescript_watcher_backend_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root, watch_backend="auto"),
                app_config=app_config,
            )
            progress_stream = io.StringIO()
            built_backends: list[str] = []

            class RecordingWatcher:
                def __init__(self, owner: DaemonRunner, backend_name: str) -> None:
                    self._owner = owner
                    self.backend_name = backend_name

                def start(self) -> None:
                    return None

                def close(self) -> None:
                    return None

                def wait_for_changes(self) -> list[Path]:
                    self._owner.request_shutdown()
                    return []

            runner = DaemonRunner(app_config, daemon_config, progress_stream=progress_stream)

            def fake_build_watcher(
                _prompt_dir: Path,
                watch_config: object,
                **_kwargs: object,
            ) -> RecordingWatcher:
                backend_name = getattr(watch_config, "backend")
                built_backends.append(backend_name)
                return RecordingWatcher(runner, backend_name)

            with (
                mock.patch.object(
                    daemon_runner_module.InotifyWatcher,
                    "is_available",
                    return_value=False,
                ),
                mock.patch.object(
                    daemon_runner_module,
                    "build_watcher",
                    side_effect=fake_build_watcher,
                ),
                mock.patch.object(runner, "_write_heartbeat"),
                mock.patch.object(runner, "_remove_heartbeat"),
                mock.patch.object(runner, "run_pending_once", return_value=0),
            ):
                self.assertIsNone(runner.run_forever())

            self.assertEqual(built_backends, ["polling"])
            payloads = [
                json.loads(line)
                for line in (root / "captured-runner-payloads.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            watcher_payload = next(
                payload
                for payload in payloads
                if payload["entrypoint"] == "daemon_watcher_backend_decision"
            )
            self.assertEqual(
                watcher_payload,
                {
                    "entrypoint": "daemon_watcher_backend_decision",
                    "requested_backend": "auto",
                    "inotify_available": False,
                },
            )

    @unittest.skipUnless(daemon_runner_module._HAS_FCNTL, "fcntl is required")
    def test_instance_lock_can_use_typescript_conflict_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            runner = DaemonRunner(app_config, daemon_config, progress_stream=io.StringIO())
            runner._pid_lock_path.parent.mkdir(parents=True, exist_ok=True)
            runner._pid_lock_path.write_text("1234", encoding="utf-8")

            with (
                mock.patch.object(
                    daemon_runner_module._fcntl,
                    "flock",
                    side_effect=OSError("busy"),
                ),
                self.assertRaises(DaemonAlreadyRunningError) as raised,
            ):
                with runner._instance_lock():
                    self.fail("lock acquisition should fail")

            self.assertIn("existing daemon PID: 1234", str(raised.exception))
            payloads = [
                json.loads(line)
                for line in (root / "captured-runner-payloads.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                payloads[-1],
                {
                    "entrypoint": "daemon_instance_lock_decision",
                    "fcntl_available": True,
                    "lock_acquired": False,
                    "prompt_path": str(daemon_config.prompt_path),
                    "existing_pid": "1234",
                },
            )

    @unittest.skipUnless(daemon_runner_module._HAS_FCNTL, "fcntl is required")
    def test_instance_lock_can_use_typescript_release_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            runner = DaemonRunner(app_config, daemon_config, progress_stream=io.StringIO())
            flock_flags: list[int] = []

            def record_flock(_lock_file: object, flags: int) -> None:
                flock_flags.append(flags)

            with mock.patch.object(
                daemon_runner_module._fcntl,
                "flock",
                side_effect=record_flock,
            ):
                with runner._instance_lock():
                    self.assertIsNotNone(runner._pid_lock_file)
                    self.assertEqual(
                        runner._pid_lock_path.read_text(encoding="utf-8"),
                        str(os.getpid()),
                    )

            self.assertIsNone(runner._pid_lock_file)
            self.assertFalse(runner._pid_lock_path.exists())
            self.assertEqual(
                flock_flags,
                [
                    daemon_runner_module._fcntl.LOCK_EX
                    | daemon_runner_module._fcntl.LOCK_NB,
                    daemon_runner_module._fcntl.LOCK_UN,
                ],
            )
            payloads = [
                json.loads(line)
                for line in (root / "captured-runner-payloads.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                [payload["entrypoint"] for payload in payloads],
                [
                    "daemon_instance_lock_decision",
                    "daemon_instance_unlock_decision",
                ],
            )
            self.assertTrue(payloads[0]["lock_acquired"])
            self.assertTrue(payloads[1]["lock_held"])

    def test_write_heartbeat_can_use_typescript_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            runner = DaemonRunner(app_config, daemon_config, progress_stream=io.StringIO())
            runner._heartbeat_path = root / "state" / "daemon_heartbeat.json"

            with (
                mock.patch.object(daemon_runner_module, "_get_pid", return_value=77),
                mock.patch.object(
                    daemon_runner_module,
                    "_iso_now",
                    return_value="2026-06-08T03:10:00+00:00",
                ),
            ):
                runner._write_heartbeat(status="busy")

            self.assertEqual(
                json.loads(runner._heartbeat_path.read_text(encoding="utf-8")),
                {
                    "pid": 77,
                    "status": "busy",
                    "ts": "2026-06-08T03:10:00+00:00",
                },
            )
            payload = json.loads(
                (root / "captured-runner-payload.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload,
                {
                    "entrypoint": "daemon_heartbeat_write_decision",
                    "heartbeat_path_configured": True,
                    "pid": 77,
                    "status": "busy",
                    "timestamp": "2026-06-08T03:10:00+00:00",
                },
            )

    def test_remove_heartbeat_can_use_typescript_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            ts_runner = self._write_fake_typescript_runner(root)
            self._write_typescript_runner_config(root, ts_runner)
            app_config = self._app_config(root)
            daemon_config = load_daemon_config(
                self._write_daemon_config(root),
                app_config=app_config,
            )
            runner = DaemonRunner(app_config, daemon_config, progress_stream=io.StringIO())
            runner._heartbeat_path = root / "state" / "daemon_heartbeat.json"
            runner._heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            runner._heartbeat_path.write_text("{}", encoding="utf-8")

            runner._remove_heartbeat()

            self.assertFalse(runner._heartbeat_path.exists())
            payload = json.loads(
                (root / "captured-runner-payload.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload,
                {
                    "entrypoint": "daemon_heartbeat_remove_decision",
                    "heartbeat_path_configured": True,
                },
            )

    @unittest.skipUnless(InotifyWatcher.is_available(), "inotify is only available on Linux")
    def test_daemonize_cli_smoke_processes_prompt_via_inotify(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            daemon_config_path = self._write_daemon_config(root, watch_backend="inotify")
            prompt_dir = root / "queue" / "prompts"
            result_dir = root / ".test-home" / ".dormammu" / "results"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            result_dir.mkdir(parents=True, exist_ok=True)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(BACKEND)
            env["HOME"] = str(root / ".test-home")
            stdout_log = (root / "daemonize.stdout.log").open("w+", encoding="utf-8")
            stderr_log = (root / "daemonize.stderr.log").open("w+", encoding="utf-8")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "dormammu",
                    "daemonize",
                    "--verbose",
                    "--repo-root",
                    str(root),
                    "--config",
                    str(daemon_config_path),
                ],
                cwd=root,
                env=env,
                stdout=stdout_log,
                stderr=stderr_log,
            )

            try:
                self._wait_for_log_text(root / "daemonize.stderr.log", "watcher: inotify")
                prompt_path = prompt_dir / "001-smoke.md"
                prompt_path.write_text("Smoke prompt\n", encoding="utf-8")
                result_path = result_dir / "001-smoke_RESULT.md"

                # This smoke path exercises the full daemon contract, including
                # refine/plan prelude, the supervised developer loop, supervisor
                # verification, and CLI-authored result reporting. Give it a
                # bounded but realistic timeout so normal runtime latency does
                # not masquerade as an inotify failure.
                deadline = time.time() + 20
                while time.time() < deadline and not result_path.exists():
                    time.sleep(0.1)
                self.assertTrue(result_path.exists(), "daemonize did not produce a result report in time")

                deadline = time.time() + 20
                while time.time() < deadline:
                    result_text = result_path.read_text(encoding="utf-8")
                    if "Status: `completed`" in result_text:
                        break
                    time.sleep(0.1)
                else:
                    self.fail("daemonize did not complete the prompt in time")

                self.assertFalse(prompt_path.exists())
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                stdout_log.close()
                stderr_log.close()

    @unittest.skipUnless(os.name == "posix", "SIGTERM smoke test requires POSIX signals")
    def test_daemonize_exits_promptly_on_sigterm_during_active_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            sleepy_cli = self._write_sleepy_loop_cli(root, sleep_seconds=30)
            self._write_active_cli_config(root, sleepy_cli)
            daemon_config_path = self._write_daemon_config(root, watch_backend="polling")
            prompt_dir = root / "queue" / "prompts"
            result_dir = root / ".test-home" / ".dormammu" / "results"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            result_dir.mkdir(parents=True, exist_ok=True)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(BACKEND)
            env["HOME"] = str(root / ".test-home")
            env["DORMAMMU_SESSIONS_DIR"] = str(root / "sessions")
            stdout_log = (root / "daemonize.stdout.log").open("w+", encoding="utf-8")
            stderr_log = (root / "daemonize.stderr.log").open("w+", encoding="utf-8")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "dormammu",
                    "daemonize",
                    "--verbose",
                    "--repo-root",
                    str(root),
                    "--config",
                    str(daemon_config_path),
                ],
                cwd=root,
                env=env,
                stdout=stdout_log,
                stderr=stderr_log,
            )

            prompt_path = prompt_dir / "001-interrupt.md"
            prompt_path.write_text("Create hello.txt and finish.\n", encoding="utf-8")

            try:
                self._wait_for_log_text(root / "daemonize.stderr.log", "WORKER::started")
                started = time.monotonic()
                process.terminate()
                process.wait(timeout=5)
                elapsed = time.monotonic() - started

                self.assertLess(
                    elapsed,
                    5,
                    f"daemonize did not exit promptly after SIGTERM ({elapsed:.2f}s)",
                )
                self.assertEqual(process.returncode, 130)
                self.assertTrue(prompt_path.exists(), "Interrupted prompt should remain for retry")
                self.assertFalse(
                    (result_dir / "001-interrupt_RESULT.md").exists(),
                    "Interrupted prompt should not be finalized as a result report",
                )

                stderr_text = (root / "daemonize.stderr.log").read_text(encoding="utf-8")
                self.assertIn("daemonize: received SIGTERM", stderr_text)
                self.assertIn("WORKER::got-signal::15", stderr_text)
                self.assertIn("daemonize interrupted", stderr_text)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                stdout_log.close()
                stderr_log.close()

    def test_daemonize_keeps_running_when_result_report_cli_output_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_invalid_result_report_loop_cli(root)
            self._write_active_cli_config(root, loop_cli)
            daemon_config_path = self._write_daemon_config(root, watch_backend="polling")
            prompt_dir = root / "queue" / "prompts"
            result_dir = root / ".test-home" / ".dormammu" / "results"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            result_dir.mkdir(parents=True, exist_ok=True)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(BACKEND)
            env["HOME"] = str(root / ".test-home")
            env["DORMAMMU_SESSIONS_DIR"] = str(root / "sessions")
            stdout_log = (root / "daemonize.stdout.log").open("w+", encoding="utf-8")
            stderr_log = (root / "daemonize.stderr.log").open("w+", encoding="utf-8")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "dormammu",
                    "daemonize",
                    "--repo-root",
                    str(root),
                    "--config",
                    str(daemon_config_path),
                ],
                cwd=root,
                env=env,
                stdout=stdout_log,
                stderr=stderr_log,
            )

            try:
                self._wait_for_log_text(root / "daemonize.stderr.log", "watcher: polling")

                first_prompt = prompt_dir / "001-first.md"
                first_prompt.write_text("First prompt\n", encoding="utf-8")
                first_result = result_dir / "001-first_RESULT.md"
                deadline = time.time() + 10
                while time.time() < deadline and not first_result.exists():
                    time.sleep(0.1)
                self.assertTrue(first_result.exists(), "daemonize did not write the first fallback result report in time")
                self.assertIsNone(process.poll(), "daemonize exited after the first prompt")

                second_prompt = prompt_dir / "002-second.md"
                second_prompt.write_text("Second prompt\n", encoding="utf-8")
                second_result = result_dir / "002-second_RESULT.md"
                deadline = time.time() + 10
                while time.time() < deadline and not second_result.exists():
                    time.sleep(0.1)
                self.assertTrue(second_result.exists(), "daemonize did not process the second prompt after fallback")
                self.assertIsNone(process.poll(), "daemonize exited before the second prompt completed")

                first_result_text = first_result.read_text(encoding="utf-8")
                self.assertIn("Configured CLI result report authoring failed", first_result_text)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                stdout_log.close()
                stderr_log.close()

    def _seed_repo(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")

    @staticmethod
    def _app_config(root: Path) -> AppConfig:
        env = dict(os.environ)
        env["HOME"] = str(root / ".test-home")
        env["DORMAMMU_SESSIONS_DIR"] = str(root / "sessions")
        return AppConfig.load(repo_root=root, env=env)

    def _write_active_cli_config(self, root: Path, cli_path: Path) -> None:
        (root / "dormammu.json").write_text(
            json.dumps({"active_agent_cli": str(cli_path)}, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def _write_typescript_runner_config(
        self,
        root: Path,
        runner_cli: Path,
        *,
        active_agent_cli: Path | None = None,
    ) -> None:
        payload = {"typescript_agent_runner_cli": str(runner_cli)}
        if active_agent_cli is not None:
            payload["active_agent_cli"] = str(active_agent_cli)
        (root / "dormammu.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=True)
            + "\n",
            encoding="utf-8",
        )

    def _write_fake_typescript_runner(self, root: Path) -> Path:
        script = root / "ts-runner"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import json
                import re
                from pathlib import Path

                ROOT = Path({str(root)!r})
                payload = json.loads(__import__("sys").stdin.read())
                (ROOT / "captured-runner-payload.json").write_text(
                    json.dumps(payload, indent=2, ensure_ascii=True) + "\\n",
                    encoding="utf-8",
                )
                with (ROOT / "captured-runner-payloads.jsonl").open(
                    "a",
                    encoding="utf-8",
                ) as stream:
                    stream.write(json.dumps(payload, ensure_ascii=True) + "\\n")
                if payload.get("entrypoint") == "daemon_goal_source_decision":
                    match = re.search(
                        r"^<!--\\s*dormammu:goal_source=([^\\s>]+)\\s*-->",
                        payload["prompt_text"],
                        re.MULTILINE,
                    )
                    raw_path = match.group(1).strip() if match else ""
                    print(json.dumps({{
                        "entrypoint": "daemon_goal_source_decision",
                        "goalSourcePath": raw_path or None,
                        "reason": (
                            "goal_source_found"
                            if raw_path
                            else "goal_source_missing"
                        ),
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_pending_decision":
                    ready = [
                        item
                        for item in payload["ready_prompt_paths"]
                        if isinstance(item, str) and item
                    ]
                    if ready:
                        print(json.dumps({{
                            "entrypoint": "daemon_pending_decision",
                            "action": "process",
                            "promptPath": ready[0],
                            "queuedPromptNames": [
                                Path(item).name for item in ready[1:]
                            ],
                            "retryAfterSeconds": None,
                            "reason": "fake_ready_prompt_available",
                        }}, ensure_ascii=True))
                    elif (
                        payload["processed_count"] == 0
                        and payload.get("retry_after_seconds") is not None
                    ):
                        print(json.dumps({{
                            "entrypoint": "daemon_pending_decision",
                            "action": "wait",
                            "promptPath": None,
                            "queuedPromptNames": [],
                            "retryAfterSeconds": payload["retry_after_seconds"],
                            "reason": "fake_settle_window_pending",
                        }}, ensure_ascii=True))
                    else:
                        print(json.dumps({{
                            "entrypoint": "daemon_pending_decision",
                            "action": "idle",
                            "promptPath": None,
                            "queuedPromptNames": [],
                            "retryAfterSeconds": None,
                            "reason": "fake_no_ready_prompts",
                        }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_prompt_lifecycle_decision":
                    if payload["prompt_exists"]:
                        response = {{
                            "entrypoint": "daemon_prompt_lifecycle_decision",
                            "action": "process",
                            "status": "processing",
                            "promptPath": payload["prompt_path"],
                            "resultPath": payload["result_path"],
                            "removeExistingResult": True,
                            "errorMessage": None,
                            "reason": "fake_prompt_ready",
                        }}
                    else:
                        response = {{
                            "entrypoint": "daemon_prompt_lifecycle_decision",
                            "action": "skip",
                            "status": "skipped",
                            "promptPath": payload["prompt_path"],
                            "resultPath": payload["result_path"],
                            "removeExistingResult": False,
                            "errorMessage": (
                                "Prompt file was deleted before processing."
                            ),
                            "reason": "fake_prompt_missing",
                        }}
                    print(json.dumps(response, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_prompt_path_decision":
                    prompt_name = Path(payload["prompt_path"]).name
                    prompt_stem = (
                        prompt_name.rsplit(".", 1)[0]
                        if "." in prompt_name and not prompt_name.startswith(".")
                        else prompt_name
                    )
                    result_root = Path(payload["result_path_root"])
                    print(json.dumps({{
                        "entrypoint": "daemon_prompt_path_decision",
                        "promptStem": prompt_stem,
                        "resultPath": str(result_root / (prompt_stem + "_RESULT.md")),
                        "progressLogPath": str(
                            result_root.parent
                            / "progress"
                            / (prompt_stem + "_progress.log")
                        ),
                        "reason": "prompt_paths_projected",
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_existing_result_decision":
                    status = (
                        (payload.get("existing_result_status") or "").strip()
                        or None
                    )
                    should_remove = (
                        bool(payload.get("result_exists"))
                        and status == "completed"
                    )
                    print(json.dumps({{
                        "entrypoint": "daemon_existing_result_decision",
                        "action": "remove" if should_remove else "keep",
                        "removeExistingResult": should_remove,
                        "promptPath": payload["prompt_path"],
                        "resultPath": payload["result_path"],
                        "existingResultStatus": status,
                        "reason": (
                            "fake_completed_result_reprocess"
                            if should_remove
                            else "fake_existing_result_keep"
                        ),
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_result_status_decision":
                    status = None
                    for line in payload.get("result_text", "").splitlines():
                        prefix = "- Status: `"
                        if line.startswith(prefix) and line.endswith("`"):
                            raw_status = line[len(prefix):-1]
                            if raw_status:
                                status = raw_status.strip()
                                break
                    print(json.dumps({{
                        "entrypoint": "daemon_result_status_decision",
                        "status": status,
                        "reason": (
                            "status_line_found"
                            if status is not None
                            else "status_line_missing"
                        ),
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_prompt_settle_decision":
                    settle_seconds = max(float(payload["settle_seconds"]), 0.0)
                    age_seconds = max(float(payload["age_seconds"]), 0.0)
                    remaining = max(settle_seconds - age_seconds, 0.0)
                    should_defer = settle_seconds > 0 and remaining > 0
                    print(json.dumps({{
                        "entrypoint": "daemon_prompt_settle_decision",
                        "action": "defer" if should_defer else "ready",
                        "promptPath": payload["prompt_path"],
                        "retryAfterSeconds": remaining if should_defer else None,
                        "reason": (
                            "fake_settle_window_pending"
                            if should_defer
                            else "fake_settle_window_elapsed"
                        ),
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_queue_file_decision":
                    if payload["in_progress"]:
                        action = "skip"
                        reason = "prompt_in_progress"
                    elif not payload["prompt_candidate"]:
                        action = "skip"
                        reason = "not_prompt_candidate"
                    else:
                        action = "inspect"
                        reason = "prompt_ready_for_inspection"
                    print(json.dumps({{
                        "entrypoint": "daemon_queue_file_decision",
                        "action": action,
                        "promptPath": payload["prompt_path"],
                        "reason": reason,
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_result_report_decision":
                    run_id = (
                        (payload.get("daemon_run_id") or "").strip()
                        or (payload.get("latest_run_id") or "").strip()
                        or None
                    )
                    session_id = (payload.get("session_id") or "").strip() or None
                    print(json.dumps({{
                        "entrypoint": "daemon_result_report_decision",
                        "action": "publish",
                        "writeReport": True,
                        "removePrompt": payload["prompt_exists"],
                        "promptPath": payload["prompt_path"],
                        "resultPath": payload["result_path"],
                        "artifactKind": "result_report",
                        "artifactLabel": "result_report",
                        "contentType": "text/markdown",
                        "runId": run_id,
                        "role": "daemon",
                        "stageName": "daemon",
                        "sessionId": session_id,
                        "reason": (
                            "fake_publish_and_remove_prompt"
                            if payload["prompt_exists"]
                            else "fake_publish_without_prompt"
                        ),
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_result_artifact_ref_decision":
                    if not payload["result_exists"]:
                        print(json.dumps({{
                            "entrypoint": "daemon_result_artifact_ref_decision",
                            "action": "skip",
                            "artifactRef": None,
                            "reason": "result_report_missing",
                        }}, ensure_ascii=True))
                        raise SystemExit(0)
                    run_id = (
                        (payload.get("daemon_run_id") or "").strip()
                        or (payload.get("latest_run_id") or "").strip()
                        or None
                    )
                    session_id = (payload.get("session_id") or "").strip() or None
                    print(json.dumps({{
                        "entrypoint": "daemon_result_artifact_ref_decision",
                        "action": "reference",
                        "artifactRef": {{
                            "kind": "result_report",
                            "path": payload["result_path"],
                            "label": "result_report",
                            "contentType": "text/markdown",
                            "createdAt": payload.get("created_at"),
                            "runId": run_id,
                            "role": "daemon",
                            "stageName": "daemon",
                            "sessionId": session_id,
                        }},
                        "reason": "result_report_referenced",
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_roadmap_phase_decision":
                    phase_id = "phase_4"
                    reason = "default_phase_selected"
                    for candidate in payload.get("active_phase_ids", []):
                        if isinstance(candidate, str) and candidate.strip():
                            phase_id = candidate
                            reason = "active_phase_selected"
                            break
                    print(json.dumps({{
                        "entrypoint": "daemon_roadmap_phase_decision",
                        "expectedRoadmapPhaseId": phase_id,
                        "reason": reason,
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_run_finished_decision":
                    def non_negative_int_or_none(value):
                        if value is None:
                            return None
                        return max(0, int(value))

                    print(json.dumps({{
                        "entrypoint": "daemon_run_finished_decision",
                        "source": "daemon_runner",
                        "runEntrypoint": "DaemonRunner._process_prompt",
                        "attemptsCompleted": non_negative_int_or_none(
                            payload.get("attempts_completed")
                        ),
                        "retriesUsed": non_negative_int_or_none(
                            payload.get("retries_used")
                        ),
                        "supervisorVerdict": (
                            (payload.get("supervisor_verdict") or "").strip()
                            or None
                        ),
                        "outcome": (
                            (payload.get("outcome") or "").strip()
                            or "unknown"
                        ),
                        "error": (
                            (payload.get("error") or "").strip()
                            or None
                        ),
                        "reason": "fake_daemon_run_finished",
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_terminal_error_decision":
                    status = (payload.get("status") or "").strip() or "unknown"
                    next_pending_task = (
                        (payload.get("next_pending_task") or "").strip()
                        or None
                    )
                    if status == "failed":
                        suffix = (
                            " Next pending PLAN task: "
                            + next_pending_task
                            + "."
                            if next_pending_task
                            else ""
                        )
                        message = (
                            "Loop retry budget was exhausted before PLAN.md "
                            "completed."
                            + suffix
                        )
                        reason = "retry_budget_exhausted"
                    elif status == "blocked":
                        message = (
                            "Loop stopped because the configured coding-agent "
                            "CLIs were blocked."
                        )
                        reason = "agent_cli_blocked"
                    elif status == "manual_review_needed":
                        message = "Loop stopped because manual review is required."
                        reason = "manual_review_needed"
                    else:
                        message = (
                            "Loop finished with terminal status: "
                            + status
                            + "."
                        )
                        reason = "terminal_status_fallback"
                    print(json.dumps({{
                        "entrypoint": "daemon_terminal_error_decision",
                        "status": status,
                        "nextPendingTask": next_pending_task,
                        "message": message,
                        "reason": reason,
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_terminal_status_decision":
                    status = (payload.get("status") or "").strip() or "unknown"
                    plan_all_completed = payload.get("plan_all_completed")
                    has_clean_evidence = bool(
                        payload.get("has_clean_terminal_stage_evidence")
                    )
                    next_pending_task = (
                        (payload.get("next_pending_task") or "").strip()
                        or None
                    )
                    if status == "completed":
                        if plan_all_completed is True:
                            response = {{
                                "status": status,
                                "error": None,
                                "preserveCompleted": False,
                                "reason": "plan_complete",
                            }}
                        elif has_clean_evidence:
                            response = {{
                                "status": status,
                                "error": None,
                                "preserveCompleted": True,
                                "reason": "clean_terminal_stage_evidence",
                            }}
                        else:
                            response = {{
                                "status": "failed",
                                "error": (
                                    "Loop returned completed but session "
                                    "PLAN.md is not fully complete."
                                ),
                                "preserveCompleted": False,
                                "reason": "completed_plan_incomplete",
                            }}
                    elif status == "failed":
                        suffix = (
                            " Next pending PLAN task: "
                            + next_pending_task
                            + "."
                            if next_pending_task
                            else ""
                        )
                        response = {{
                            "status": status,
                            "error": (
                                "Loop retry budget was exhausted before "
                                "PLAN.md completed."
                                + suffix
                            ),
                            "preserveCompleted": False,
                            "reason": "terminal_error_status",
                        }}
                    elif status == "blocked":
                        response = {{
                            "status": status,
                            "error": (
                                "Loop stopped because the configured "
                                "coding-agent CLIs were blocked."
                            ),
                            "preserveCompleted": False,
                            "reason": "terminal_error_status",
                        }}
                    elif status == "manual_review_needed":
                        response = {{
                            "status": status,
                            "error": "Loop stopped because manual review is required.",
                            "preserveCompleted": False,
                            "reason": "terminal_error_status",
                        }}
                    else:
                        response = {{
                            "status": status,
                            "error": (
                                "Loop finished with terminal status: "
                                + status
                                + "."
                            ),
                            "preserveCompleted": False,
                            "reason": "terminal_error_status",
                        }}
                    response["entrypoint"] = "daemon_terminal_status_decision"
                    print(json.dumps(response, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_prompt_route_decision":
                    if payload["has_agents_config"]:
                        action = "configured_pipeline"
                        response = {{
                            "runner": "pipeline",
                            "requiresAgentCli": False,
                            "runRefineAndPlanPrelude": False,
                            "enablePlanEvaluator": False,
                            "useGoalsEvaluatorConfig": payload["has_goal_file"],
                            "reason": "fake_configured_pipeline",
                        }}
                    elif payload["request_class"] == "direct_response":
                        action = "direct_pipeline"
                        response = {{
                            "runner": "pipeline",
                            "requiresAgentCli": False,
                            "runRefineAndPlanPrelude": False,
                            "enablePlanEvaluator": False,
                            "useGoalsEvaluatorConfig": False,
                            "reason": "fake_direct_pipeline",
                        }}
                    elif payload["request_class"] == "planning_only":
                        action = "planning_pipeline"
                        response = {{
                            "runner": "pipeline",
                            "requiresAgentCli": True,
                            "runRefineAndPlanPrelude": False,
                            "enablePlanEvaluator": False,
                            "useGoalsEvaluatorConfig": False,
                            "reason": "fake_planning_pipeline",
                        }}
                    else:
                        action = "prelude_then_loop"
                        response = {{
                            "runner": "loop",
                            "requiresAgentCli": True,
                            "runRefineAndPlanPrelude": True,
                            "enablePlanEvaluator": payload["has_goal_file"],
                            "useGoalsEvaluatorConfig": False,
                            "reason": "fake_prelude_then_loop",
                        }}
                    response.update({{
                        "entrypoint": "daemon_prompt_route_decision",
                        "action": action,
                    }})
                    print(json.dumps(response, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_loop_iteration_decision":
                    heartbeat_status = (
                        "busy" if payload["in_progress_count"] > 0 else "idle"
                    )
                    if payload["shutdown_requested"]:
                        action = "stop"
                        wait = False
                        reason = "fake_shutdown_requested"
                    elif payload["processed_count"] == 0:
                        action = "wait"
                        wait = True
                        reason = "fake_no_prompt_processed"
                    else:
                        action = "continue"
                        wait = False
                        reason = "fake_prompt_processed"
                    print(json.dumps({{
                        "entrypoint": "daemon_loop_iteration_decision",
                        "action": action,
                        "heartbeatStatus": heartbeat_status,
                        "waitForChanges": wait,
                        "reason": reason,
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_startup_decision":
                    print(json.dumps({{
                        "entrypoint": "daemon_startup_decision",
                        "action": "start",
                        "initialHeartbeatStatus": "idle",
                        "startGoalsScheduler": payload["goals_scheduler_configured"],
                        "triggerGoalsScheduler": payload["goals_scheduler_configured"],
                        "startAutonomousScheduler": (
                            payload["autonomous_scheduler_configured"]
                        ),
                        "triggerAutonomousScheduler": (
                            payload["autonomous_scheduler_configured"]
                        ),
                        "reason": "fake_daemon_startup",
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_startup_banner_decision":
                    allowed_extensions = payload.get("allowed_extensions") or []
                    extension_text = (
                        ",".join(allowed_extensions)
                        if allowed_extensions
                        else "any"
                    )
                    lines = [
                        "=== dormammu daemonize ===",
                        "repo root: " + payload["repo_root"],
                        "daemon config: " + payload["config_path"],
                        "prompt path: " + payload["prompt_path"],
                        "result path: " + payload["result_path"],
                        (
                            "watcher: "
                            + payload["watcher_backend"]
                            + " (requested="
                            + payload["requested_watcher_backend"]
                            + ", poll_interval="
                            + str(payload["poll_interval_seconds"])
                            + "s, settle="
                            + str(payload["settle_seconds"])
                            + "s)"
                        ),
                        (
                            "prompt detection: hidden_files="
                            + (
                                "ignore"
                                if payload["ignore_hidden_files"]
                                else "include"
                            )
                            + ", extensions="
                            + extension_text
                            + ", replace_completed_result_on_requeued_prompt=yes, "
                            + "order=numeric-prefix -> alpha-prefix -> remaining-name"
                        ),
                        (
                            "prompt lifecycle: each accepted prompt reuses the "
                            "dormammu run loop and writes its result only after "
                            "the loop reaches a terminal outcome"
                        ),
                    ]
                    if payload.get("goals_path"):
                        lines.append(
                            "goals: "
                            + payload["goals_path"]
                            + " (interval="
                            + str(payload.get("goals_interval_minutes"))
                            + "m, watching for .md files)"
                        )
                    else:
                        lines.append("goals: disabled")
                    if payload["autonomous_enabled"]:
                        lines.append(
                            "autonomous: enabled (interval="
                            + str(payload.get("autonomous_interval_minutes"))
                            + "m, focus="
                            + str(payload.get("autonomous_focus"))
                            + ", max_queued="
                            + str(payload.get("autonomous_max_queued_tasks"))
                            + ")"
                        )
                    else:
                        lines.append("autonomous: disabled")
                    print(json.dumps({{
                        "entrypoint": "daemon_startup_banner_decision",
                        "allowedExtensionsDescription": extension_text,
                        "lines": lines,
                        "reason": "startup_banner_projected",
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_shutdown_decision":
                    print(json.dumps({{
                        "entrypoint": "daemon_shutdown_decision",
                        "action": "shutdown",
                        "stopGoalsScheduler": payload["goals_scheduler_configured"],
                        "stopAutonomousScheduler": (
                            payload["autonomous_scheduler_configured"]
                        ),
                        "closeWatcher": True,
                        "removeHeartbeat": True,
                        "closeProgressLog": payload["progress_log_active"],
                        "reason": "fake_daemon_shutdown",
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_instance_lock_decision":
                    if not payload["fcntl_available"]:
                        response = {{
                            "entrypoint": "daemon_instance_lock_decision",
                            "action": "skip",
                            "writePidFile": False,
                            "errorMessage": None,
                            "reason": "fake_fcntl_unavailable",
                        }}
                    elif payload["lock_acquired"]:
                        response = {{
                            "entrypoint": "daemon_instance_lock_decision",
                            "action": "hold",
                            "writePidFile": True,
                            "errorMessage": None,
                            "reason": "fake_lock_acquired",
                        }}
                    else:
                        existing = (payload.get("existing_pid") or "").strip()
                        pid_info = (
                            f" (existing daemon PID: {{existing}})"
                            if existing
                            else ""
                        )
                        response = {{
                            "entrypoint": "daemon_instance_lock_decision",
                            "action": "reject",
                            "writePidFile": False,
                            "errorMessage": (
                                "Another dormammu daemon is already running against "
                                f"{{payload['prompt_path']}}{{pid_info}}.\\n"
                                "Stop it first or use a different prompt_path."
                            ),
                            "reason": "fake_lock_busy",
                        }}
                    print(json.dumps(response, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_instance_unlock_decision":
                    should_release = payload["fcntl_available"] and payload["lock_held"]
                    print(json.dumps({{
                        "entrypoint": "daemon_instance_unlock_decision",
                        "action": "release" if should_release else "skip",
                        "unlockFcntl": should_release,
                        "closeLockFile": should_release,
                        "clearPidLockFile": should_release,
                        "removePidFile": should_release,
                        "reason": (
                            "fake_lock_release"
                            if should_release
                            else "fake_lock_skip"
                        ),
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_heartbeat_write_decision":
                    if payload["heartbeat_path_configured"]:
                        response = {{
                            "entrypoint": "daemon_heartbeat_write_decision",
                            "action": "write",
                            "ensureParent": True,
                            "heartbeatPayload": {{
                                "pid": payload["pid"],
                                "status": payload["status"],
                                "ts": payload["timestamp"],
                            }},
                            "reason": "fake_heartbeat_write",
                        }}
                    else:
                        response = {{
                            "entrypoint": "daemon_heartbeat_write_decision",
                            "action": "skip",
                            "ensureParent": False,
                            "heartbeatPayload": None,
                            "reason": "fake_heartbeat_skip",
                        }}
                    print(json.dumps(response, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_heartbeat_remove_decision":
                    print(json.dumps({{
                        "entrypoint": "daemon_heartbeat_remove_decision",
                        "action": (
                            "remove" if payload["heartbeat_path_configured"] else "skip"
                        ),
                        "removeHeartbeat": payload["heartbeat_path_configured"],
                        "reason": "fake_heartbeat_remove",
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_watcher_backend_decision":
                    requested = payload["requested_backend"]
                    inotify_available = payload["inotify_available"]
                    if requested == "polling":
                        response = {{
                            "entrypoint": "daemon_watcher_backend_decision",
                            "action": "use",
                            "backend": "polling",
                            "errorMessage": None,
                            "reason": "fake_polling_requested",
                        }}
                    elif requested == "inotify" and not inotify_available:
                        response = {{
                            "entrypoint": "daemon_watcher_backend_decision",
                            "action": "error",
                            "backend": None,
                            "errorMessage": (
                                "Inotify backend is not available on this platform."
                            ),
                            "reason": "fake_inotify_unavailable",
                        }}
                    else:
                        response = {{
                            "entrypoint": "daemon_watcher_backend_decision",
                            "action": "use",
                            "backend": (
                                "inotify"
                                if requested == "inotify" or inotify_available
                                else "polling"
                            ),
                            "errorMessage": None,
                            "reason": "fake_watcher_backend",
                        }}
                    print(json.dumps(response, ensure_ascii=True))
                    raise SystemExit(0)
                if payload.get("entrypoint") == "daemon_watcher_wait_decision":
                    backend = (payload.get("watcher_backend") or "").strip() or "unknown"
                    should_wait = (
                        payload["wait_requested"]
                        and not payload["shutdown_requested"]
                    )
                    print(json.dumps({{
                        "entrypoint": "daemon_watcher_wait_decision",
                        "action": "wait" if should_wait else "skip",
                        "waitForChanges": should_wait,
                        "watcherBackend": backend,
                        "reason": (
                            "fake_wait_requested"
                            if should_wait
                            else "fake_wait_skipped"
                        ),
                    }}, ensure_ascii=True))
                    raise SystemExit(0)
                raise SystemExit(2)
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_daemon_config(self, root: Path, *, watch_backend: str = "polling") -> Path:
        config_path = root / "daemonize.json"
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "prompt_path": "./queue/prompts",
                    "result_path": "./queue/results",
                    "watch": {
                        "backend": watch_backend,
                        "poll_interval_seconds": 1,
                        "settle_seconds": 0,
                    },
                    "queue": {
                        "allowed_extensions": [".md"],
                        "ignore_hidden_files": True,
                    },
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return config_path

    def _write_loop_cli(
        self,
        root: Path,
        *,
        success_attempt: int,
        plan_completion_attempt: int | None = None,
        name: str = "fake-loop-agent",
        mark_root_plan: bool = False,
    ) -> Path:
        script = root / name
        effective_plan_completion_attempt = success_attempt if plan_completion_attempt is None else plan_completion_attempt
        marker_path = root / f"{name}-used.txt"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import json, os
                import sys

                ROOT = Path({str(root)!r})
                SUCCESS_ATTEMPT = {success_attempt}
                PLAN_COMPLETION_ATTEMPT = {effective_plan_completion_attempt}
                MARK_ROOT_PLAN = {mark_root_plan!r}
                COUNTER_PATH = ROOT / ".attempt-count"
                TARGET_PATH = ROOT / "done.txt"
                _base_dev_dir = os.environ.get("DORMAMMU_BASE_DEV_DIR", "").strip()
                BASE_DEV_DIR = Path(_base_dev_dir) if _base_dev_dir else ROOT / ".dev"
                SESSION_PATH = BASE_DEV_DIR / "session.json"
                MARKER_PATH = ROOT / {marker_path.name!r}
                _sdir = os.environ.get("DORMAMMU_SESSIONS_DIR", "").strip()
                sessions_dir = Path(_sdir) if _sdir else BASE_DEV_DIR / "sessions"

                def is_prelude_prompt(prompt: str) -> bool:
                    return any(
                        marker in prompt
                        for marker in (
                            "You are a requirement refiner.",
                            "You are the requirement refiner.",
                            "You are a planning agent.",
                            "You are the planning agent.",
                            "You are an analyzer agent.",
                        )
                    )

                def is_plan_evaluator_prompt(prompt: str) -> bool:
                    return "mandatory post-plan evaluator checkpoint" in prompt

                def is_result_report_prompt(prompt: str) -> bool:
                    return "Write a deterministic operator-facing Markdown result report." in prompt

                def mark_complete(path: Path) -> None:
                    if not path.exists():
                        return
                    lines = path.read_text(encoding="utf-8").splitlines()
                    rewritten = [
                        line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                        for line in lines
                    ]
                    path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

                def mark_plan_complete() -> None:
                    if MARK_ROOT_PLAN:
                        mark_complete(BASE_DEV_DIR / "PLAN.md")
                        mark_complete(BASE_DEV_DIR / "TASKS.md")
                        return
                    if not SESSION_PATH.exists():
                        return
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    mark_complete(sessions_dir / str(session_id) / "PLAN.md")
                    mark_complete(sessions_dir / str(session_id) / "TASKS.md")

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-loop-agent [--prompt-file PATH]")
                        return 0

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    if is_plan_evaluator_prompt(prompt):
                        print("CHECKPOINT::ok")
                        print("DECISION: PROCEED")
                        return 0

                    if is_result_report_prompt(prompt):
                        print("# CLI Authored Result")
                        print("")
                        if "# Structured Facts" in prompt:
                            print(prompt.split("# Structured Facts", 1)[1].strip())
                        return 0

                    if is_prelude_prompt(prompt):
                        print("PRELUDE::ok")
                        return 0

                    MARKER_PATH.write_text("used\\n", encoding="utf-8")
                    if COUNTER_PATH.exists():
                        attempt = int(COUNTER_PATH.read_text(encoding="utf-8").strip()) + 1
                    else:
                        attempt = 1
                    COUNTER_PATH.write_text(str(attempt), encoding="utf-8")

                    print(f"ATTEMPT::{{attempt}}")
                    if attempt >= SUCCESS_ATTEMPT:
                        TARGET_PATH.write_text("done\\n", encoding="utf-8")
                    if attempt >= PLAN_COMPLETION_ATTEMPT:
                        mark_plan_complete()
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_sleepy_loop_cli(self, root: Path, *, sleep_seconds: int, name: str = "sleepy-loop-agent") -> Path:
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import signal
                import sys
                import time

                ROOT = Path({str(root)!r})

                def is_prelude_prompt(prompt: str) -> bool:
                    return any(
                        marker in prompt
                        for marker in (
                            "You are a requirement refiner.",
                            "You are the requirement refiner.",
                            "You are a planning agent.",
                            "You are the planning agent.",
                            "You are an analyzer agent.",
                        )
                    )

                def is_plan_evaluator_prompt(prompt: str) -> bool:
                    return "mandatory post-plan evaluator checkpoint" in prompt

                def _on_term(signum, frame):
                    print(f"WORKER::got-signal::{{signum}}", flush=True)
                    raise SystemExit(143)

                signal.signal(signal.SIGTERM, _on_term)

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: {name} [--prompt-file PATH]")
                        return 0

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    if is_plan_evaluator_prompt(prompt):
                        print("CHECKPOINT::ok", flush=True)
                        print("DECISION: PROCEED", flush=True)
                        return 0

                    if is_prelude_prompt(prompt):
                        print("PRELUDE::ok", flush=True)
                        return 0

                    print("WORKER::started", flush=True)
                    time.sleep({sleep_seconds})
                    print("WORKER::finished", flush=True)
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_invalid_result_report_loop_cli(self, root: Path, name: str = "broken-result-loop-agent") -> Path:
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import json
                import os
                import sys

                ROOT = Path({str(root)!r})
                COUNTER_PATH = ROOT / ".attempt-count"
                _base_dev_dir = os.environ.get("DORMAMMU_BASE_DEV_DIR", "").strip()
                BASE_DEV_DIR = Path(_base_dev_dir) if _base_dev_dir else ROOT / ".dev"
                SESSION_PATH = BASE_DEV_DIR / "session.json"
                _sdir = os.environ.get("DORMAMMU_SESSIONS_DIR", "").strip()
                sessions_dir = Path(_sdir) if _sdir else BASE_DEV_DIR / "sessions"

                def is_prelude_prompt(prompt: str) -> bool:
                    return any(
                        marker in prompt
                        for marker in (
                            "You are a requirement refiner.",
                            "You are the requirement refiner.",
                            "You are a planning agent.",
                            "You are the planning agent.",
                            "You are an analyzer agent.",
                        )
                    )

                def is_plan_evaluator_prompt(prompt: str) -> bool:
                    return "mandatory post-plan evaluator checkpoint" in prompt

                def is_result_report_prompt(prompt: str) -> bool:
                    return "Write a deterministic operator-facing Markdown result report." in prompt

                def mark_complete(path: Path) -> None:
                    if not path.exists():
                        return
                    lines = path.read_text(encoding="utf-8").splitlines()
                    rewritten = [
                        line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                        for line in lines
                    ]
                    path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

                def mark_plan_complete() -> None:
                    if not SESSION_PATH.exists():
                        return
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    mark_complete(sessions_dir / str(session_id) / "PLAN.md")
                    mark_complete(sessions_dir / str(session_id) / "TASKS.md")

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: {name} [--prompt-file PATH]")
                        return 0

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    if is_plan_evaluator_prompt(prompt):
                        print("CHECKPOINT::ok")
                        print("DECISION: PROCEED")
                        return 0

                    if is_result_report_prompt(prompt):
                        print("# Invalid Result")
                        print("")
                        print("## Summary")
                        print("")
                        print("- Status: `completed`")
                        return 0

                    if is_prelude_prompt(prompt):
                        print("PRELUDE::ok")
                        return 0

                    attempt = int(COUNTER_PATH.read_text(encoding="utf-8").strip()) + 1 if COUNTER_PATH.exists() else 1
                    COUNTER_PATH.write_text(str(attempt), encoding="utf-8")
                    mark_plan_complete()
                    print(f"ATTEMPT::{{attempt}}")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _wait_for_log_text(self, path: Path, pattern: str) -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            if path.exists() and pattern in path.read_text(encoding="utf-8"):
                return
            time.sleep(0.1)
        raise AssertionError(f"Did not observe '{pattern}' in {path}")


if __name__ == "__main__":
    unittest.main()
