from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "install.sh"


class InstallScriptTests(unittest.TestCase):
    def test_root_install_script_supports_local_source_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            install_root = temp_root / "install-root"
            bin_dir = temp_root / "bin"
            home_dir = temp_root / "home"
            home_dir.mkdir()

            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home_dir),
                    "PYTHON": sys.executable,
                    "DORMAMMU_INSTALL_SOURCE": str(ROOT),
                    "DORMAMMU_INSTALL_ROOT": str(install_root),
                    "DORMAMMU_BIN_DIR": str(bin_dir),
                }
            )

            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            binary = bin_dir / "dormammu"
            self.assertTrue(binary.exists())
            self.assertIn("Installed dormammu into", result.stdout)
            self.assertIn(str(bin_dir / "dormammu"), result.stdout)

            help_result = subprocess.run(
                [str(binary), "--help"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("usage: dormammu", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
