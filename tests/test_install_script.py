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


if __name__ == "__main__":
    unittest.main()
