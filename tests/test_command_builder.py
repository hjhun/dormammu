from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.agent import AgentRunRequest, CliCapabilities, build_command_plan


class CommandBuilderTests(unittest.TestCase):
    def test_auto_mode_prefers_prompt_file_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            request = AgentRunRequest(
                cli_path=Path("/tmp/fake-agent"),
                prompt_text="hello",
                repo_root=Path(tmpdir),
                extra_args=("--flag",),
            )
            capabilities = CliCapabilities(
                help_flag="--help",
                prompt_file_flag="--prompt-file",
                prompt_arg_flag="--prompt",
                workdir_flag=None,
                help_text="",
                help_exit_code=0,
            )

            plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

            self.assertEqual(plan.prompt_mode, "file")
            self.assertEqual(
                list(plan.argv),
                ["/tmp/fake-agent", "--prompt-file", str(prompt_path), "--flag"],
            )
            self.assertIsNone(plan.stdin_input)

    def test_auto_mode_falls_back_to_stdin_without_known_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            request = AgentRunRequest(
                cli_path=Path("/tmp/fake-agent"),
                prompt_text="hello from stdin",
                repo_root=Path(tmpdir),
            )
            capabilities = CliCapabilities(
                help_flag="--help",
                prompt_file_flag=None,
                prompt_arg_flag=None,
                workdir_flag=None,
                help_text="",
                help_exit_code=0,
            )

            plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

            self.assertEqual(plan.prompt_mode, "stdin")
            self.assertEqual(list(plan.argv), ["/tmp/fake-agent"])
            self.assertEqual(plan.stdin_input, "hello from stdin")

    def test_auto_mode_supports_positional_prompt_with_command_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            request = AgentRunRequest(
                cli_path=Path("/tmp/codex"),
                prompt_text="inspect the repository",
                repo_root=Path(tmpdir),
            )
            capabilities = CliCapabilities(
                help_flag="--help",
                prompt_file_flag=None,
                prompt_arg_flag=None,
                workdir_flag=None,
                help_text="",
                help_exit_code=0,
                command_prefix=("exec",),
                prompt_positional=True,
            )

            plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

            self.assertEqual(plan.prompt_mode, "positional")
            self.assertEqual(
                list(plan.argv),
                ["/tmp/codex", "exec", "inspect the repository"],
            )
            self.assertIsNone(plan.stdin_input)

    def test_positional_prompt_keeps_extra_args_before_prompt_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            request = AgentRunRequest(
                cli_path=Path("/tmp/cline"),
                prompt_text="inspect the repository",
                repo_root=Path(tmpdir),
                extra_args=("-y",),
            )
            capabilities = CliCapabilities(
                help_flag="--help",
                prompt_file_flag=None,
                prompt_arg_flag=None,
                workdir_flag=None,
                help_text="",
                help_exit_code=0,
                prompt_positional=True,
            )

            plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

            self.assertEqual(plan.prompt_mode, "positional")
            self.assertEqual(
                list(plan.argv),
                ["/tmp/cline", "-y", "inspect the repository"],
            )
            self.assertIsNone(plan.stdin_input)

    def test_claude_print_mode_keeps_permission_flags_before_prompt_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            request = AgentRunRequest(
                cli_path=Path("/tmp/claude"),
                prompt_text="build the feature",
                repo_root=Path(tmpdir),
                extra_args=("--permission-mode", "auto"),
            )
            capabilities = CliCapabilities(
                help_flag="--help",
                prompt_file_flag=None,
                prompt_arg_flag=None,
                workdir_flag=None,
                help_text="",
                help_exit_code=0,
                command_prefix=("--print",),
                prompt_positional=True,
            )

            plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

            self.assertEqual(plan.prompt_mode, "positional")
            self.assertEqual(
                list(plan.argv),
                ["/tmp/claude", "--print", "--permission-mode", "auto", "build the feature"],
            )
            self.assertIsNone(plan.stdin_input)

    def test_workdir_flag_is_injected_before_positional_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            workdir = Path(tmpdir) / "workspace"
            request = AgentRunRequest(
                cli_path=Path("/tmp/cline"),
                prompt_text="inspect the repository",
                repo_root=Path(tmpdir),
                workdir=workdir,
                extra_args=("-y", "--verbose", "--timeout", "1200"),
            )
            capabilities = CliCapabilities(
                help_flag="--help",
                prompt_file_flag=None,
                prompt_arg_flag=None,
                workdir_flag="--cwd",
                help_text="",
                help_exit_code=0,
                prompt_positional=True,
            )

            plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

            self.assertEqual(plan.prompt_mode, "positional")
            self.assertEqual(
                list(plan.argv),
                [
                    "/tmp/cline",
                    "--cwd",
                    str(workdir),
                    "-y",
                    "--verbose",
                    "--timeout",
                    "1200",
                    "inspect the repository",
                ],
            )
            self.assertIsNone(plan.stdin_input)


if __name__ == "__main__":
    unittest.main()
