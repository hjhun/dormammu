from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
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

from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.agent import cli_adapter as cli_adapter_module
from dormammu.agent.prompt_identity import prepend_cli_identity
from dormammu.config import AppConfig
from dormammu.state import StateRepository


class CliAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self.sleep_mock = self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    def test_run_once_writes_artifacts_and_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_3"])

            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Write a tiny test plan.",
                    repo_root=root,
                    extra_args=("--echo-tag", "phase3"),
                    run_label="phase-3-smoke",
                )
            )
            repository.record_latest_run(result)

            self.assertEqual(result.exit_code, 0)
            self.assertIn(
                f"PROMPT::{prepend_cli_identity('Write a tiny test plan.', fake_cli)}",
                result.stdout_path.read_text(encoding="utf-8"),
            )
            self.assertIn("TAG::phase3", result.stdout_path.read_text(encoding="utf-8"))
            self.assertTrue(result.stderr_path.exists())

            session_id = json.loads(
                (config.base_dev_dir / "session.json").read_text(encoding="utf-8")
            )[
                "active_session_id"
            ]
            workflow_state = json.loads(
                (config.sessions_dir / session_id / "workflow_state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(workflow_state["latest_run"]["run_id"], result.run_id)
            self.assertEqual(workflow_state["latest_run"]["prompt_mode"], "file")

    def test_run_once_materializes_current_run_artifacts_before_persisting_started_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_7"])

            captured: dict[str, object] = {}

            def _handle_started(started: object) -> None:
                repository.record_current_run(started)
                workflow_state = repository.read_workflow_state()
                current_run = workflow_state["current_run"]
                metadata_path = Path(current_run["artifacts"]["metadata"])
                captured["current_run"] = current_run
                captured["artifact_paths_exist"] = all(
                    Path(item["path"]).exists() for item in current_run["artifact_refs"]
                )
                captured["metadata_payload"] = json.loads(
                    metadata_path.read_text(encoding="utf-8")
                )

            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Write a tiny test plan.",
                    repo_root=root,
                    run_label="current-run-artifacts",
                ),
                on_started=_handle_started,
            )

            self.assertEqual(result.exit_code, 0)
            self.assertTrue(captured["artifact_paths_exist"])
            current_run = captured["current_run"]
            self.assertEqual(current_run["run_id"], result.run_id)
            self.assertEqual(
                {item["kind"] for item in current_run["artifact_refs"]},
                {"prompt", "stdout", "stderr", "metadata"},
            )
            self.assertEqual(captured["metadata_payload"]["run_id"], result.run_id)
            self.assertEqual(
                {item["kind"] for item in captured["metadata_payload"]["artifact_refs"]},
                {"prompt", "stdout", "stderr", "metadata"},
            )

    def test_run_once_uses_codex_exec_preset_for_positional_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_codex_cli(root)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    run_label="phase-7-codex",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.prompt_mode, "positional")
            self.assertEqual(list(result.command[:2]), [str(fake_cli), "exec"])
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", result.command)
            self.assertIn(
                f"PROMPT::{prepend_cli_identity('Summarize the repository.', fake_cli)}",
                result.stdout_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(result.capabilities.preset_key, "codex")
            self.assertIsNotNone(result.capabilities.auto_approve)
            self.assertEqual(
                result.capabilities.auto_approve.candidates[0].value,
                "--dangerously-bypass-approvals-and-sandbox",
            )

    def test_run_once_applies_skip_git_repo_check_for_supported_codex_exec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_codex_cli(root, include_skip_git_repo_check=True)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    run_label="phase-7-codex-skip-git-check",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(
                list(result.command[:4]),
                [
                    str(fake_cli),
                    "exec",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--skip-git-repo-check",
                ],
            )

    def test_run_once_applies_skip_git_repo_check_when_only_exec_help_advertises_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_codex_cli(
                root,
                include_skip_git_repo_check=True,
                skip_git_repo_check_in_exec_help_only=True,
            )

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    run_label="phase-7-codex-exec-help-skip-git-check",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertIn("--skip-git-repo-check", result.command)

    def test_run_once_does_not_duplicate_explicit_skip_git_repo_check_for_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_codex_cli(root, include_skip_git_repo_check=True)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    extra_args=("--skip-git-repo-check",),
                    run_label="phase-7-codex-explicit-skip-git-check",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.command.count("--skip-git-repo-check"), 1)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", result.command)

    def test_run_once_does_not_add_dangerous_bypass_when_codex_approval_flags_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_codex_cli(root, include_skip_git_repo_check=True)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    extra_args=("--full-auto",),
                    run_label="phase-7-codex-explicit-approval-mode",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", result.command)
            self.assertEqual(result.command.count("--full-auto"), 1)

    def test_run_once_falls_back_across_configured_clis_when_token_limit_is_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            primary_cli = self._write_exhausted_cli(root, name="primary-agent", message="usage limit exceeded")
            fallback_one = self._write_exhausted_cli(root, name="fallback-one", message="quota exceeded")
            fallback_two = self._write_fake_cli(root)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "fallback_agent_clis": [
                            str(fallback_one),
                            str(fallback_two),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=primary_cli,
                    prompt_text="Write a tiny test plan.",
                    repo_root=root,
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.requested_cli_path, primary_cli.resolve())
            self.assertEqual(result.cli_path, fallback_two.resolve())
            self.assertEqual(
                list(result.attempted_cli_paths),
                [
                    primary_cli.resolve(),
                    fallback_one.resolve(),
                    fallback_two.resolve(),
                ],
            )
            self.assertEqual(result.fallback_trigger, "quota exceeded")
            self.assertIn(
                f"PROMPT::{prepend_cli_identity('Write a tiny test plan.', fallback_two)}",
                result.stdout_path.read_text(encoding="utf-8"),
            )

    def test_run_once_waits_between_fallback_cli_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            primary_cli = self._write_exhausted_cli(root, name="primary-agent", message="usage limit exceeded")
            fallback_one = self._write_exhausted_cli(root, name="fallback-one", message="quota exceeded")
            fallback_two = self._write_fake_cli(root, name="fallback-two")
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "fallback_agent_clis": [
                            str(fallback_one),
                            str(fallback_two),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            adapter = CliAdapter(config)
            self.sleep_mock.reset_mock()
            result = adapter.run_once(
                AgentRunRequest(
                    cli_path=primary_cli,
                    prompt_text="Write a tiny test plan.",
                    repo_root=root,
                )
            )
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(self.sleep_mock.call_count, 2)

    def test_run_once_applies_cli_overrides_for_cline_style_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cline_cli(root)
            workdir = root / "workspace"
            workdir.mkdir()
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "cli_overrides": {
                            "cline": {
                                "extra_args": ["-y", "--verbose", "--timeout", "1200"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    workdir=workdir,
                    run_label="phase-7-cline",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.prompt_mode, "positional")
            self.assertEqual(
                list(result.command),
                [
                    str(fake_cli),
                    "--cwd",
                    str(workdir),
                    "-y",
                    "--verbose",
                    "--timeout",
                    "1200",
                    prepend_cli_identity("Summarize the repository.", fake_cli),
                ],
            )
            self.assertIn(
                f"PROMPT::{prepend_cli_identity('Summarize the repository.', fake_cli)}",
                result.stdout_path.read_text(encoding="utf-8"),
            )
            self.assertIn("YOLO::yes", result.stdout_path.read_text(encoding="utf-8"))
            self.assertIn(f"CWD::{workdir}", result.stdout_path.read_text(encoding="utf-8"))
            self.assertIn("VERBOSE::yes", result.stdout_path.read_text(encoding="utf-8"))
            self.assertIn("TIMEOUT::1200", result.stdout_path.read_text(encoding="utf-8"))

    def test_run_once_applies_default_timeout_but_not_verbose_for_cline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cline_cli(root)
            workdir = root / "workspace"
            workdir.mkdir()
            home_dir = root / "home"
            home_dir.mkdir()

            config = AppConfig.load(
                repo_root=root,
                env={
                    **os.environ,
                    "HOME": str(home_dir),
                },
            )
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    workdir=workdir,
                    run_label="phase-7-cline-defaults",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.prompt_mode, "positional")
            self.assertEqual(
                list(result.command),
                [
                    str(fake_cli),
                    "--cwd",
                    str(workdir),
                    "--timeout",
                    "1200",
                    prepend_cli_identity("Summarize the repository.", fake_cli),
                ],
            )
            stdout_text = result.stdout_path.read_text(encoding="utf-8")
            self.assertIn("VERBOSE::no", stdout_text)
            self.assertIn("TIMEOUT::1200", stdout_text)

    def test_run_once_defaults_workdir_to_current_directory_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cline_cli(root)
            subdir = root / "workspace" / "feature"
            subdir.mkdir(parents=True, exist_ok=True)

            config = AppConfig.load(repo_root=root)
            with contextlib.chdir(subdir):
                result = CliAdapter(config).run_once(
                    AgentRunRequest(
                        cli_path=fake_cli,
                        prompt_text="Summarize the repository.",
                        repo_root=root,
                        run_label="cwd-default",
                    )
                )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.workdir, subdir)
            self.assertEqual(
                list(result.command[:3]),
                [str(fake_cli), "--cwd", str(subdir)],
            )
            self.assertIn(f"CWD::{subdir}", result.stdout_path.read_text(encoding="utf-8"))

    def test_run_once_applies_default_no_approval_mode_for_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_claude_cli(root)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    run_label="claude-no-approval",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.prompt_mode, "positional")
            self.assertEqual(
                list(result.command[:3]),
                [str(fake_cli), "--print", "--dangerously-skip-permissions"],
            )
            self.assertIn("MODE::dangerously-skip-permissions", result.stdout_path.read_text(encoding="utf-8"))

    def test_run_once_applies_default_no_approval_mode_for_gemini(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_gemini_cli(root)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    run_label="gemini-no-approval",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.prompt_mode, "arg")
            self.assertIn("--approval-mode", result.command)
            self.assertIn("yolo", result.command)
            self.assertIn("--include-directories", result.command)
            self.assertIn("/", result.command)
            self.assertIn("MODE::yolo", result.stdout_path.read_text(encoding="utf-8"))
            self.assertIn("INCLUDE::/", result.stdout_path.read_text(encoding="utf-8"))

    def test_run_once_does_not_duplicate_explicit_approval_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_gemini_cli(root)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    extra_args=("--approval-mode", "auto_edit"),
                    run_label="gemini-explicit-approval",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(
                list(result.command[-2:]),
                ["--approval-mode", "auto_edit"],
            )
            self.assertIn("MODE::auto_edit", result.stdout_path.read_text(encoding="utf-8"))

    def test_run_once_does_not_duplicate_explicit_include_directories_for_gemini(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_gemini_cli(root)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    extra_args=("--include-directories", "/proc"),
                    run_label="gemini-explicit-include",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertIn("--include-directories", result.command)
            self.assertIn("/proc", result.command)
            output_lines = result.stdout_path.read_text(encoding="utf-8").splitlines()
            self.assertNotIn("INCLUDE::/", output_lines)
            self.assertIn("INCLUDE::/proc", output_lines)

    def test_run_once_mirrors_live_output_to_parent_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = CliAdapter(config).run_once(
                    AgentRunRequest(
                        cli_path=fake_cli,
                        prompt_text="Watch the live terminal output.",
                        repo_root=root,
                        run_label="live-stream-test",
                    )
                )

            self.assertEqual(result.exit_code, 0)
            mirrored = stderr.getvalue()
            self.assertIn(
                f"PROMPT::[{fake_cli.name}]",
                mirrored,
            )
            self.assertIn("Watch the live terminal output.", mirrored)
            self.assertIn("TRACE::stderr", mirrored)

    def test_run_once_waits_before_second_agent_cli_call_and_logs_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            first_cli = self._write_fake_cli(root)
            second_cli = self._write_fake_cli(root, name="fake-agent-two")

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            self.sleep_mock.reset_mock()
            with contextlib.redirect_stderr(stderr):
                adapter = CliAdapter(config)
                first_result = adapter.run_once(
                    AgentRunRequest(
                        cli_path=first_cli,
                        prompt_text="First call.",
                        repo_root=root,
                        run_label="first-call",
                    )
                )
                second_result = adapter.run_once(
                    AgentRunRequest(
                        cli_path=second_cli,
                        prompt_text="Second call.",
                        repo_root=root,
                        run_label="second-call",
                    )
                )

            self.assertEqual(first_result.exit_code, 0)
            self.assertEqual(second_result.exit_code, 0)
            self.sleep_mock.assert_called_once_with(cli_adapter_module.CLI_RETRY_DELAY_SECONDS)
            mirrored = stderr.getvalue()
            self.assertIn(cli_adapter_module.CLI_RETRY_DELAY_MESSAGE, mirrored)
            self.assertIn(f"PROMPT::{prepend_cli_identity('First call.', first_cli)}", mirrored)
            self.assertIn(f"PROMPT::[{second_cli.name}]", mirrored)
            self.assertIn("Second call.", mirrored)

    def test_run_once_does_not_wait_across_separate_adapter_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            first_cli = self._write_fake_cli(root)
            second_cli = self._write_fake_cli(root, name="fake-agent-two")

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            self.sleep_mock.reset_mock()
            with contextlib.redirect_stderr(stderr):
                first_result = CliAdapter(config).run_once(
                    AgentRunRequest(
                        cli_path=first_cli,
                        prompt_text="First adapter call.",
                        repo_root=root,
                        run_label="first-adapter-call",
                    )
                )
                second_result = CliAdapter(config).run_once(
                    AgentRunRequest(
                        cli_path=second_cli,
                        prompt_text="Second adapter call.",
                        repo_root=root,
                        run_label="second-adapter-call",
                    )
                )

            self.assertEqual(first_result.exit_code, 0)
            self.assertEqual(second_result.exit_code, 0)
            self.sleep_mock.assert_not_called()
            self.assertNotIn(cli_adapter_module.CLI_RETRY_DELAY_MESSAGE, stderr.getvalue())

    def test_run_once_applies_cli_override_when_configured_codex_path_is_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            real_cli = self._write_fake_codex_cli(root, name="real-codex")
            symlink_cli = root / "codex"
            symlink_cli.symlink_to(real_cli)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "active_agent_cli": str(symlink_cli),
                        "cli_overrides": {
                            "codex": {
                                "extra_args": ["--full-auto"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=config.active_agent_cli,
                    prompt_text="Summarize the repository.",
                    repo_root=root,
                    run_label="codex-symlink-override",
                )
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(
                list(result.command[:3]),
                [str(symlink_cli), "exec", "--full-auto"],
            )
            output_text = result.stdout_path.read_text(encoding="utf-8")
            self.assertIn(
                f"PROMPT::{prepend_cli_identity('Summarize the repository.', symlink_cli)}",
                output_text,
            )
            self.assertIn("MODE::", output_text)

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")

    def _write_fake_cli(self, root: Path, *, name: str = "fake-agent") -> Path:
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: {name} [--prompt-file PATH] [--echo-tag TAG]")
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
                    print("TRACE::stderr", file=sys.stderr)
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_fake_codex_cli(
        self,
        root: Path,
        *,
        name: str = "codex",
        include_skip_git_repo_check: bool = False,
        skip_git_repo_check_in_exec_help_only: bool = False,
    ) -> Path:
        script = root / name
        main_help_skip_git_repo_check_line = ""
        exec_help_skip_git_repo_check_line = ""
        if include_skip_git_repo_check and not skip_git_repo_check_in_exec_help_only:
            main_help_skip_git_repo_check_line = 'print("  --skip-git-repo-check")'
        if include_skip_git_repo_check:
            exec_help_skip_git_repo_check_line = 'print("  --skip-git-repo-check")'
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
                            {exec_help_skip_git_repo_check_line}
                            return 0
                        print("Usage: codex [OPTIONS] [PROMPT]")
                        print("  codex exec [OPTIONS] [PROMPT]")
                        print("  --full-auto")
                        print("  --dangerously-bypass-approvals-and-sandbox")
                        {main_help_skip_git_repo_check_line}
                        return 0

                    if args and args[0] == "exec":
                        filtered_args = []
                        skip_next = False
                        for arg in args[1:]:
                            if skip_next:
                                skip_next = False
                                continue
                            if arg in ("-a", "-s"):
                                skip_next = True
                                continue
                            if arg in (
                                "--dangerously-bypass-approvals-and-sandbox",
                                "--full-auto",
                                "--skip-git-repo-check",
                                "--ask-for-approval",
                                "--sandbox",
                            ):
                                continue
                            filtered_args.append(arg)
                        prompt = " ".join(filtered_args).strip()
                        mode = "dangerous" if "--dangerously-bypass-approvals-and-sandbox" in args else ""
                        print(f"PROMPT::{{prompt}}")
                        print(f"MODE::{{mode}}")
                        return 0

                    print("unexpected invocation", file=sys.stderr)
                    return 1

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_exhausted_cli(self, root: Path, *, name: str, message: str) -> Path:
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: {name} [--prompt-file PATH]")
                        return 0

                    print({message!r}, file=sys.stderr)
                    return 2

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_fake_cline_cli(self, root: Path) -> Path:
        script = root / "cline"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("Usage: cline [prompt] [options]")
                        print("-y")
                        print("--verbose")
                        print("--cwd")
                        print("--timeout")
                        return 0

                    cwd = ""
                    timeout = ""
                    if "--cwd" in args:
                        index = args.index("--cwd")
                        cwd = args[index + 1]
                    if "--timeout" in args:
                        index = args.index("--timeout")
                        timeout = args[index + 1]
                    filtered_args = []
                    skip_next = False
                    for arg in args:
                        if skip_next:
                            skip_next = False
                            continue
                        if arg == "--cwd":
                            skip_next = True
                            continue
                        if arg == "--timeout":
                            skip_next = True
                            continue
                        if arg in ("-y", "--verbose"):
                            continue
                        filtered_args.append(arg)
                    prompt_args = filtered_args
                    if len(prompt_args) != 1:
                        print("interactive mode requires a single positional prompt", file=sys.stderr)
                        return 2

                    prompt = prompt_args[0]
                    print(f"PROMPT::{{prompt}}")
                    print(f"YOLO::{{'yes' if '-y' in args else 'no'}}")
                    print(f"CWD::{{cwd}}")
                    print(f"VERBOSE::{{'yes' if '--verbose' in args else 'no'}}")
                    print(f"TIMEOUT::{{timeout}}")
                    return 0

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

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("Usage: claude [options] [command] [prompt]")
                        print("  -p, --print")
                        print("  --permission-mode <mode>")
                        print("  --dangerously-skip-permissions")
                        return 0

                    mode = ""
                    if "--permission-mode" in args:
                        index = args.index("--permission-mode")
                        mode = args[index + 1]
                    elif "--dangerously-skip-permissions" in args:
                        mode = "dangerously-skip-permissions"

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

    def _write_fake_gemini_cli(self, root: Path) -> Path:
        script = root / "gemini"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("Usage: gemini [options] [command]")
                        print("  -p, --prompt")
                        print("  --approval-mode")
                        print("  --yolo")
                        return 0

                    prompt = ""
                    mode = ""
                    include_dir = ""
                    if "--prompt" in args:
                        index = args.index("--prompt")
                        prompt = args[index + 1]
                    if "--approval-mode" in args:
                        index = args.index("--approval-mode")
                        mode = args[index + 1]
                    elif "--yolo" in args:
                        mode = "yolo"
                    if "--include-directories" in args:
                        index = args.index("--include-directories")
                        include_dir = args[index + 1]

                    print(f"PROMPT::{{prompt}}")
                    print(f"MODE::{{mode}}")
                    print(f"INCLUDE::{{include_dir}}")
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
