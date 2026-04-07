from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig, discover_repo_root


class ConfigTests(unittest.TestCase):
    def test_discover_repo_root_walks_upward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested = root / "nested" / "child"
            nested.mkdir(parents=True)
            (root / "AGENTS.md").write_text("marker\n", encoding="utf-8")

            self.assertEqual(discover_repo_root(nested), root)

    def test_load_uses_env_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = AppConfig.load(
                repo_root=root,
                env={
                    "DORMAMMU_APP_NAME": "custom-app",
                    "DORMAMMU_HOST": "0.0.0.0",
                    "DORMAMMU_PORT": "9000",
                    "DORMAMMU_LOG_LEVEL": "debug",
                },
            )

            self.assertEqual(config.app_name, "custom-app")
            self.assertEqual(config.host, "0.0.0.0")
            self.assertEqual(config.port, 9000)
            self.assertEqual(config.log_level, "debug")
            self.assertEqual(config.repo_root, root)
            self.assertEqual(config.dev_dir, root / ".dev")


if __name__ == "__main__":
    unittest.main()
