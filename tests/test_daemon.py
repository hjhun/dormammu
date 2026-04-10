from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock
import re

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config
from dormammu.daemon.models import DaemonConfig, WatchConfig
from dormammu.daemon.queue import prompt_sort_key
from dormammu.daemon.runner import DaemonRunner
from dormammu.daemon.watchers import EFFECTIVE_POLL_INTERVAL_SECONDS, InotifyWatcher, PollingWatcher, build_watcher
from dormammu.agent import cli_adapter as cli_adapter_module


class DaemonConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    def test_load_daemon_config_resolves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config_path = root / "ops" / "daemon.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            cli_path = root / "bin" / "fake-agent"
            cli_path.parent.mkdir(parents=True, exist_ok=True)
            cli_path.write_text("", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "../queue/prompts",
                        "result_path": "../queue/results",
                        "phases": self._phase_payload("./../bin/fake-agent"),
                    }
                ),
                encoding="utf-8",
            )

            app_config = AppConfig.load(repo_root=root)
            config = load_daemon_config(config_path, app_config=app_config)

            self.assertEqual(config.prompt_path, (root / "queue" / "prompts").resolve())
            self.assertEqual(config.result_path, (root / "queue" / "results").resolve())
            self.assertEqual(config.phases["plan"].agent_cli.path, cli_path.resolve())
            self.assertEqual(config.phases["plan"].skill_name, "planning-agent")
            self.assertTrue(config.phases["plan"].skill_path.exists())

    def test_load_daemon_config_rejects_missing_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config_path = root / "daemon.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "./prompts",
                        "result_path": "./results",
                        "phases": {
                            "plan": {
                                "skill_name": "planning-agent",
                                "agent_cli": {"path": "codex"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            app_config = AppConfig.load(repo_root=root)
            with self.assertRaises(RuntimeError):
                load_daemon_config(config_path, app_config=app_config)

    def test_load_daemon_config_resolves_explicit_skill_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            skill_path = root / "custom-skill.md"
            skill_path.write_text("# Custom Skill\n\nDo the custom thing.\n", encoding="utf-8")
            config_path = root / "daemon.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "./prompts",
                        "result_path": "./results",
                        "phases": self._phase_payload("codex", skill_path=str(skill_path)),
                    }
                ),
                encoding="utf-8",
            )

            app_config = AppConfig.load(repo_root=root)
            config = load_daemon_config(config_path, app_config=app_config)

            self.assertIsNone(config.phases["plan"].skill_name)
            self.assertEqual(config.phases["plan"].skill_path, skill_path.resolve())

    def test_daemonize_codex_defaults_avoid_interactive_approval_when_extra_args_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_codex = self._write_fake_codex_cli(root)
            daemon_config_path = root / "daemon.json"
            daemon_config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "./prompts",
                        "result_path": "./results",
                        "watch": {
                            "backend": "polling",
                            "poll_interval_seconds": 1,
                            "settle_seconds": 0,
                        },
                        "phases": {
                            phase_name: {
                                "skill_name": self._skill_name_for_phase(phase_name),
                                "agent_cli": {
                                    "path": str(fake_codex),
                                    "input_mode": "auto",
                                    "prompt_flag": None,
                                    "extra_args": [],
                                },
                            }
                            for phase_name in (
                                "plan",
                                "design",
                                "develop",
                                "build_and_deploy",
                                "test_and_review",
                                "commit",
                            )
                        },
                    }
                ),
                encoding="utf-8",
            )

            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertTrue((root / "codex-danger.txt").exists())

    def test_daemonize_claude_defaults_avoid_interactive_approval_when_extra_args_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_claude = self._write_fake_claude_cli(root)
            daemon_config_path = root / "daemon.json"
            daemon_config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "./prompts",
                        "result_path": "./results",
                        "watch": {
                            "backend": "polling",
                            "poll_interval_seconds": 1,
                            "settle_seconds": 0,
                        },
                        "phases": {
                            phase_name: {
                                "skill_name": self._skill_name_for_phase(phase_name),
                                "agent_cli": {
                                    "path": str(fake_claude),
                                    "input_mode": "auto",
                                    "prompt_flag": None,
                                    "extra_args": [],
                                },
                            }
                            for phase_name in (
                                "plan",
                                "design",
                                "develop",
                                "build_and_deploy",
                                "test_and_review",
                                "commit",
                            )
                        },
                    }
                ),
                encoding="utf-8",
            )

            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertTrue((root / "claude-print.txt").exists())
            self.assertTrue((root / "claude-danger.txt").exists())

    def _phase_payload(self, cli_path: str, *, skill_path: str | None = None) -> dict[str, object]:
        return {
            phase_name: {
                **(
                    {"skill_path": skill_path}
                    if skill_path is not None
                    else {"skill_name": self._skill_name_for_phase(phase_name)}
                ),
                "agent_cli": {
                    "path": cli_path,
                    "input_mode": "file",
                    "extra_args": [],
                },
            }
            for phase_name in (
                "plan",
                "design",
                "develop",
                "build_and_deploy",
                "test_and_review",
                "commit",
            )
        }

    def _skill_name_for_phase(self, phase_name: str) -> str:
        return {
            "plan": "planning-agent",
            "design": "designing-agent",
            "develop": "developing-agent",
            "build_and_deploy": "building-and-deploying",
            "test_and_review": "testing-and-reviewing",
            "commit": "committing-agent",
        }[phase_name]

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")
        skills_dir = root / "agents" / "skills"
        for name in (
            "planning-agent",
            "designing-agent",
            "developing-agent",
            "building-and-deploying",
            "testing-and-reviewing",
            "committing-agent",
        ):
            skill_dir = skills_dir / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n\nUse {name}.\n", encoding="utf-8")

    def _write_fake_codex_cli(self, root: Path) -> Path:
        script = root / "codex"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys
                from pathlib import Path

                def mark_session_plan_complete() -> None:
                    sessions_dir = Path.cwd() / ".dev" / "sessions"
                    if not sessions_dir.exists():
                        return
                    session_dirs = sorted(path for path in sessions_dir.iterdir() if path.is_dir())
                    if not session_dirs:
                        return
                    (session_dirs[-1] / "PLAN.md").write_text(
                        "# PLAN\\n\\n"
                        "## Prompt-Derived Implementation Plan\\n\\n"
                        "- [O] Phase 1. First prompt\\n\\n"
                        "## Resume Checkpoint\\n\\n"
                        "Resume complete.\\n",
                        encoding="utf-8",
                    )

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        if args[:2] == ["exec", "--help"]:
                            print("Run Codex non-interactively")
                            print("Usage: codex exec [OPTIONS] [PROMPT]")
                            print("  --skip-git-repo-check")
                            return 0
                        print("Usage: codex [OPTIONS] [PROMPT]")
                        print("  codex exec [OPTIONS] [PROMPT]")
                        print("  --dangerously-bypass-approvals-and-sandbox")
                        print("  --skip-git-repo-check")
                        return 0

                    if args and args[0] == "exec":
                        mark_session_plan_complete()
                        dangerous = "--dangerously-bypass-approvals-and-sandbox" in args
                        if dangerous:
                            Path({str(root / "codex-danger.txt")!r}).write_text("danger\\n", encoding="utf-8")
                        print(f"MODE::{{'dangerous' if dangerous else 'interactive'}}")
                        return 0

                    return 1

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_fake_claude_cli(self, root: Path) -> Path:
        script = root / "claude"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys
                from pathlib import Path

                def mark_session_plan_complete() -> None:
                    sessions_dir = Path.cwd() / ".dev" / "sessions"
                    if not sessions_dir.exists():
                        return
                    session_dirs = sorted(path for path in sessions_dir.iterdir() if path.is_dir())
                    if not session_dirs:
                        return
                    (session_dirs[-1] / "PLAN.md").write_text(
                        "# PLAN\\n\\n"
                        "## Prompt-Derived Implementation Plan\\n\\n"
                        "- [O] Phase 1. First prompt\\n\\n"
                        "## Resume Checkpoint\\n\\n"
                        "Resume complete.\\n",
                        encoding="utf-8",
                    )

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("Usage: claude [options] [command] [prompt]")
                        print("  -p, --print")
                        print("  --permission-mode <mode>")
                        print("  --dangerously-skip-permissions")
                        return 0

                    if "--print" not in args:
                        print("missing print mode", file=sys.stderr)
                        return 13
                    Path({str(root / "claude-print.txt")!r}).write_text("print\\n", encoding="utf-8")

                    mode = ""
                    if "--permission-mode" in args:
                        index = args.index("--permission-mode")
                        mode = args[index + 1]
                    elif "--dangerously-skip-permissions" in args:
                        mode = "dangerously-skip-permissions"

                    if mode != "dangerously-skip-permissions":
                        print(f"unexpected mode::{{mode}}", file=sys.stderr)
                        return 14
                    mark_session_plan_complete()
                    Path({str(root / "claude-danger.txt")!r}).write_text(mode + "\\n", encoding="utf-8")

                    prompt = args[-1] if args else ""
                    print(f"PROMPT::{{prompt}}")
                    print(f"MODE::{{mode}}")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script


class DaemonQueueTests(unittest.TestCase):
    def test_prompt_sort_key_orders_numeric_then_alpha_then_plain(self) -> None:
        filenames = [
            "b-task.md",
            "_scratch.md",
            "010-build.md",
            "002-plan.md",
            "A-design.md",
        ]

        ordered = sorted(filenames, key=prompt_sort_key)

        self.assertEqual(
            ordered,
            ["002-plan.md", "010-build.md", "A-design.md", "b-task.md", "_scratch.md"],
        )


@unittest.skipUnless(InotifyWatcher.is_available(), "inotify is only available on Linux")
class InotifyWatcherTests(unittest.TestCase):
    def test_build_watcher_uses_inotify_for_auto_and_explicit_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_dir = Path(tmpdir)
            for backend in ("auto", "inotify"):
                watcher = build_watcher(
                    prompt_dir,
                    WatchConfig(
                        backend=backend,
                        poll_interval_seconds=1,
                        settle_seconds=0,
                    ),
                )
                self.assertIsInstance(watcher, InotifyWatcher)
                self.assertEqual(watcher.backend_name, "inotify")

    def test_wait_for_changes_blocks_until_close_write_and_logs_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_dir = Path(tmpdir)
            events: list[str] = []
            watcher = InotifyWatcher(
                prompt_dir,
                WatchConfig(
                    backend="inotify",
                    poll_interval_seconds=60,
                    settle_seconds=0,
                ),
                event_logger=events.append,
            )
            watcher.start()
            try:
                writer_started = threading.Event()

                def writer() -> None:
                    prompt_path = prompt_dir / "001-first.md"
                    with prompt_path.open("w", encoding="utf-8") as handle:
                        writer_started.set()
                        handle.write("First prompt\n")
                        handle.flush()
                        time.sleep(0.2)

                thread = threading.Thread(target=writer, daemon=True)
                start = time.monotonic()
                thread.start()
                self.assertTrue(writer_started.wait(timeout=1.0))
                changed_paths = watcher.wait_for_changes()
                elapsed = time.monotonic() - start
                thread.join(timeout=1.0)

                self.assertGreaterEqual(elapsed, 0.15)
                self.assertEqual(changed_paths, [prompt_dir / "001-first.md"])
                self.assertTrue(any("IN_CLOSE_WRITE" in event for event in events))
                self.assertTrue(any("001-first.md" in event for event in events))
            finally:
                watcher.close()


class PollingWatcherTests(unittest.TestCase):
    def test_build_watcher_uses_polling_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_dir = Path(tmpdir)
            watcher = build_watcher(
                prompt_dir,
                WatchConfig(
                    backend="polling",
                    poll_interval_seconds=1,
                    settle_seconds=0,
                ),
            )
            self.assertIsInstance(watcher, PollingWatcher)
            self.assertEqual(watcher.backend_name, "polling")

    def test_wait_for_changes_uses_configured_poll_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_dir = Path(tmpdir)
            prompt_path = prompt_dir / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            watcher = PollingWatcher(
                prompt_dir,
                WatchConfig(
                    backend="polling",
                    poll_interval_seconds=7,
                    settle_seconds=0,
                ),
            )

            with mock.patch("dormammu.daemon.watchers.time.sleep") as sleep_mock:
                changed_paths = watcher.wait_for_changes()

            sleep_mock.assert_called_once_with(7)
            self.assertEqual(changed_paths, [prompt_path])


class DaemonRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    def test_run_forever_emits_startup_banner_with_detection_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))

            class InterruptingWatcher:
                backend_name = "inotify"

                def start(self) -> None:
                    return None

                def close(self) -> None:
                    return None

                def wait_for_changes(self) -> list[Path]:
                    raise KeyboardInterrupt()

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            runner = DaemonRunner(config, daemon_config, progress_stream=stderr, watcher=InterruptingWatcher())

            with self.assertRaises(KeyboardInterrupt):
                runner.run_forever()

            progress = stderr.getvalue()
            self.assertIn("=== dormammu daemonize ===", progress)
            self.assertIn(f"daemon config: {daemon_config.config_path}", progress)
            self.assertIn(f"prompt path: {daemon_config.prompt_path}", progress)
            self.assertIn("watcher: inotify", progress)
            self.assertIn("prompt detection: hidden_files=ignore, extensions=.md", progress)
            self.assertIn("replace_completed_result_on_requeued_prompt=yes", progress)
            self.assertIn("child cli output: stdout+stderr are mirrored live to parent stderr", progress)

    def test_run_pending_once_processes_existing_prompts_in_sorted_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            (daemon_config.prompt_path / "b-second.md").write_text("Second prompt\n", encoding="utf-8")
            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                runner = DaemonRunner(config, daemon_config)
                first_processed = runner.run_pending_once(watcher_backend="polling")
                second_processed = runner.run_pending_once(watcher_backend="polling")

            self.assertEqual(first_processed, 1)
            self.assertEqual(second_processed, 1)
            first_result = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            second_result = (daemon_config.result_path / "b-second_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", first_result)
            self.assertIn("Status: `completed`", second_result)
            self.assertFalse((daemon_config.prompt_path / "001-first.md").exists())
            self.assertFalse((daemon_config.prompt_path / "b-second.md").exists())
            stderr_text = stderr.getvalue()
            first_detect = "daemon prompt detected: 001-first.md"
            second_detect = "daemon prompt detected: b-second.md"
            self.assertIn(first_detect, stderr_text)
            self.assertIn(second_detect, stderr_text)
            self.assertLess(stderr_text.index(first_detect), stderr_text.index(second_detect))
            self.assertIn("keeping queued prompts pending until the current prompt finishes", stderr_text)

    def test_run_pending_once_creates_a_new_session_for_each_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")
            (daemon_config.prompt_path / "002-second.md").write_text("Second prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            runner = DaemonRunner(config, daemon_config)
            self.assertEqual(runner.run_pending_once(watcher_backend="polling"), 1)
            self.assertEqual(runner.run_pending_once(watcher_backend="polling"), 1)

            first_result = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            second_result = (daemon_config.result_path / "002-second_RESULT.md").read_text(encoding="utf-8")
            first_session_id = self._extract_session_id(first_result)
            second_session_id = self._extract_session_id(second_result)

            self.assertNotEqual(first_session_id, second_session_id)
            self.assertTrue((root / ".dev" / "sessions" / first_session_id / "session.json").exists())
            self.assertTrue((root / ".dev" / "sessions" / second_session_id / "session.json").exists())

    def test_run_pending_once_logs_prompt_detection_and_phase_launch_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            processed = DaemonRunner(config, daemon_config, progress_stream=stderr).run_pending_once(
                watcher_backend="inotify"
            )

            self.assertEqual(processed, 1)
            progress = stderr.getvalue()
            self.assertIn("daemon prompt detected: 001-first.md", progress)
            self.assertIn("sort_key=(0, 1, '001-first.md')", progress)
            self.assertIn("daemon phase plan: launching CLI", progress)
            self.assertIn("prompt_mode=file", progress)
            self.assertIn("command:", progress)
            self.assertIn("stdout artifact:", progress)
            self.assertIn("stderr artifact:", progress)
            self.assertIn("daemon phase commit: exit_code=0", progress)

    def test_run_pending_once_retries_after_settle_window_without_new_watcher_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            daemon_config = DaemonConfig(
                schema_version=daemon_config.schema_version,
                config_path=daemon_config.config_path,
                prompt_path=daemon_config.prompt_path,
                result_path=daemon_config.result_path,
                watch=WatchConfig(
                    backend=daemon_config.watch.backend,
                    poll_interval_seconds=daemon_config.watch.poll_interval_seconds,
                    settle_seconds=2,
                ),
                queue=daemon_config.queue,
                phases=daemon_config.phases,
            )

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            sleep_calls: list[float] = []
            real_time = time.time

            def fake_sleep(seconds: float) -> None:
                sleep_calls.append(seconds)
                os.utime(prompt_path, (real_time() - 5, real_time() - 5))

            with mock.patch("dormammu.daemon.runner.time.sleep", side_effect=fake_sleep):
                processed = DaemonRunner(config, daemon_config, progress_stream=stderr).run_pending_once(
                    watcher_backend="inotify"
                )

            self.assertEqual(processed, 1)
            self.assertTrue(sleep_calls)
            self.assertGreaterEqual(sleep_calls[0], 0)
            self.assertLessEqual(sleep_calls[0], 2.1)
            self.assertIn("deferring 001-first.md until settle window expires", stderr.getvalue())
            self.assertIn("waiting for prompt settle window before retry", stderr.getvalue())
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_preserves_prompt_and_marks_result_interrupted_on_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            class InterruptingRunner(DaemonRunner):
                def _run_phase(self, *args: object, **kwargs: object):  # type: ignore[override]
                    raise KeyboardInterrupt()

            config = AppConfig.load(repo_root=root)
            runner = InterruptingRunner(config, daemon_config)

            with self.assertRaises(KeyboardInterrupt):
                runner.run_pending_once(watcher_backend="polling")

            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `interrupted`", result_text)
            self.assertTrue(prompt_path.exists())

    def test_run_pending_once_reprocesses_prompt_when_existing_completed_result_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            result_path = daemon_config.result_path / "001-first_RESULT.md"
            result_path.write_text(
                "# Result: 001-first.md\n\n## Summary\n\n- Status: `completed`\n",
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            processed = DaemonRunner(config, daemon_config, progress_stream=stderr).run_pending_once(
                watcher_backend="polling"
            )

            self.assertEqual(processed, 1)
            result_text = result_path.read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertIn("Watcher backend: `polling`", result_text)
            self.assertFalse(prompt_path.exists())
            self.assertIn(
                "removing stale completed result for 001-first.md and reprocessing prompt",
                stderr.getvalue(),
            )

    def test_run_pending_once_reprocesses_prompt_when_existing_result_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            (daemon_config.result_path / "001-first_RESULT.md").write_text(
                "# Result: 001-first.md\n\n## Summary\n\n- Status: `failed`\n",
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_writes_in_progress_result_before_phase_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            result_path = root / "queue" / "results" / "001-first_RESULT.md"
            fake_cli = self._write_result_asserting_cli(root)
            daemon_config_path = self._write_daemon_config(
                root,
                fake_cli,
                extra_args_by_phase={
                    phase_name: ["--result-path", str(result_path), "--phase", phase_name]
                    for phase_name in (
                        "plan",
                        "design",
                        "develop",
                        "build_and_deploy",
                        "test_and_review",
                        "commit",
                    )
                },
            )
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = result_path.read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertIn("### commit", result_text)
            self.assertFalse(prompt_path.exists())

    def test_run_pending_once_preserves_prompt_after_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_failing_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `failed`", result_text)
            self.assertTrue(prompt_path.exists())

    def test_run_pending_once_preserves_prompt_when_plan_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_plan_status_cli(root, mark_complete=False)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            processed = DaemonRunner(config, daemon_config, progress_stream=stderr).run_pending_once(
                watcher_backend="polling"
            )

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `waiting_for_plan`", result_text)
            self.assertIn("PLAN complete: `no`", result_text)
            self.assertIn("Next pending PLAN task:", result_text)
            self.assertTrue(prompt_path.exists())
            self.assertIn("waiting for PLAN completion", stderr.getvalue())

    def test_run_pending_once_keeps_later_prompts_pending_until_waiting_plan_prompt_is_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_plan_status_cli(root, mark_complete=False)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            first_prompt = daemon_config.prompt_path / "001-first.md"
            second_prompt = daemon_config.prompt_path / "002-second.md"
            first_prompt.write_text("First prompt\n", encoding="utf-8")
            second_prompt.write_text("Second prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            runner = DaemonRunner(config, daemon_config, progress_stream=stderr)

            self.assertEqual(runner.run_pending_once(watcher_backend="polling"), 1)
            self.assertTrue(first_prompt.exists())
            self.assertTrue(second_prompt.exists())

            blocked_processed = runner.run_pending_once(watcher_backend="polling")
            self.assertEqual(blocked_processed, 0)
            self.assertTrue(second_prompt.exists())
            self.assertIn(
                "keeping 002-second.md pending until 001-first.md is completed",
                stderr.getvalue(),
            )

            first_result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            first_session_id = self._extract_session_id(first_result_text)
            first_plan = root / ".dev" / "sessions" / first_session_id / "PLAN.md"
            first_plan.write_text(
                "# PLAN\n\n"
                "## Prompt-Derived Implementation Plan\n\n"
                "- [O] Phase 1. Session task\n\n"
                "## Resume Checkpoint\n\n"
                "Resume here.\n",
                encoding="utf-8",
            )

            processed_after_release = runner.run_pending_once(watcher_backend="polling")
            self.assertEqual(processed_after_release, 1)
            released_first_result = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            second_result_text = (daemon_config.result_path / "002-second_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", released_first_result)
            self.assertIn("Status: `waiting_for_plan`", second_result_text)
            self.assertFalse(first_prompt.exists())
            self.assertTrue(second_prompt.exists())
            self.assertIn(
                "PLAN is now complete; releasing the queue and marking the prompt completed",
                stderr.getvalue(),
            )

    def test_run_pending_once_removes_prompt_when_plan_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_plan_status_cli(root, mark_complete=True)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 1)
            result_text = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", result_text)
            self.assertIn("PLAN complete: `yes`", result_text)
            self.assertFalse(prompt_path.exists())

    @unittest.skipUnless(InotifyWatcher.is_available(), "inotify is only available on Linux")
    def test_daemonize_cli_smoke_processes_prompt_via_inotify(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli, watch_backend="inotify")
            prompt_dir = root / "queue" / "prompts"
            result_dir = root / "queue" / "results"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            result_dir.mkdir(parents=True, exist_ok=True)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(BACKEND)
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
                deadline = time.time() + 60
                while time.time() < deadline and not result_path.exists():
                    time.sleep(0.1)
                self.assertTrue(result_path.exists(), "daemonize did not produce a result report in time")

                deadline = time.time() + 60
                while time.time() < deadline:
                    result_text = result_path.read_text(encoding="utf-8")
                    if "Status: `completed`" in result_text:
                        break
                    time.sleep(0.1)
                else:
                    self.fail("daemonize did not complete the prompt in time")

                stderr_text = (root / "daemonize.stderr.log").read_text(encoding="utf-8")
                self.assertIn("daemon watcher event: backend=inotify", stderr_text)
                self.assertIn("IN_CLOSE_WRITE", stderr_text)
                self.assertIn("daemon prompt detected: 001-smoke.md", stderr_text)
                self.assertFalse(prompt_path.exists())
            finally:
                process.send_signal(signal.SIGINT)
                process.wait(timeout=10)
                stdout_log.close()
                stderr_log.close()

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")

    def _write_daemon_config(
        self,
        root: Path,
        fake_cli: Path,
        *,
        extra_args_by_phase: dict[str, list[str]] | None = None,
        watch_backend: str = "polling",
    ) -> Path:
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
                    "phases": {
                        phase_name: {
                            "skill_name": self._skill_name_for_phase(phase_name),
                            "agent_cli": {
                                "path": str(fake_cli),
                                "input_mode": "file",
                                "prompt_flag": "--prompt-file",
                                "extra_args": (
                                    extra_args_by_phase.get(phase_name, ["--phase", phase_name])
                                    if extra_args_by_phase is not None
                                    else ["--phase", phase_name]
                                ),
                            },
                        }
                        for phase_name in (
                            "plan",
                            "design",
                            "develop",
                            "build_and_deploy",
                            "test_and_review",
                            "commit",
                        )
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _skill_name_for_phase(self, phase_name: str) -> str:
        return {
            "plan": "planning-agent",
            "design": "designing-agent",
            "develop": "developing-agent",
            "build_and_deploy": "building-and-deploying",
            "test_and_review": "testing-and-reviewing",
            "commit": "committing-agent",
        }[phase_name]

    def _write_fake_cli(self, root: Path) -> Path:
        script = root / "fake-agent"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                def mark_session_plan_complete() -> None:
                    sessions_dir = Path.cwd() / ".dev" / "sessions"
                    if not sessions_dir.exists():
                        return
                    session_dirs = sorted(path for path in sessions_dir.iterdir() if path.is_dir())
                    if not session_dirs:
                        return
                    (session_dirs[-1] / "PLAN.md").write_text(
                        "# PLAN\\n\\n"
                        "## Prompt-Derived Implementation Plan\\n\\n"
                        "- [O] Phase 1. First prompt\\n\\n"
                        "## Resume Checkpoint\\n\\n"
                        "Resume complete.\\n",
                        encoding="utf-8",
                    )

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-agent [--prompt-file PATH] [--phase NAME]")
                        return 0

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    phase = "unknown"
                    if "--phase" in args:
                        index = args.index("--phase")
                        phase = args[index + 1]

                    mark_session_plan_complete()
                    print(f"PHASE::{{phase}}")
                    print(f"PROMPT::{{prompt.strip()}}")
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

    def _extract_session_id(self, result_text: str) -> str:
        match = re.search(r"- Session id: `([^`]+)`", result_text)
        self.assertIsNotNone(match)
        return match.group(1)

    def _write_fake_codex_cli(self, root: Path) -> Path:
        script = root / "codex"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        if args[:2] == ["exec", "--help"]:
                            print("Run Codex non-interactively")
                            print("Usage: codex exec [OPTIONS] [PROMPT]")
                            print("  --skip-git-repo-check")
                            return 0
                        print("Usage: codex [OPTIONS] [PROMPT]")
                        print("  codex exec [OPTIONS] [PROMPT]")
                        print("  --dangerously-bypass-approvals-and-sandbox")
                        print("  --skip-git-repo-check")
                        return 0

                    if args and args[0] == "exec":
                        dangerous = "--dangerously-bypass-approvals-and-sandbox" in args
                        if dangerous:
                            from pathlib import Path
                            Path({str(root / "codex-danger.txt")!r}).write_text("danger\n", encoding="utf-8")
                        print(f"MODE::{{'dangerous' if dangerous else 'interactive'}}")
                        return 0

                    return 1

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_result_asserting_cli(self, root: Path) -> Path:
        script = root / "fake-agent-result-check"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                def mark_session_plan_complete() -> None:
                    sessions_dir = Path.cwd() / ".dev" / "sessions"
                    if not sessions_dir.exists():
                        return
                    session_dirs = sorted(path for path in sessions_dir.iterdir() if path.is_dir())
                    if not session_dirs:
                        return
                    (session_dirs[-1] / "PLAN.md").write_text(
                        "# PLAN\\n\\n"
                        "## Prompt-Derived Implementation Plan\\n\\n"
                        "- [O] Phase 1. First prompt\\n\\n"
                        "## Resume Checkpoint\\n\\n"
                        "Resume complete.\\n",
                        encoding="utf-8",
                    )

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print(
                            "usage: fake-agent-result-check [--prompt-file PATH] "
                            "[--result-path PATH] [--phase NAME]"
                        )
                        return 0

                    result_path = None
                    if "--result-path" in args:
                        index = args.index("--result-path")
                        result_path = Path(args[index + 1])

                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        Path(args[index + 1]).read_text(encoding="utf-8")

                    if result_path is None or not result_path.exists():
                        print("missing result artifact", file=sys.stderr)
                        return 9

                    result_text = result_path.read_text(encoding="utf-8")
                    if "Status: `in_progress`" not in result_text:
                        print("result artifact is not marked in progress", file=sys.stderr)
                        return 10

                    if "Completed at: `not completed`" not in result_text:
                        print("result artifact already looks final", file=sys.stderr)
                        return 11

                    phase = "unknown"
                    if "--phase" in args:
                        index = args.index("--phase")
                        phase = args[index + 1]

                    mark_session_plan_complete()
                    print(f"PHASE::{{phase}}")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_failing_cli(self, root: Path) -> Path:
        script = root / "fake-agent-fail"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-agent-fail [--prompt-file PATH] [--phase NAME]")
                        return 0
                    return 7

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_plan_status_cli(self, root: Path, *, mark_complete: bool) -> Path:
        script = root / ("fake-agent-plan-complete" if mark_complete else "fake-agent-plan-pending")
        replacement = "- [O]" if mark_complete else "- [ ]"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-agent-plan-status [--prompt-file PATH] [--phase NAME]")
                        return 0

                    sessions_dir = Path.cwd() / ".dev" / "sessions"
                    session_dirs = sorted(path for path in sessions_dir.iterdir() if path.is_dir())
                    session_plan = session_dirs[-1] / "PLAN.md"
                    session_plan.write_text(
                        "# PLAN\\n\\n"
                        "## Prompt-Derived Implementation Plan\\n\\n"
                        "{replacement} Phase 1. Session task\\n\\n"
                        "## Resume Checkpoint\\n\\n"
                        "Resume here.\\n",
                        encoding="utf-8",
                    )

                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        Path(args[index + 1]).read_text(encoding="utf-8")

                    phase = "unknown"
                    if "--phase" in args:
                        index = args.index("--phase")
                        phase = args[index + 1]

                    print(f"PHASE::{{phase}}")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script
