from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig, discover_repo_root, set_config_value


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
            self.assertEqual(config.home_dir, Path.home())
            self.assertEqual(config.repo_dev_dir, root / ".dev")
            self.assertEqual(config.base_dev_dir, config.workspace_project_root / ".dev")
            self.assertEqual(config.dev_dir, config.base_dev_dir)
            self.assertEqual(config.workspace_tmp_dir, config.workspace_project_root / ".tmp")
            self.assertEqual(config.results_dir, config.global_home_dir / "results")

    def test_load_preserves_sessions_dir_override_with_workspace_shadow_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            sessions_dir = Path(tmpdir) / "custom-sessions"

            config = AppConfig.load(
                repo_root=root,
                env={
                    **os.environ,
                    "DORMAMMU_SESSIONS_DIR": str(sessions_dir),
                },
            )

            self.assertEqual(config.base_dev_dir, config.workspace_project_root / ".dev")
            self.assertEqual(config.sessions_dir, sessions_dir.resolve())

    def test_load_ignores_ambient_sessions_override_for_different_explicit_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            ambient_sessions_dir = Path(tmpdir) / "ambient-sessions"

            with mock.patch.dict(
                os.environ,
                {"DORMAMMU_SESSIONS_DIR": str(ambient_sessions_dir)},
                clear=False,
            ):
                config = AppConfig.load(repo_root=root)

            self.assertEqual(config.base_dev_dir, config.workspace_project_root / ".dev")
            self.assertEqual(config.sessions_dir, config.workspace_project_root / ".dev" / "sessions")

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
                                "extra_args": ["-y", "--verbose", "--timeout", "1200"],
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
            self.assertEqual(
                config.cli_overrides["cline"].extra_args,
                ("-y", "--verbose", "--timeout", "1200"),
            )
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
                        "cli_overrides": {
                            "cline": {"extra_args": ["-y", "--verbose", "--timeout", "1200"]}
                        },
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
            self.assertEqual(config.home_dir, home_dir)
            self.assertEqual(config.active_agent_cli, Path("/opt/tools/codex"))
            self.assertEqual(
                config.cli_overrides["cline"].extra_args,
                ("-y", "--verbose", "--timeout", "1200"),
            )

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


class SetConfigValueTests(unittest.TestCase):
    def _make_config(self, root: Path, home_dir: Path | None = None) -> AppConfig:
        env: dict[str, str] = {k: v for k, v in os.environ.items()}
        if home_dir is not None:
            env["HOME"] = str(home_dir)
        return AppConfig.load(repo_root=root, env=env)

    # --- scalar key: active_agent_cli ---

    def test_set_active_agent_cli_creates_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._make_config(root)

            written = set_config_value(config, "active_agent_cli", value="/usr/bin/claude")

            self.assertEqual(written, root / "dormammu.json")
            payload = json.loads(written.read_text())
            self.assertEqual(payload["active_agent_cli"], "/usr/bin/claude")

    def test_set_active_agent_cli_updates_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(json.dumps({"active_agent_cli": "/old/cli"}), encoding="utf-8")
            config = self._make_config(root)

            set_config_value(config, "active_agent_cli", value="/new/cli")

            payload = json.loads(config_path.read_text())
            self.assertEqual(payload["active_agent_cli"], "/new/cli")

    def test_unset_active_agent_cli_removes_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(json.dumps({"active_agent_cli": "/usr/bin/claude"}), encoding="utf-8")
            config = self._make_config(root)

            set_config_value(config, "active_agent_cli", unset=True)

            payload = json.loads(config_path.read_text())
            self.assertNotIn("active_agent_cli", payload)

    def test_set_active_agent_cli_rejects_add_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._make_config(root)

            with self.assertRaises(ValueError, msg="scalar key should reject --add"):
                set_config_value(config, "active_agent_cli", add="/usr/bin/claude")

    def test_set_global_scope_writes_to_home_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            home_dir = Path(tmpdir) / "home"
            config = self._make_config(root, home_dir=home_dir)

            written = set_config_value(config, "active_agent_cli", value="/usr/bin/codex", global_scope=True)

            self.assertEqual(written, home_dir / ".dormammu" / "config")
            payload = json.loads(written.read_text())
            self.assertEqual(payload["active_agent_cli"], "/usr/bin/codex")

    # --- list key: token_exhaustion_patterns ---

    def test_add_token_exhaustion_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._make_config(root)

            set_config_value(config, "token_exhaustion_patterns", add="context window exceeded")

            payload = json.loads((root / "dormammu.json").read_text())
            self.assertIn("context window exceeded", payload["token_exhaustion_patterns"])

    def test_add_token_exhaustion_pattern_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps({"token_exhaustion_patterns": ["usage limit"]}), encoding="utf-8"
            )
            config = self._make_config(root)

            set_config_value(config, "token_exhaustion_patterns", add="usage limit")

            payload = json.loads(config_path.read_text())
            self.assertEqual(payload["token_exhaustion_patterns"].count("usage limit"), 1)

    def test_remove_token_exhaustion_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps({"token_exhaustion_patterns": ["usage limit", "quota exceeded"]}),
                encoding="utf-8",
            )
            config = self._make_config(root)

            set_config_value(config, "token_exhaustion_patterns", remove="usage limit")

            payload = json.loads(config_path.read_text())
            self.assertNotIn("usage limit", payload["token_exhaustion_patterns"])
            self.assertIn("quota exceeded", payload["token_exhaustion_patterns"])

    def test_remove_absent_pattern_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps({"token_exhaustion_patterns": ["quota exceeded"]}), encoding="utf-8"
            )
            config = self._make_config(root)

            set_config_value(config, "token_exhaustion_patterns", remove="nonexistent pattern")

            payload = json.loads(config_path.read_text())
            self.assertEqual(payload["token_exhaustion_patterns"], ["quota exceeded"])

    def test_set_list_key_with_json_array_replaces_full_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps({"token_exhaustion_patterns": ["old pattern"]}), encoding="utf-8"
            )
            config = self._make_config(root)

            set_config_value(
                config,
                "token_exhaustion_patterns",
                value='["new pattern a", "new pattern b"]',
            )

            payload = json.loads(config_path.read_text())
            self.assertEqual(payload["token_exhaustion_patterns"], ["new pattern a", "new pattern b"])

    def test_unset_list_key_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps({"token_exhaustion_patterns": ["usage limit"]}), encoding="utf-8"
            )
            config = self._make_config(root)

            set_config_value(config, "token_exhaustion_patterns", unset=True)

            payload = json.loads(config_path.read_text())
            self.assertNotIn("token_exhaustion_patterns", payload)

    # --- error cases ---

    def test_unknown_key_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._make_config(root)

            with self.assertRaises(ValueError, msg="unknown key should raise"):
                set_config_value(config, "nonexistent_key", value="x")

    def test_no_operation_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._make_config(root)

            with self.assertRaises(ValueError):
                set_config_value(config, "active_agent_cli")

    def test_multiple_operations_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._make_config(root)

            with self.assertRaises(ValueError):
                set_config_value(config, "token_exhaustion_patterns", add="a", remove="b")


if __name__ == "__main__":
    unittest.main()
