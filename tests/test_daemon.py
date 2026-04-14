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
from dormammu.daemon.runner import DaemonRunner, SessionProgressLogStream
from dormammu.daemon.watchers import InotifyWatcher
from dormammu.agent import cli_adapter as cli_adapter_module


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
            self.assertEqual(config.result_path, (root / "queue" / "results").resolve())

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
            first_progress_log = root / "queue" / "progress" / "001-first_progress.log"
            second_progress_log = root / "queue" / "progress" / "002-second_progress.log"

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

    @unittest.skipUnless(InotifyWatcher.is_available(), "inotify is only available on Linux")
    def test_daemonize_cli_smoke_processes_prompt_via_inotify(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            loop_cli = self._write_loop_cli(root, success_attempt=1)
            self._write_active_cli_config(root, loop_cli)
            daemon_config_path = self._write_daemon_config(root, watch_backend="inotify")
            prompt_dir = root / "queue" / "prompts"
            result_dir = root / "queue" / "results"
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

                deadline = time.time() + 10
                while time.time() < deadline and not result_path.exists():
                    time.sleep(0.1)
                self.assertTrue(result_path.exists(), "daemonize did not produce a result report in time")

                deadline = time.time() + 10
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
            result_dir = root / "queue" / "results"
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
                SESSION_PATH = ROOT / ".dev" / "session.json"
                MARKER_PATH = ROOT / {marker_path.name!r}
                _sdir = os.environ.get("DORMAMMU_SESSIONS_DIR", "").strip()
                sessions_dir = Path(_sdir) if _sdir else ROOT / ".dev" / "sessions"

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

                def mark_plan_complete() -> None:
                    if MARK_ROOT_PLAN:
                        plan_path = ROOT / ".dev" / "PLAN.md"
                        if not plan_path.exists():
                            return
                        lines = plan_path.read_text(encoding="utf-8").splitlines()
                        rewritten = [
                            line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                            for line in lines
                        ]
                        plan_path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")
                        return
                    if not SESSION_PATH.exists():
                        return
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    plan_path = sessions_dir / str(session_id) / "PLAN.md"
                    if not plan_path.exists():
                        return
                    lines = plan_path.read_text(encoding="utf-8").splitlines()
                    rewritten = [
                        line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                        for line in lines
                    ]
                    plan_path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

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

    def _wait_for_log_text(self, path: Path, pattern: str) -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            if path.exists() and pattern in path.read_text(encoding="utf-8"):
                return
            time.sleep(0.1)
        raise AssertionError(f"Did not observe '{pattern}' in {path}")


if __name__ == "__main__":
    unittest.main()
