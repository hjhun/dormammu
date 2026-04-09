from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "install.sh"


class InstallScriptTests(unittest.TestCase):
    def test_root_install_script_bootstraps_global_home_config_and_bin_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            home_dir = temp_root / "home"
            home_dir.mkdir()
            fake_tools_dir = temp_root / "fake-tools"
            fake_tools_dir.mkdir()
            bashrc_path = home_dir / ".bashrc"
            bashrc_path.write_text("# test bashrc\n", encoding="utf-8")

            codex_path = self._write_fake_tool(fake_tools_dir, "codex")
            self._write_fake_tool(fake_tools_dir, "cline")
            self._write_fake_whereis(fake_tools_dir, codex_path)

            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home_dir),
                    "PYTHON": sys.executable,
                    "DORMAMMU_INSTALL_SOURCE": str(ROOT),
                    "PATH": f"{fake_tools_dir}:{env['PATH']}",
                }
            )

            first_result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            second_result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            install_root = home_dir / ".dormammu"
            bin_dir = install_root / "bin"
            config_path = install_root / "config"
            binary = bin_dir / "dormammu"
            self.assertTrue(binary.exists())
            self.assertTrue(config_path.exists())
            self.assertIn("Installed dormammu into", first_result.stdout)
            self.assertIn(str(config_path), first_result.stdout)
            self.assertIn(str(bin_dir), first_result.stdout)
            self.assertIn(str(codex_path), first_result.stdout)
            self.assertIn("Updated", second_result.stdout)

            help_result = subprocess.run(
                [str(binary), "--help"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("usage: dormammu", help_result.stdout)

            package_assets_result = subprocess.run(
                [
                    str(install_root / "venv" / "bin" / "python"),
                    "-c",
                    (
                        "from pathlib import Path; "
                        "import dormammu; "
                        "asset = Path(dormammu.__file__).resolve().parent / 'assets' / 'agents' / 'AGENTS.md'; "
                        "print(asset); "
                        "print(asset.exists())"
                    ),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            package_asset_lines = package_assets_result.stdout.strip().splitlines()
            self.assertGreaterEqual(len(package_asset_lines), 2)
            self.assertEqual(package_asset_lines[-1], "True")

            packaged_repo = temp_root / "packaged-repo"
            packaged_repo.mkdir()
            subprocess.run(["git", "init", "-q", str(packaged_repo)], check=True)
            (packaged_repo / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
            (packaged_repo / ".agents").mkdir()

            init_state_result = subprocess.run(
                [str(binary), "init-state", "--repo-root", str(packaged_repo)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            init_payload = json.loads(init_state_result.stdout)
            self.assertTrue(Path(init_payload["dashboard"]).exists())
            self.assertTrue(Path(init_payload["tasks"]).exists())

            doctor_result = subprocess.run(
                [
                    str(binary),
                    "doctor",
                    "--repo-root",
                    str(packaged_repo),
                    "--agent-cli",
                    str(codex_path),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            doctor_payload = json.loads(doctor_result.stdout)
            self.assertEqual(doctor_payload["status"], "ok")

            fake_agent = self._write_fake_python_cli(packaged_repo, "fake-agent")
            run_once_result = subprocess.run(
                [
                    str(binary),
                    "run-once",
                    "--repo-root",
                    str(packaged_repo),
                    "--agent-cli",
                    str(fake_agent),
                    "--prompt",
                    "Installed binary prompt",
                    "--run-label",
                    "installed-e2e",
                    "--extra-arg=--echo-tag",
                    "--extra-arg",
                    "install",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            run_once_payload = json.loads(run_once_result.stdout)
            stdout_text = Path(run_once_payload["artifacts"]["stdout"]).read_text(encoding="utf-8")
            self.assertIn("PROMPT::Installed binary prompt", stdout_text)
            self.assertIn("TAG::install", stdout_text)

            fake_loop = self._write_fake_loop_cli(packaged_repo, success_attempt=2)
            first_loop = subprocess.run(
                [
                    str(binary),
                    "run",
                    "--repo-root",
                    str(packaged_repo),
                    "--agent-cli",
                    str(fake_loop),
                    "--prompt",
                    "Create done.txt",
                    "--run-label",
                    "installed-loop",
                    "--max-retries",
                    "0",
                    "--required-path",
                    "done.txt",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first_loop.returncode, 1)
            first_loop_payload = json.loads(first_loop.stdout)
            self.assertEqual(first_loop_payload["status"], "failed")
            self.assertIsNotNone(first_loop_payload["continuation_prompt_path"])
            self.assertTrue(Path(first_loop_payload["continuation_prompt_path"]).exists())

            resume_result = subprocess.run(
                [
                    str(binary),
                    "resume",
                    "--repo-root",
                    str(packaged_repo),
                    "--max-retries",
                    "1",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            resume_payload = json.loads(resume_result.stdout)
            self.assertEqual(resume_payload["status"], "completed")
            self.assertTrue((packaged_repo / "done.txt").exists())

            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config_payload["active_agent_cli"], str(codex_path))
            self.assertEqual(config_payload["cli_overrides"]["cline"]["extra_args"], ["-y"])

            export_line = f'export PATH="{bin_dir}:$PATH"'
            bashrc_contents = bashrc_path.read_text(encoding="utf-8")
            self.assertEqual(bashrc_contents.count(export_line), 1)

    def _write_fake_tool(self, directory: Path, name: str) -> Path:
        path = directory / name
        path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def _write_fake_whereis(self, directory: Path, codex_path: Path) -> Path:
        path = directory / "whereis"
        path.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                if [[ "$1" == "-b" ]]; then
                  shift
                fi
                name="$1"
                case "$name" in
                  codex)
                    printf 'codex: %s\\n' "{codex_path}"
                    ;;
                  cline)
                    printf 'cline: %s/cline\\n' "{directory}"
                    ;;
                  *)
                    printf '%s:\\n' "$name"
                    ;;
                esac
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def _write_fake_python_cli(self, root: Path, name: str) -> Path:
        path = root / name
        path.write_text(
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
                    if tag:
                        print(f"TAG::{{tag}}")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def _write_fake_loop_cli(self, root: Path, *, success_attempt: int) -> Path:
        path = root / "fake-loop-agent"
        path.write_text(
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
        path.chmod(0o755)
        return path


if __name__ == "__main__":
    unittest.main()
