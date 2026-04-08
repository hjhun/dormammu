from __future__ import annotations

import json
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

    def test_load_reads_fallback_cli_settings_from_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps(
                    {
                        "fallback_agent_clis": [
                            "claude",
                            {
                                "path": "./bin/aider",
                                "extra_args": ["--yes"],
                                "input_mode": "arg",
                                "prompt_flag": "--message",
                            },
                        ],
                        "token_exhaustion_patterns": [
                            "usage limit exceeded",
                            "quota exhausted",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)

            self.assertEqual(config.config_file, config_path.resolve())
            self.assertEqual(str(config.fallback_agent_clis[0].path), "claude")
            self.assertEqual(config.fallback_agent_clis[1].path, (root / "bin" / "aider").resolve())
            self.assertEqual(config.fallback_agent_clis[1].extra_args, ("--yes",))
            self.assertEqual(config.fallback_agent_clis[1].input_mode, "arg")
            self.assertEqual(config.fallback_agent_clis[1].prompt_flag, "--message")
            self.assertEqual(
                config.token_exhaustion_patterns,
                ("usage limit exceeded", "quota exhausted"),
            )


if __name__ == "__main__":
    unittest.main()
