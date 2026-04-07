from __future__ import annotations

import contextlib
import io
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

from dormammu.cli import main


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

    def _seed_repo(self, root: Path) -> None:
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


if __name__ == "__main__":
    unittest.main()
