from __future__ import annotations

import json
import os
from pathlib import Path
import stat
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
                },
            )

            self.assertEqual(config.app_name, "custom-app")
            self.assertEqual(config.repo_root, root)
            self.assertEqual(config.base_dev_dir, root / ".dev")
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
                        "cli_overrides": {
                            "cline": {
                                "input_mode": "arg",
                                "prompt_flag": "--prompt",
                                "extra_args": ["-y", "--verbose"],
                            }
                        },
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
            self.assertIsNotNone(config.cli_overrides)
            self.assertEqual(config.cli_overrides["cline"].extra_args, ("-y", "--verbose"))
            self.assertEqual(config.cli_overrides["cline"].input_mode, "arg")
            self.assertEqual(config.cli_overrides["cline"].prompt_flag, "--prompt")
            self.assertEqual(
                config.token_exhaustion_patterns,
                ("usage limit exceeded", "quota exhausted"),
            )

    def test_load_reads_global_config_from_home_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            config_path = home_dir / ".dormammu" / "config"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "active_agent_cli": "/opt/tools/codex",
                        "cli_overrides": {"cline": {"extra_args": ["-y", "--verbose"]}},
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(
                repo_root=root,
                env={
                    "HOME": str(home_dir),
                    **{key: value for key, value in os.environ.items() if key != "HOME"},
                },
            )

            self.assertEqual(config.config_file, config_path.resolve())
            self.assertEqual(config.active_agent_cli, Path("/opt/tools/codex"))
            self.assertEqual(config.cli_overrides["cline"].extra_args, ("-y", "--verbose"))

    def test_load_preserves_absolute_symlink_for_active_agent_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real_cli = root / "real-codex"
            real_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            real_cli.chmod(real_cli.stat().st_mode | stat.S_IXUSR)
            symlink_cli = root / "codex"
            symlink_cli.symlink_to(real_cli)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps(
                    {
                        "active_agent_cli": str(symlink_cli),
                        "cli_overrides": {"codex": {"extra_args": ["--full-auto"]}},
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)

            self.assertEqual(config.active_agent_cli, symlink_cli)
            self.assertIn("codex", config.cli_overrides)

    def test_load_uses_default_fallback_cli_order_when_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            config = AppConfig.load(repo_root=root)

            self.assertEqual(
                [str(item.path) for item in config.fallback_agent_clis],
                ["codex", "claude", "gemini"],
            )

    def test_load_falls_back_to_packaged_asset_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "AGENTS.md").write_text("marker\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)

            self.assertTrue(config.templates_dir.exists())
            self.assertNotEqual(config.templates_dir, root / "templates")
            self.assertTrue(config.agents_dir.exists())

    def test_load_prefers_global_agents_dir_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            (root / "AGENTS.md").write_text("marker\n", encoding="utf-8")
            home_dir = Path(tmpdir) / "home"
            agents_dir = home_dir / ".dormammu" / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (agents_dir / "AGENTS.md").write_text("global guidance\n", encoding="utf-8")

            config = AppConfig.load(
                repo_root=root,
                env={
                    "HOME": str(home_dir),
                    **{key: value for key, value in os.environ.items() if key != "HOME"},
                },
            )

            self.assertEqual(config.agents_dir, agents_dir.resolve())
            self.assertEqual(config.default_guidance_files, (agents_dir.resolve() / "AGENTS.md",))


if __name__ == "__main__":
    unittest.main()
