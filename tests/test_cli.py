from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.cli import build_parser, main
from dormammu.agent import cli_adapter as cli_adapter_module
from dormammu.config import AppConfig
from dormammu.interactive_shell import InteractiveShellRunner


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    @staticmethod
    def _root_index_path(config: "AppConfig") -> Path:
        return config.base_dev_dir / "session.json"

    @classmethod
    def _active_session_id(cls, config: "AppConfig") -> str:
        payload = json.loads(cls._root_index_path(config).read_text(encoding="utf-8"))
        return str(payload["active_session_id"])

    def test_top_level_help_mentions_runtime_and_daemon_config_entry_points(self) -> None:
        parser = build_parser()

        help_text = parser.format_help()

        self.assertIn("Config injection:", help_text)
        self.assertIn("./dormammu.json", help_text)
        self.assertIn("$DORMAMMU_CONFIG_PATH", help_text)
        self.assertIn("~/.dormammu/daemonize.json", help_text)
        self.assertIn("dormammu daemonize --config daemonize.json", help_text)

    def test_daemonize_help_mentions_runtime_and_daemon_config_files(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(stdout):
            build_parser().parse_args(["daemonize", "--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("~/.dormammu/daemonize.json", help_text)
        self.assertIn("--config daemonize.json", help_text)
        self.assertIn("./dormammu.json", help_text)
        self.assertIn("$DORMAMMU_CONFIG_PATH", help_text)

    def test_daemonize_uses_default_global_daemon_config_when_flag_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            home = root / ".test-home"
            daemon_config_path = home / ".dormammu" / "daemonize.json"
            daemon_config_path.parent.mkdir(parents=True, exist_ok=True)
            daemon_config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": str(root / "queue" / "prompts"),
                        "result_path": str(root / "queue" / "results"),
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.dict(os.environ, {"HOME": str(home)}, clear=False),
                mock.patch("dormammu._cli_handlers.DaemonRunner.run_forever", return_value=0) as run_forever,
            ):
                exit_code = main(["daemonize", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_forever.call_count, 1)

    def test_show_config_prints_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["show-config", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["repo_root"], str(root))

    def test_show_config_includes_configured_fallback_clis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "fallback_agent_clis": [
                            "claude",
                            {"path": "./bin/aider", "extra_args": ["--yes"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["show-config", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["config_file"], str((root / "dormammu.json").resolve()))
            self.assertEqual(payload["fallback_agent_clis"][0]["path"], "claude")
            self.assertEqual(
                payload["fallback_agent_clis"][1]["path"],
                str((root / "bin" / "aider").resolve()),
            )

    def test_show_config_uses_default_fallback_order_without_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["show-config", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(
                [item["path"] for item in payload["fallback_agent_clis"]],
                ["codex", "claude", "gemini"],
            )

    def test_daemonize_returns_error_when_config_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "daemonize",
                        "--repo-root",
                        str(root),
                        "--config",
                        str(root / "missing-daemon.json"),
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertIn("Daemon config file was not found", stderr.getvalue())

    def test_daemonize_returns_error_when_default_global_config_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            home = root / ".test-home"

            stderr = io.StringIO()
            with mock.patch.dict(os.environ, {"HOME": str(home)}, clear=False), contextlib.redirect_stderr(stderr):
                exit_code = main(["daemonize", "--repo-root", str(root)])

            self.assertEqual(exit_code, 2)
            self.assertIn(str((home / ".dormammu" / "daemonize.json").resolve()), stderr.getvalue())

    def test_init_state_uses_packaged_templates_when_repo_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(["init-state", "--repo-root", str(root)])
                runtime_config = AppConfig.load(repo_root=root)

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(Path(payload["dashboard"]).exists())
            self.assertTrue(Path(payload["tasks"]).exists())
            self.assertIn(str(runtime_config.sessions_dir), payload["dashboard"])

    def test_init_state_records_custom_guidance_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            custom_guidance = root / "docs" / "custom-agent.md"
            custom_guidance.parent.mkdir(parents=True, exist_ok=True)
            custom_guidance.write_text("# Custom agent rules\n\nUse this file.\n", encoding="utf-8")

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "init-state",
                        "--repo-root",
                        str(root),
                        "--guidance-file",
                        str(custom_guidance),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            workflow_state = json.loads(Path(payload["workflow_state"]).read_text(encoding="utf-8"))
            self.assertEqual(
                workflow_state["bootstrap"]["repo_guidance"]["rule_files"],
                ["docs/custom-agent.md"],
            )

    def test_init_state_creates_bootstrap_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "init-state",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "CLI bootstrap",
                        "--roadmap-phase",
                        "phase_1",
                    ]
                )
                runtime_config = AppConfig.load(repo_root=root)

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(Path(payload["dashboard"]).exists())
            self.assertIn(str(runtime_config.sessions_dir), payload["dashboard"])
            self.assertIn(str(runtime_config.sessions_dir), payload["logs_dir"])
            root_index = json.loads(self._root_index_path(runtime_config).read_text(encoding="utf-8"))
            self.assertIn("active_session_id", root_index)

    def test_init_state_creates_gitignore_entry_for_session_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            gitignore_path = root / ".gitignore"
            self.assertFalse(gitignore_path.exists())

            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = main(["init-state", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(gitignore_path.read_text(encoding="utf-8"), ".session\n")

    def test_session_marker_updates_gitignore_without_duplicate_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            gitignore_path = root / ".gitignore"
            gitignore_path.write_text(".venv/\n", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                first_exit = main(["init-state", "--repo-root", str(root)])
                second_exit = main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Next session",
                        "--session-id",
                        "session-two",
                    ]
                )

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(
                gitignore_path.read_text(encoding="utf-8"),
                ".venv/\n.session\n",
            )

    def test_init_state_sets_active_agent_cli_from_highest_priority_available_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            root = temp_root / "repo"
            root.mkdir()
            self._seed_repo(root)
            home_dir = temp_root / "home"
            home_dir.mkdir()
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            claude_path = self._write_path_tool(bin_dir, "claude")
            self._write_path_tool(bin_dir, "gemini")
            self._write_path_tool(bin_dir, "cline")

            stdout = io.StringIO()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "HOME": str(home_dir),
                        "PATH": str(bin_dir),
                        "DORMAMMU_SESSIONS_DIR": str(root / "sessions"),
                    },
                    clear=False,
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(["init-state", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["active_agent_cli"], str(claude_path))
            config_path = home_dir / ".dormammu" / "config"
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config_payload["active_agent_cli"], str(claude_path))

    def test_init_state_updates_existing_active_agent_cli_to_available_higher_priority_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            root = temp_root / "repo"
            root.mkdir()
            self._seed_repo(root)
            home_dir = temp_root / "home"
            home_dir.mkdir()
            config_dir = home_dir / ".dormammu"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "config"
            config_path.write_text(
                json.dumps({"active_agent_cli": "/tmp/missing-cline", "token_exhaustion_patterns": ["quota exceeded"]}),
                encoding="utf-8",
            )
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            codex_path = self._write_path_tool(bin_dir, "codex")
            self._write_path_tool(bin_dir, "cline")

            stdout = io.StringIO()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "HOME": str(home_dir),
                        "PATH": str(bin_dir),
                        "DORMAMMU_SESSIONS_DIR": str(root / "sessions"),
                    },
                    clear=False,
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(["init-state", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["active_agent_cli"], str(codex_path))
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config_payload["active_agent_cli"], str(codex_path))
            self.assertEqual(config_payload["token_exhaustion_patterns"], ["quota exceeded"])

    def test_init_state_prompts_for_bootstrap_inputs_on_first_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch(
                    "builtins.input",
                    side_effect=["Interactive bootstrap goal", "phase_7"],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(["init-state", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            workflow_state = json.loads(Path(payload["workflow_state"]).read_text(encoding="utf-8"))
            self.assertEqual(workflow_state["bootstrap"]["goal"], "Interactive bootstrap goal")
            self.assertEqual(workflow_state["roadmap"]["active_phase_ids"], ["phase_7"])

    def test_start_session_and_sessions_list_manage_archived_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            sessions_dir = root / "sessions"

            start_one_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(start_one_stdout),
            ):
                first_exit = main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "First multi-session workflow",
                        "--session-id",
                        "session-one",
                        "--roadmap-phase",
                        "phase_7",
                    ]
                )

            self.assertEqual(first_exit, 0)
            first_payload = json.loads(start_one_stdout.getvalue())
            self.assertEqual(first_payload["session"]["session_id"], "session-one")

            start_two_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(start_two_stdout),
            ):
                second_exit = main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Second multi-session workflow",
                        "--session-id",
                        "session-two",
                        "--roadmap-phase",
                        "phase_7",
                    ]
                )

            self.assertEqual(second_exit, 0)

            sessions_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(sessions_stdout),
            ):
                sessions_exit = main(["sessions", "--repo-root", str(root)])

            self.assertEqual(sessions_exit, 0)
            payload = json.loads(sessions_stdout.getvalue())
            self.assertEqual(len(payload["sessions"]), 2)
            active = [item for item in payload["sessions"] if item["is_active"]]
            self.assertEqual(active[0]["session_id"], "session-two")

    def test_restore_session_switches_the_active_root_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            sessions_dir = root / "sessions"

            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Session one goal",
                        "--session-id",
                        "session-one",
                        "--roadmap-phase",
                        "phase_7",
                    ]
                )
                main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Session two goal",
                        "--session-id",
                        "session-two",
                        "--roadmap-phase",
                        "phase_7",
                    ]
                )

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "restore-session",
                        "--repo-root",
                        str(root),
                        "--session-id",
                        "session-one",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["session"]["session_id"], "session-one")

    def test_run_without_explicit_session_id_uses_active_session_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)
            sessions_dir = root / "sessions"

            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Session A",
                        "--session-id",
                        "session-a",
                        "--roadmap-phase",
                        "phase_4",
                    ]
                )
                runtime_config = AppConfig.load(repo_root=root)

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--run-label",
                        "active-session-run",
                        "--max-retries",
                        "0",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertIn(str(runtime_config.sessions_dir / "session-a"), payload["report_path"])
            workflow_state = json.loads(
                (runtime_config.sessions_dir / "session-a" / "workflow_state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                str(runtime_config.sessions_dir / "session-a" / "logs"),
                workflow_state["latest_run"]["artifacts"]["stdout"],
            )

    def test_run_creates_repo_session_marker_and_reuses_it_on_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)
            sessions_dir = root / "sessions"

            first_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(first_stdout),
            ):
                first_exit = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                    ]
                )

            self.assertEqual(first_exit, 0)
            marker_path = root / ".session"
            self.assertTrue(marker_path.exists())
            session_id = marker_path.read_text(encoding="utf-8").strip()
            self.assertTrue(session_id)

            (root / ".attempt-count").unlink()
            (root / "done.txt").unlink()
            second_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(second_stdout),
            ):
                second_exit = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file again.",
                    ]
                )

            self.assertEqual(second_exit, 0)
            second_payload = json.loads(second_stdout.getvalue())
            runtime_config = AppConfig.load(repo_root=root)
            self.assertIn(str(runtime_config.sessions_dir / session_id), second_payload["report_path"])
            self.assertEqual(marker_path.read_text(encoding="utf-8").strip(), session_id)

    def test_run_starts_a_new_session_when_marker_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)
            sessions_dir = root / "sessions"

            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Existing session",
                        "--session-id",
                        "existing-session",
                        "--roadmap-phase",
                        "phase_4",
                    ]
                )

            (root / ".session").unlink()

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            session_id = (root / ".session").read_text(encoding="utf-8").strip()
            self.assertNotEqual(session_id, "existing-session")
            runtime_config = AppConfig.load(repo_root=root)
            self.assertIn(str(runtime_config.sessions_dir / session_id), payload["report_path"])

    def test_resume_can_target_a_saved_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)
            sessions_dir = root / "sessions"

            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Session A",
                        "--session-id",
                        "session-a",
                        "--roadmap-phase",
                        "phase_4",
                    ]
                )

            first_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(first_stdout),
            ):
                first_exit = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--run-label",
                        "phase7-resume-session",
                        "--max-retries",
                        "0",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(first_exit, 1)
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Session B",
                        "--session-id",
                        "session-b",
                        "--roadmap-phase",
                        "phase_7",
                    ]
                )
                runtime_config = AppConfig.load(repo_root=root)

            resume_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(resume_stdout),
            ):
                resume_exit = main(
                    [
                        "resume",
                        "--repo-root",
                        str(root),
                        "--session-id",
                        "session-a",
                        "--max-retries",
                        "1",
                    ]
                )

            self.assertEqual(resume_exit, 0)
            resume_payload = json.loads(resume_stdout.getvalue())
            self.assertEqual(resume_payload["status"], "completed")
            self.assertTrue((root / "done.txt").exists())
            self.assertTrue((runtime_config.sessions_dir / "session-a" / "workflow_state.json").exists())

    def test_resume_uses_repo_session_marker_before_active_root_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            first_stdout = io.StringIO()
            with contextlib.redirect_stdout(first_stdout):
                first_exit = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--max-retries",
                        "0",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(first_exit, 1)
            marked_session_id = (root / ".session").read_text(encoding="utf-8").strip()
            runtime_config = AppConfig.load(repo_root=root)

            with contextlib.redirect_stdout(io.StringIO()):
                main(
                    [
                        "start-session",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "Different active session",
                        "--session-id",
                        "session-b",
                        "--roadmap-phase",
                        "phase_7",
                    ]
                )

            (root / ".session").write_text(f"{marked_session_id}\n", encoding="utf-8")
            resume_stdout = io.StringIO()
            with contextlib.redirect_stdout(resume_stdout):
                resume_exit = main(
                    [
                        "resume",
                        "--repo-root",
                        str(root),
                        "--max-retries",
                        "1",
                    ]
                )

            self.assertEqual(resume_exit, 0)
            resume_payload = json.loads(resume_stdout.getvalue())
            self.assertEqual(resume_payload["status"], "completed")
            self.assertTrue((root / "done.txt").exists())
            self.assertEqual((root / ".session").read_text(encoding="utf-8").strip(), marked_session_id)
            self.assertTrue((runtime_config.sessions_dir / marked_session_id / "workflow_state.json").exists())

    def test_run_once_executes_external_cli_and_prints_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Phase 3 test prompt",
                        "--run-label",
                        "cli-test",
                        "--extra-arg=--echo-tag",
                        "--extra-arg",
                        "cli",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["exit_code"], 0)
            self.assertEqual(payload["prompt_mode"], "file")
            self.assertTrue(Path(payload["artifacts"]["stdout"]).exists())
            stdout_text = Path(payload["artifacts"]["stdout"]).read_text(encoding="utf-8")
            self.assertIn("Phase 3 test prompt", stdout_text)
            self.assertIn("Follow the guidance files below before making changes.", stdout_text)
            self.assertIn("bootstrap", stdout_text)
            self.assertIn(
                "This workflow keeps downstream execution under the supervising-agent contract",
                stdout_text,
            )

    def test_run_once_uses_configured_active_agent_cli_when_flag_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            (root / "dormammu.json").write_text(
                json.dumps({"active_agent_cli": str(fake_cli)}),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--prompt",
                        "Configured CLI prompt",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["cli_path"], str(fake_cli))
            stdout_text = Path(payload["artifacts"]["stdout"]).read_text(encoding="utf-8")
            self.assertIn("Configured CLI prompt", stdout_text)
            self.assertIn("Follow the guidance files below before making changes.", stdout_text)
            self.assertIn(
                "This workflow keeps downstream execution under the supervising-agent contract",
                stdout_text,
            )

    def test_run_once_defaults_workdir_to_repo_root_when_invoked_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            root = temp_root / "repo"
            root.mkdir()
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            outside_cwd = temp_root / "outside"
            outside_cwd.mkdir()

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.chdir(outside_cwd),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Repo-root workdir prompt",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["workdir"], str(root.resolve()))
            stdout_text = Path(payload["artifacts"]["stdout"]).read_text(encoding="utf-8")
            self.assertIn("Repo-root workdir prompt", stdout_text)

    def test_run_once_uses_custom_guidance_file_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            custom_guidance = root / "custom-rules.md"
            custom_guidance.write_text("# Rules\n\nAlways mention this custom file.\n", encoding="utf-8")

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--guidance-file",
                        str(custom_guidance),
                        "--prompt",
                        "Custom guidance prompt",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            stdout_text = Path(payload["artifacts"]["stdout"]).read_text(encoding="utf-8")
            self.assertIn("Custom guidance prompt", stdout_text)
            self.assertIn("Always mention this custom file.", stdout_text)
            self.assertNotIn("bootstrap", stdout_text)

    def test_run_once_falls_back_to_packaged_guidance_when_repo_guidance_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]\nname='temp'\nversion='0'\n", encoding="utf-8")
            fake_cli = self._write_fake_cli(root)

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Fallback guidance prompt",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            stdout_text = Path(payload["artifacts"]["stdout"]).read_text(encoding="utf-8")
            self.assertIn("Fallback guidance prompt", stdout_text)
            self.assertIn("distributable workflow guidance bundle", stdout_text)

    def test_run_loop_and_resume_loop_cover_phase_4_cli_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)
            sessions_dir = root / "sessions"

            first_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(first_stdout),
            ):
                first_exit = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--run-label",
                        "phase4-cli",
                        "--max-retries",
                        "0",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(first_exit, 1)
            first_payload = json.loads(first_stdout.getvalue())
            self.assertEqual(first_payload["status"], "failed")
            runtime_config = AppConfig.load(repo_root=root)
            session_id = self._active_session_id(runtime_config)
            self.assertTrue(
                (runtime_config.sessions_dir / session_id / "continuation_prompt.txt").exists()
            )

            resume_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(resume_stdout),
            ):
                resume_exit = main(
                    [
                        "resume",
                        "--repo-root",
                        str(root),
                        "--max-retries",
                        "1",
                    ]
                )

            self.assertEqual(resume_exit, 0)
            resume_payload = json.loads(resume_stdout.getvalue())
            self.assertEqual(resume_payload["status"], "completed")
            self.assertTrue((root / "done.txt").exists())

    def test_run_loop_after_init_state_retargets_active_roadmap_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)
            sessions_dir = root / "sessions"

            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                init_exit = main(["init-state", "--repo-root", str(root)])

            self.assertEqual(init_exit, 0)

            first_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(first_stdout),
            ):
                first_exit = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--run-label",
                        "phase4-after-init",
                        "--max-retries",
                        "0",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(first_exit, 1)
            first_payload = json.loads(first_stdout.getvalue())
            self.assertEqual(first_payload["status"], "failed")

            resume_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(resume_stdout),
            ):
                resume_exit = main(
                    [
                        "resume",
                        "--repo-root",
                        str(root),
                        "--max-retries",
                        "1",
                    ]
                )

            self.assertEqual(resume_exit, 0)
            resume_payload = json.loads(resume_stdout.getvalue())
            self.assertEqual(resume_payload["status"], "completed")
            self.assertTrue((root / "done.txt").exists())

    def test_run_defaults_to_fifty_total_iterations_when_budget_is_not_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["attempts_completed"], 1)
            self.assertEqual(payload["max_iterations"], 50)
            self.assertEqual(payload["max_retries"], 49)

    def test_run_accepts_explicit_max_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--max-iterations",
                        "1",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["attempts_completed"], 1)
            self.assertEqual(payload["max_iterations"], 1)

    def test_resume_accepts_max_iterations_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)
            sessions_dir = root / "sessions"

            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                first_exit = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--max-iterations",
                        "1",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(first_exit, 1)

            resume_stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(sessions_dir)}),
                contextlib.redirect_stdout(resume_stdout),
            ):
                resume_exit = main(
                    [
                        "resume",
                        "--repo-root",
                        str(root),
                        "--max-iterations",
                        "2",
                    ]
                )

            self.assertEqual(resume_exit, 0)
            payload = json.loads(resume_stdout.getvalue())
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["max_iterations"], 2)

    def test_run_rejects_combining_max_iterations_and_max_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--max-iterations",
                        "5",
                        "--max-retries",
                        "4",
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertIn("Use either --max-iterations or --max-retries", stderr.getvalue())

    def test_run_once_emits_runtime_banner_and_live_agent_output_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Visible prompt",
                        "--extra-arg=--echo-tag",
                        "--extra-arg=live",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["exit_code"], 0)
            progress = stderr.getvalue()
            self.assertIn("=== dormammu run ===", progress)
            self.assertIn(f"target project: {root}", progress)
            self.assertIn(f"cli: {fake_cli}", progress)
            self.assertIn("=== dormammu command ===", progress)
            self.assertIn("command: ", progress)
            self.assertIn("Task prompt:\nVisible prompt", progress)
            self.assertIn("TAG::live", progress)

    def test_run_loop_emits_dashboard_and_tasks_snapshots_to_stderr_each_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--run-label",
                        "visible-loop",
                        "--max-retries",
                        "1",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "completed")
            progress = stderr.getvalue()
            self.assertIn("=== dormammu run ===", progress)
            self.assertGreaterEqual(progress.count("=== DASHBOARD.md ==="), 2)
            self.assertGreaterEqual(progress.count("=== PLAN.md ==="), 2)
            self.assertIn("# DASHBOARD", progress)
            self.assertIn("# PLAN", progress)
            self.assertIn("=== dormammu supervisor ===", progress)
            self.assertIn("ATTEMPT::1", progress)
            self.assertIn("ATTEMPT::2", progress)
            self.assertIn(
                "This workflow keeps downstream execution under the supervising-agent contract",
                progress,
            )

    def test_run_once_does_not_create_project_log_without_debug(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Visible prompt without project log",
                        "--run-label",
                        "project-log-disabled",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse((root / "DORMAMMU.log").exists())

    def test_run_once_appends_runtime_output_to_project_log_when_debug_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--debug",
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Visible prompt for project log",
                        "--run-label",
                        "project-log-once",
                        "--extra-arg=--echo-tag",
                        "--extra-arg",
                        "project-log",
                    ]
                )

            self.assertEqual(exit_code, 0)
            project_log = root / "DORMAMMU.log"
            self.assertTrue(project_log.exists())
            log_text = project_log.read_text(encoding="utf-8")
            self.assertIn("=== dormammu run-once started", log_text)
            self.assertIn("=== dormammu run ===", log_text)
            self.assertIn(f"target project: {root}", log_text)
            self.assertIn("=== dormammu command ===", log_text)
            self.assertIn("Visible prompt for project log", log_text)
            self.assertIn("TAG::project-log", log_text)
            self.assertIn("=== dormammu run-once finished", log_text)

    def test_run_loop_appends_attempt_progress_to_project_log_when_debug_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DORMAMMU_SESSIONS_DIR": str(root / "sessions")}),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run",
                        "--repo-root",
                        str(root),
                        "--debug",
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt",
                        "Create the required marker file.",
                        "--run-label",
                        "project-log-loop",
                        "--max-retries",
                        "1",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(exit_code, 0)
            project_log = root / "DORMAMMU.log"
            self.assertTrue(project_log.exists())
            log_text = project_log.read_text(encoding="utf-8")
            self.assertIn("=== dormammu run started", log_text)
            self.assertIn("=== dormammu run ===", log_text)
            self.assertIn("=== DASHBOARD.md ===", log_text)
            self.assertIn("=== PLAN.md ===", log_text)
            self.assertIn("=== dormammu supervisor ===", log_text)
            self.assertIn("ATTEMPT::1", log_text)
            self.assertIn("ATTEMPT::2", log_text)
            self.assertIn("=== dormammu run finished", log_text)

    def test_run_with_prompt_file_copies_prompt_to_session_and_global_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home = Path(tmpdir) / "home"
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            prompt_file = root / "PROMPT.md"
            prompt_file.write_text(
                "# Session Prompt\n\n- Create DASHBOARD.md and PLAN.md from this request.\n",
                encoding="utf-8",
            )

            sessions_dir = home / ".dormammu" / "sessions"
            stdout = io.StringIO()
            with (
                mock.patch.dict("os.environ", {"HOME": str(home), "DORMAMMU_SESSIONS_DIR": str(sessions_dir)}, clear=False),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "run-once",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                        "--prompt-file",
                        str(prompt_file),
                    ]
                )
                runtime_config = AppConfig.load(repo_root=root)

            self.assertEqual(exit_code, 0)
            session_id = self._active_session_id(runtime_config)
            session_prompt = runtime_config.sessions_dir / session_id / "PROMPT.md"
            self.assertTrue(session_prompt.exists())
            self.assertEqual(session_prompt.read_text(encoding="utf-8"), prompt_file.read_text(encoding="utf-8"))
            global_prompt = runtime_config.sessions_dir / session_id / ".dev" / "PROMPT.md"
            self.assertTrue(global_prompt.exists())
            self.assertEqual(global_prompt.read_text(encoding="utf-8"), prompt_file.read_text(encoding="utf-8"))
            session_plan = runtime_config.sessions_dir / session_id / "PLAN.md"
            self.assertTrue(session_plan.exists())
            self.assertIn("Create DASHBOARD.md and PLAN.md from this request", session_plan.read_text(encoding="utf-8"))

    def test_inspect_cli_reports_preset_and_auto_approve_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_aider_cli(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "inspect-cli",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            capabilities = payload["capabilities"]
            self.assertEqual(capabilities["preset"]["key"], "aider")
            self.assertEqual(capabilities["prompt_file_flag"], "--message-file")
            self.assertTrue(capabilities["auto_approve"]["supported"])
            self.assertEqual(capabilities["auto_approve"]["candidates"][0]["value"], "--yes")

    def test_loop_aliases_parse_with_existing_handlers(self) -> None:
        parser = build_parser()

        run_args = parser.parse_args(["run-loop", "--agent-cli", "tool", "--prompt", "hi"])
        resume_args = parser.parse_args(["resume-loop"])

        self.assertEqual(run_args.command, "run-loop")
        self.assertEqual(resume_args.command, "resume-loop")
        self.assertIsNotNone(run_args.handler)
        self.assertIsNotNone(resume_args.handler)

    def test_main_without_arguments_starts_interactive_shell(self) -> None:
        with mock.patch("dormammu.cli.InteractiveShellRunner.run", return_value=0) as run:
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        run.assert_called_once()

    def test_explicit_subcommand_bypasses_interactive_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            with mock.patch("dormammu.cli.InteractiveShellRunner.run", return_value=0) as run:
                exit_code = main(["show-config", "--repo-root", str(root)])

        self.assertEqual(exit_code, 0)
        run.assert_not_called()

    def test_interactive_shell_config_set_updates_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            stdin = io.StringIO("/config set active_agent_cli /usr/bin/codex\n/exit\n")
            stdout = io.StringIO()

            exit_code = InteractiveShellRunner(repo_root=root, stdin=stdin, stdout=stdout, env=dict(os.environ)).run()

            self.assertEqual(exit_code, 0)
            payload = json.loads((root / "dormammu.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["active_agent_cli"], "/usr/bin/codex")
            self.assertIn("config updated:", stdout.getvalue())

    def test_interactive_shell_daemon_enqueue_writes_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            home = root / "home"
            daemon_config_path = home / ".dormammu" / "daemonize.json"
            prompt_path = root / "queue" / "prompts"
            result_path = root / "queue" / "results"
            daemon_config_path.parent.mkdir(parents=True, exist_ok=True)
            daemon_config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": str(prompt_path),
                        "result_path": str(result_path),
                    }
                ),
                encoding="utf-8",
            )
            stdin = io.StringIO("/daemon enqueue test queued prompt\n/exit\n")
            stdout = io.StringIO()
            env = {**os.environ, "HOME": str(home)}

            exit_code = InteractiveShellRunner(repo_root=root, stdin=stdin, stdout=stdout, env=env).run()

            self.assertEqual(exit_code, 0)
            queued = sorted(prompt_path.glob("*.md"))
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0].read_text(encoding="utf-8").strip(), "test queued prompt")
            self.assertIn("daemon prompt queued:", stdout.getvalue())

    def test_root_help_mentions_prompt_file_example(self) -> None:
        parser = build_parser()
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            parser.print_help()

        help_text = stdout.getvalue()
        self.assertIn("dormammu run --agent-cli codex --prompt-file PROMPT.md", help_text)
        self.assertIn("Use `dormammu <command> --help`", help_text)

    def test_doctor_reports_ready_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            (root / ".agents").mkdir()
            fake_cli = self._write_fake_cli(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "doctor",
                        "--repo-root",
                        str(root),
                        "--agent-cli",
                        str(fake_cli),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["home_dir"], str(Path.home()))
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertTrue(checks["python_version"]["ok"])
            self.assertTrue(checks["home_directory"]["ok"])
            self.assertTrue(checks["agent_cli"]["ok"])
            self.assertTrue(checks["agent_directory"]["ok"])
            self.assertTrue(checks["repo_writable"]["ok"])

    def test_doctor_reports_missing_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with (
                mock.patch.dict("os.environ", {"HOME": str(root / "home")}, clear=False),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "doctor",
                        "--repo-root",
                        str(root),
                    ]
                )

            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "issues_found")
            self.assertEqual(payload["home_dir"], str((root / "home").expanduser()))
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertFalse(checks["home_directory"]["ok"])
            self.assertFalse(checks["agent_cli"]["ok"])
            self.assertFalse(checks["agent_directory"]["ok"])

    def test_doctor_uses_configured_active_agent_cli_when_flag_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            (root / ".agents").mkdir()
            fake_cli = self._write_fake_cli(root)
            (root / "dormammu.json").write_text(
                json.dumps({"active_agent_cli": str(fake_cli)}),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["doctor", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertTrue(checks["home_directory"]["ok"])
            self.assertTrue(checks["agent_cli"]["ok"])

    def _seed_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text(
            "# DASHBOARD\n\n- Goal: ${goal}\n",
            encoding="utf-8",
        )
        (templates / "plan.md.tmpl").write_text(
            "# PLAN\n\n${task_items}\n",
            encoding="utf-8",
        )

    def _write_fake_cli(self, root: Path) -> Path:
        script = root / "fake-agent"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-agent [--prompt-file PATH] [--echo-tag TAG]")
                        return 0

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    tag = ""
                    if "--echo-tag" in args:
                        index = args.index("--echo-tag")
                        tag = args[index + 1]

                    print(f"PROMPT::{{prompt.strip()}}")
                    print(f"TAG::{{tag}}")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_loop_cli(self, root: Path, *, success_attempt: int) -> Path:
        script = root / "fake-loop-agent"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                ROOT = Path({str(root)!r})
                SUCCESS_ATTEMPT = {success_attempt}
                COUNTER_PATH = ROOT / ".attempt-count"
                TARGET_PATH = ROOT / "done.txt"
                import os
                _base_dev_dir = os.environ.get("DORMAMMU_BASE_DEV_DIR", "").strip()
                BASE_DEV_DIR = Path(_base_dev_dir) if _base_dev_dir else ROOT / ".dev"
                SESSION_PATH = BASE_DEV_DIR / "session.json"

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
                    import json
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    _sdir = os.environ.get("DORMAMMU_SESSIONS_DIR", "").strip()
                    candidates = []
                    if _sdir:
                        candidates.append(Path(_sdir))
                    candidates.append(BASE_DEV_DIR / "sessions")
                    candidates.append(ROOT / ".dev" / "sessions")

                    for sessions_dir in candidates:
                        session_dir = sessions_dir / str(session_id)
                        if session_dir.exists():
                            mark_complete(session_dir / "PLAN.md")
                            mark_complete(session_dir / "TASKS.md")
                            return

                    for sessions_dir in candidates:
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
                        print(f"PROMPT::{{prompt.strip()}}")
                        return 0

                    if is_prelude_prompt(prompt):
                        print("PRELUDE::ok")
                        print(f"PROMPT::{{prompt.strip()}}")
                        return 0

                    if COUNTER_PATH.exists():
                        attempt = int(COUNTER_PATH.read_text(encoding="utf-8").strip()) + 1
                    else:
                        attempt = 1
                    COUNTER_PATH.write_text(str(attempt), encoding="utf-8")

                    print(f"ATTEMPT::{{attempt}}")
                    print(f"PROMPT::{{prompt.strip()}}")

                    if attempt >= SUCCESS_ATTEMPT:
                        TARGET_PATH.write_text("done\\n", encoding="utf-8")
                        mark_plan_complete()

                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_aider_cli(self, root: Path) -> Path:
        script = root / "aider"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: aider [--message-file PATH] [--message TEXT] [--yes]")
                        return 0
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_path_tool(self, directory: Path, name: str) -> Path:
        script = directory / name
        script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script


class SetConfigCliTests(unittest.TestCase):
    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("marker\n", encoding="utf-8")

    def test_set_config_writes_scalar_and_prints_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["set-config", "--repo-root", str(root), "active_agent_cli", "/usr/bin/claude"])

            self.assertEqual(exit_code, 0)
            written_path = Path(stdout.getvalue().strip())
            payload = json.loads(written_path.read_text())
            self.assertEqual(payload["active_agent_cli"], "/usr/bin/claude")

    def test_set_config_unset_removes_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config_path = root / "dormammu.json"
            config_path.write_text(json.dumps({"active_agent_cli": "/old/cli"}), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["set-config", "--repo-root", str(root), "active_agent_cli", "--unset"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(config_path.read_text())
            self.assertNotIn("active_agent_cli", payload)

    def test_set_config_add_appends_to_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "set-config", "--repo-root", str(root),
                    "token_exhaustion_patterns", "--add", "context window exceeded",
                ])

            self.assertEqual(exit_code, 0)
            config_path = Path(stdout.getvalue().strip())
            payload = json.loads(config_path.read_text())
            self.assertIn("context window exceeded", payload["token_exhaustion_patterns"])

    def test_set_config_remove_drops_from_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps({"token_exhaustion_patterns": ["usage limit", "quota exceeded"]}),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "set-config", "--repo-root", str(root),
                    "token_exhaustion_patterns", "--remove", "usage limit",
                ])

            self.assertEqual(exit_code, 0)
            payload = json.loads(config_path.read_text())
            self.assertNotIn("usage limit", payload["token_exhaustion_patterns"])
            self.assertIn("quota exceeded", payload["token_exhaustion_patterns"])

    def test_set_config_unknown_key_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["set-config", "--repo-root", str(root), "nonexistent_key", "val"])

            self.assertEqual(exit_code, 1)
            self.assertIn("nonexistent_key", stderr.getvalue())

    def test_set_config_global_scope_writes_to_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            self._seed_repo(root)
            home_dir = Path(tmpdir) / "home"
            env_patch = {**os.environ, "HOME": str(home_dir)}

            with mock.patch.dict(os.environ, env_patch, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main([
                        "set-config", "--repo-root", str(root),
                        "active_agent_cli", "/usr/bin/codex", "--global",
                    ])

            self.assertEqual(exit_code, 0)
            global_config = home_dir / ".dormammu" / "config"
            self.assertTrue(global_config.exists())
            payload = json.loads(global_config.read_text())
            self.assertEqual(payload["active_agent_cli"], "/usr/bin/codex")

    def test_set_config_help_text_shows_settable_keys(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(stdout):
            build_parser().parse_args(["set-config", "--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("active_agent_cli", help_text)
        self.assertIn("token_exhaustion_patterns", help_text)


if __name__ == "__main__":
    unittest.main()
