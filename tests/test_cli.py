from __future__ import annotations

import contextlib
import io
import json
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


class CliTests(unittest.TestCase):
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

    def test_init_state_uses_packaged_templates_when_repo_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["init-state", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / ".dev" / "DASHBOARD.md").exists())
            self.assertTrue((root / ".dev" / "TASKS.md").exists())

    def test_init_state_creates_bootstrap_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
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

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue((root / ".dev" / "DASHBOARD.md").exists())
            self.assertEqual(payload["logs_dir"], str(root / ".dev" / "logs"))

    def test_init_state_prompts_for_bootstrap_inputs_on_first_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with (
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch(
                    "builtins.input",
                    side_effect=["Interactive bootstrap goal", "phase_7"],
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = main(["init-state", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            workflow_state = json.loads((root / ".dev" / "workflow_state.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow_state["bootstrap"]["goal"], "Interactive bootstrap goal")
            self.assertEqual(workflow_state["roadmap"]["active_phase_ids"], ["phase_7"])

    def test_start_session_and_sessions_list_manage_archived_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            start_one_stdout = io.StringIO()
            with contextlib.redirect_stdout(start_one_stdout):
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
            with contextlib.redirect_stdout(start_two_stdout):
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
            with contextlib.redirect_stdout(sessions_stdout):
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

            with contextlib.redirect_stdout(io.StringIO()):
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
            with contextlib.redirect_stdout(stdout):
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

            with contextlib.redirect_stdout(io.StringIO()):
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

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
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
            self.assertIn(".dev/sessions/session-a", payload["report_path"])
            workflow_state = json.loads(
                (root / ".dev" / "sessions" / "session-a" / "workflow_state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                ".dev/sessions/session-a/logs",
                workflow_state["latest_run"]["artifacts"]["stdout"],
            )

    def test_resume_can_target_a_saved_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            with contextlib.redirect_stdout(io.StringIO()):
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
                        "--run-label",
                        "phase7-resume-session",
                        "--max-retries",
                        "0",
                        "--required-path",
                        "done.txt",
                    ]
                )

            self.assertEqual(first_exit, 1)
            with contextlib.redirect_stdout(io.StringIO()):
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

            resume_stdout = io.StringIO()
            with contextlib.redirect_stdout(resume_stdout):
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

    def test_run_once_executes_external_cli_and_prints_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
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
            self.assertIn(
                "PROMPT::Phase 3 test prompt",
                Path(payload["artifacts"]["stdout"]).read_text(encoding="utf-8"),
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
            with contextlib.redirect_stdout(stdout):
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
            self.assertIn(
                "PROMPT::Configured CLI prompt",
                Path(payload["artifacts"]["stdout"]).read_text(encoding="utf-8"),
            )

    def test_run_loop_and_resume_loop_cover_phase_4_cli_flow(self) -> None:
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
            self.assertTrue((root / ".dev" / "continuation_prompt.txt").exists())

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

    def test_run_loop_after_init_state_retargets_active_roadmap_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            with contextlib.redirect_stdout(io.StringIO()):
                init_exit = main(["init-state", "--repo-root", str(root)])

            self.assertEqual(init_exit, 0)

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
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertTrue(checks["python_version"]["ok"])
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
            checks = {item["name"]: item for item in payload["checks"]}
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
        (templates / "tasks.md.tmpl").write_text(
            "# TASKS\n\n${task_items}\n",
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

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-loop-agent [--prompt-file PATH]")
                        return 0

                    if COUNTER_PATH.exists():
                        attempt = int(COUNTER_PATH.read_text(encoding="utf-8").strip()) + 1
                    else:
                        attempt = 1
                    COUNTER_PATH.write_text(str(attempt), encoding="utf-8")

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    print(f"ATTEMPT::{{attempt}}")
                    print(f"PROMPT::{{prompt.strip()}}")

                    if attempt >= SUCCESS_ATTEMPT:
                        TARGET_PATH.write_text("done\\n", encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
