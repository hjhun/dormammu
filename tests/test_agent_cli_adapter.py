from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.config import AppConfig
from dormammu.state import StateRepository


class CliAdapterTests(unittest.TestCase):
    def test_run_once_writes_artifacts_and_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)

            config = AppConfig.load(repo_root=root)
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
            self.assertIn("PROMPT::Write a tiny test plan.", result.stdout_path.read_text(encoding="utf-8"))
            self.assertIn("TAG::phase3", result.stdout_path.read_text(encoding="utf-8"))
            self.assertTrue(result.stderr_path.exists())

            workflow_state = json.loads((root / ".dev" / "workflow_state.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow_state["latest_run"]["run_id"], result.run_id)
            self.assertEqual(workflow_state["latest_run"]["prompt_mode"], "file")

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
            self.assertIn(
                "PROMPT::Summarize the repository.",
                result.stdout_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(result.capabilities.preset_key, "codex")
            self.assertIsNotNone(result.capabilities.auto_approve)
            self.assertEqual(result.capabilities.auto_approve.candidates[0].value, "--full-auto")

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
            self.assertIn("PROMPT::Write a tiny test plan.", result.stdout_path.read_text(encoding="utf-8"))

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "tasks.md.tmpl").write_text("# TASKS\n\n${task_items}\n", encoding="utf-8")

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
                    print("TRACE::stderr", file=sys.stderr)
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

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
                        print("Usage: codex [OPTIONS] [PROMPT]")
                        print("  codex exec [OPTIONS] [PROMPT]")
                        print("  --full-auto")
                        return 0

                    if args and args[0] == "exec":
                        prompt = " ".join(args[1:]).strip()
                        print(f"PROMPT::{{prompt}}")
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


if __name__ == "__main__":
    unittest.main()
