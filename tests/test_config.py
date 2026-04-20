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
from dormammu.agent.manifest_loader import AgentManifestLoadError
from dormammu.agent.permissions import PermissionDecision
from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig


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
            self.assertEqual(
                config.project_agent_manifests_dir,
                (root / ".dormammu" / "agent-manifests").resolve(),
            )
            self.assertEqual(
                config.user_agent_manifests_dir,
                (config.global_home_dir / "agent-manifests").resolve(),
            )

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

    def test_load_falls_back_to_temp_global_home_when_default_home_is_not_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tmpdir) / "temp-root"
            temp_root.mkdir(parents=True, exist_ok=True)
            user_fragment = str(os.getuid()) if hasattr(os, "getuid") else "default"
            expected_global_home_dir = (temp_root / f"dormammu-{user_fragment}").resolve()

            with (
                mock.patch("dormammu.config.os.access", return_value=False),
                mock.patch("dormammu.config.tempfile.gettempdir", return_value=str(temp_root)),
            ):
                config = AppConfig.load(
                    repo_root=root,
                    env={
                        "HOME": str(home_dir),
                        **{key: value for key, value in os.environ.items() if key != "HOME"},
                    },
                )

            self.assertEqual(config.global_home_dir, expected_global_home_dir)
            self.assertEqual(
                config.user_agent_manifests_dir,
                (expected_global_home_dir / "agent-manifests").resolve(),
            )

    def test_resolve_agent_profile_uses_builtin_defaults_when_agents_config_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)

            config = AppConfig.load(
                repo_root=root,
                env={
                    "HOME": str(home_dir),
                    **{key: value for key, value in os.environ.items() if key != "HOME"},
                },
            )

            profile = config.resolve_agent_profile("planner")

            self.assertEqual(profile.name, "planner")
            self.assertEqual(profile.source, "built_in")
            self.assertIsNone(profile.cli_override)
            self.assertIsNone(profile.model_override)

    def test_load_merges_global_agent_profile_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            config_path = home_dir / ".dormammu" / "config"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "cli": "claude",
                                "model": "claude-opus-4-5",
                            }
                        }
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

            profile = config.resolve_agent_profile("planner")

            self.assertEqual(profile.source, "configured")
            self.assertEqual(profile.cli_override, Path("claude"))
            self.assertEqual(profile.model_override, "claude-opus-4-5")

    def test_load_merges_project_agent_profile_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "cli": "codex",
                                "model": "gpt-5.4",
                            }
                        }
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

            profile = config.resolve_agent_profile("planner")

            self.assertEqual(profile.source, "configured")
            self.assertEqual(profile.cli_override, Path("codex"))
            self.assertEqual(profile.model_override, "gpt-5.4")

    def test_load_prefers_project_agent_profile_values_over_global_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            global_config_path = home_dir / ".dormammu" / "config"
            global_config_path.parent.mkdir(parents=True, exist_ok=True)
            global_config_path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "cli": "claude",
                                "model": "claude-opus-4-5",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "cli": "codex",
                            }
                        }
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

            profile = config.resolve_agent_profile("planner")

            self.assertEqual(profile.source, "configured")
            self.assertEqual(profile.cli_override, Path("codex"))
            self.assertEqual(profile.model_override, "claude-opus-4-5")

    def test_load_merges_global_and_project_permission_policy_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            global_config_path = home_dir / ".dormammu" / "config"
            global_config_path.parent.mkdir(parents=True, exist_ok=True)
            global_config_path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "developer": {
                                "permission_policy": {
                                    "tools": {
                                        "default": "deny",
                                        "rules": [
                                            {"tool": "shell", "decision": "allow"},
                                        ],
                                    },
                                    "network": {"default": "deny"},
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "developer": {
                                "permission_policy": {
                                    "tools": {
                                        "rules": [
                                            {"tool": "shell", "decision": "deny"},
                                            {"tool": "rg", "decision": "allow"},
                                        ]
                                    },
                                    "filesystem": {
                                        "rules": [
                                            {
                                                "path": "./workspace",
                                                "decision": "allow",
                                                "access": ["read"],
                                            }
                                        ]
                                    },
                                    "worktree": {"default": "deny"},
                                }
                            }
                        }
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

            profile = config.resolve_agent_profile("developer")

            self.assertEqual(profile.source, "configured")
            self.assertEqual(profile.permission_policy.tools.default, PermissionDecision.DENY)
            self.assertEqual(
                profile.permission_policy.evaluate_tool("shell"),
                PermissionDecision.DENY,
            )
            self.assertEqual(
                profile.permission_policy.evaluate_tool("rg"),
                PermissionDecision.ALLOW,
            )
            self.assertEqual(
                profile.permission_policy.network.default,
                PermissionDecision.DENY,
            )
            self.assertEqual(
                profile.permission_policy.evaluate_filesystem(
                    root / "workspace" / "notes.md",
                    access="read",
                ),
                PermissionDecision.ALLOW,
            )
            self.assertEqual(
                profile.permission_policy.worktree.default,
                PermissionDecision.DENY,
            )

    def test_load_preserves_active_agent_cli_behavior_when_profile_config_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps({"active_agent_cli": "/opt/tools/codex"}),
                encoding="utf-8",
            )

            config = AppConfig.load(
                repo_root=root,
                env={
                    "HOME": str(home_dir),
                    **{key: value for key, value in os.environ.items() if key != "HOME"},
                },
            )

            profile = config.resolve_agent_profile("developer")

            self.assertEqual(profile.source, "built_in")
            self.assertEqual(profile.resolve_cli(config.active_agent_cli), Path("/opt/tools/codex"))

    def test_load_surfaces_invalid_agent_permission_policy_with_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "dormammu.json"
            config_path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "developer": {
                                "permission_policy": {
                                    "filesystem": {
                                        "rules": [
                                            {
                                                "decision": "allow",
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "agents.developer.permission_policy.filesystem.rules\\[0\\]\\.path "
                f"must be a non-empty string in {config_path.resolve()}",
            ):
                AppConfig.load(repo_root=root)

    def test_load_normalizes_effective_agent_profiles_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "cli": "codex",
                                "model": "gpt-5.4",
                            }
                        }
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

            self.assertIsNotNone(config.agent_profiles)
            planner_profile = config.agent_profiles["planner"]
            self.assertEqual(planner_profile.cli_override, Path("codex"))
            self.assertEqual(planner_profile.model_override, "gpt-5.4")

    def test_load_does_not_read_unselected_malformed_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            manifest_dir = home_dir / ".dormammu" / "agent-manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            (manifest_dir / "broken.agent.json").write_text("{", encoding="utf-8")

            config = AppConfig.load(
                repo_root=root,
                env={
                    "HOME": str(home_dir),
                    **{key: value for key, value in os.environ.items() if key != "HOME"},
                },
            )

            self.assertIsNotNone(config.agent_profiles)
            profile = config.resolve_agent_profile("planner")

            self.assertEqual(profile.name, "planner")
            self.assertEqual(profile.source, "built_in")

    def test_load_resolves_project_manifest_backed_profile_for_runtime_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "profile": "planner-custom",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest_dir = root / ".dormammu" / "agent-manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            (manifest_dir / "planner.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "Project planner",
                        "prompt": "Plan from the project manifest.",
                        "source": "project",
                        "cli": "./bin/project-planner",
                        "model": "gpt-5.4",
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

            self.assertIsNotNone(config.agent_profiles)
            profile = config.agent_profiles["planner"]

            self.assertEqual(profile.name, "planner-custom")
            self.assertEqual(profile.source, "project")
            self.assertEqual(
                profile.cli_override,
                (manifest_dir / "bin" / "project-planner").resolve(),
            )
            self.assertEqual(profile.model_override, "gpt-5.4")
            self.assertEqual(
                profile.metadata["dormammu_runtime"]["manifest_scope"],
                "project",
            )

    def test_load_resolves_user_manifest_backed_profile_for_runtime_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "reviewer": {
                                "profile": "reviewer-custom",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest_dir = home_dir / ".dormammu" / "agent-manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            (manifest_dir / "reviewer.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "reviewer-custom",
                        "description": "User reviewer",
                        "prompt": "Review from the user manifest.",
                        "source": "user",
                        "model": "claude-sonnet-4-5",
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

            self.assertIsNotNone(config.agent_profiles)
            profile = config.agent_profiles["reviewer"]

            self.assertEqual(profile.name, "reviewer-custom")
            self.assertEqual(profile.source, "user")
            self.assertEqual(profile.model_override, "claude-sonnet-4-5")
            self.assertEqual(
                profile.metadata["dormammu_runtime"]["manifest_scope"],
                "user",
            )

    def test_load_prefers_project_manifest_when_project_and_user_names_collide(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "profile": "planner-custom",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            project_manifest_dir = root / ".dormammu" / "agent-manifests"
            project_manifest_dir.mkdir(parents=True, exist_ok=True)
            (project_manifest_dir / "planner.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "Project planner",
                        "prompt": "Plan from the project manifest.",
                        "source": "project",
                        "model": "gpt-5.4",
                    }
                ),
                encoding="utf-8",
            )
            user_manifest_dir = home_dir / ".dormammu" / "agent-manifests"
            user_manifest_dir.mkdir(parents=True, exist_ok=True)
            (user_manifest_dir / "planner.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "User planner",
                        "prompt": "Plan from the user manifest.",
                        "source": "user",
                        "model": "claude-opus-4-5",
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

            self.assertIsNotNone(config.agent_profiles)
            profile = config.agent_profiles["planner"]

            self.assertEqual(profile.name, "planner-custom")
            self.assertEqual(profile.source, "project")
            self.assertEqual(profile.model_override, "gpt-5.4")
            self.assertEqual(
                profile.metadata["dormammu_runtime"]["manifest_scope"],
                "project",
            )

    def test_runtime_resolution_ignores_unrelated_malformed_manifest_for_selected_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "profile": "planner-custom",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            project_manifest_dir = root / ".dormammu" / "agent-manifests"
            project_manifest_dir.mkdir(parents=True, exist_ok=True)
            (project_manifest_dir / "planner.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "Project planner",
                        "prompt": "Plan from the project manifest.",
                        "source": "project",
                        "model": "gpt-5.4",
                    }
                ),
                encoding="utf-8",
            )
            user_manifest_dir = home_dir / ".dormammu" / "agent-manifests"
            user_manifest_dir.mkdir(parents=True, exist_ok=True)
            (user_manifest_dir / "broken.agent.json").write_text("{", encoding="utf-8")

            config = AppConfig.load(
                repo_root=root,
                env={
                    "HOME": str(home_dir),
                    **{key: value for key, value in os.environ.items() if key != "HOME"},
                },
            )

            self.assertIsNotNone(config.agent_profiles)
            profile = config.agent_profiles["planner"]

            self.assertEqual(profile.name, "planner-custom")
            self.assertEqual(profile.source, "project")
            self.assertEqual(profile.model_override, "gpt-5.4")
            self.assertEqual(
                profile.metadata["dormammu_runtime"]["manifest_scope"],
                "project",
            )

    def test_runtime_resolution_reports_malformed_requested_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "profile": "planner-custom",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            project_manifest_dir = root / ".dormammu" / "agent-manifests"
            project_manifest_dir.mkdir(parents=True, exist_ok=True)
            project_manifest_path = project_manifest_dir / "planner.agent.json"
            project_manifest_path.write_text(
                (
                    "{"
                    '"schema_version": 1, '
                    '"name": "planner-custom", '
                    '"description": "Broken planner", '
                    '"prompt": "Plan from the broken project manifest.", '
                    '"source": "project", '
                    '"model": "gpt-5.4",'
                    "}"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                AgentManifestLoadError,
                rf"Failed to parse agent manifest JSON in {project_manifest_path.resolve()}: .*line 1 column",
            ):
                AppConfig.load(
                    repo_root=root,
                    env={
                        "HOME": str(home_dir),
                        **{key: value for key, value in os.environ.items() if key != "HOME"},
                    },
                )

    def test_runtime_resolution_does_not_fall_through_from_malformed_project_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "profile": "planner-custom",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            project_manifest_dir = root / ".dormammu" / "agent-manifests"
            project_manifest_dir.mkdir(parents=True, exist_ok=True)
            project_manifest_path = project_manifest_dir / "planner.agent.json"
            project_manifest_path.write_text(
                (
                    "{"
                    '"schema_version": 1, '
                    '"name": "planner-custom", '
                    '"description": "Broken planner", '
                    '"prompt": "Plan from the broken project manifest.", '
                    '"source": "project", '
                    '"model": "gpt-5.4",'
                    "}"
                ),
                encoding="utf-8",
            )
            user_manifest_dir = home_dir / ".dormammu" / "agent-manifests"
            user_manifest_dir.mkdir(parents=True, exist_ok=True)
            (user_manifest_dir / "planner.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "User planner",
                        "prompt": "Plan from the user manifest.",
                        "source": "user",
                        "model": "claude-opus-4-5",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                AgentManifestLoadError,
                rf"Failed to parse agent manifest JSON in {project_manifest_path.resolve()}: .*line 1 column",
            ):
                AppConfig.load(
                    repo_root=root,
                    env={
                        "HOME": str(home_dir),
                        **{key: value for key, value in os.environ.items() if key != "HOME"},
                    },
                )

    def test_runtime_resolution_does_not_fall_through_when_syntax_breaks_before_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "profile": "planner-custom",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            project_manifest_dir = root / ".dormammu" / "agent-manifests"
            project_manifest_dir.mkdir(parents=True, exist_ok=True)
            project_manifest_path = project_manifest_dir / "planner.agent.json"
            project_manifest_path.write_text(
                (
                    "{"
                    '"schema_version": 1, '
                    'name: "planner-custom", '
                    '"description": "Broken planner", '
                    '"prompt": "Plan from the broken project manifest.", '
                    '"source": "project"'
                    "}"
                ),
                encoding="utf-8",
            )
            user_manifest_dir = home_dir / ".dormammu" / "agent-manifests"
            user_manifest_dir.mkdir(parents=True, exist_ok=True)
            (user_manifest_dir / "planner.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "User planner",
                        "prompt": "Plan from the user manifest.",
                        "source": "user",
                        "model": "claude-opus-4-5",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                AgentManifestLoadError,
                rf"Failed to parse agent manifest JSON in {project_manifest_path.resolve()}: .*line 1 column",
            ):
                AppConfig.load(
                    repo_root=root,
                    env={
                        "HOME": str(home_dir),
                        **{key: value for key, value in os.environ.items() if key != "HOME"},
                    },
                )

    def test_load_snapshots_manifest_backed_profiles_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "agents": {
                            "planner": {
                                "profile": "planner-custom",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest_dir = root / ".dormammu" / "agent-manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "planner.agent.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "Project planner",
                        "prompt": "Plan from the project manifest.",
                        "source": "project",
                        "model": "gpt-5.4",
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

            first = config.resolve_agent_profile("planner")

            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "Mutated planner",
                        "prompt": "Plan from the mutated manifest.",
                        "source": "project",
                        "model": "claude-opus-4-5",
                    }
                ),
                encoding="utf-8",
            )

            second = config.resolve_agent_profile("planner")

            self.assertIsNotNone(config.agent_profiles)
            self.assertEqual(first.name, "planner-custom")
            self.assertEqual(first.model_override, "gpt-5.4")
            self.assertEqual(second, first)
            self.assertEqual(config.agent_profiles["planner"], first)

    def test_with_overrides_recomputes_agent_profiles_when_agents_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = AppConfig.load(repo_root=root)

            updated = config.with_overrides(
                agents=AgentsConfig(
                    reviewer=RoleAgentConfig(cli=Path("claude"), model="claude-sonnet-4-5")
                )
            )

            self.assertIsNotNone(updated.agent_profiles)
            reviewer_profile = updated.agent_profiles["reviewer"]
            self.assertEqual(reviewer_profile.cli_override, Path("claude"))
            self.assertEqual(reviewer_profile.model_override, "claude-sonnet-4-5")

    def test_with_overrides_recomputes_project_manifest_directory_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            initial_root = Path(tmpdir) / "initial-repo"
            initial_root.mkdir(parents=True, exist_ok=True)
            next_root = Path(tmpdir) / "next-repo"
            next_root.mkdir(parents=True, exist_ok=True)

            manifest_dir = next_root / ".dormammu" / "agent-manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            (manifest_dir / "planner.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "planner-custom",
                        "description": "Project planner",
                        "prompt": "Plan from the overridden project manifest.",
                        "source": "project",
                        "model": "gpt-5.4",
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=initial_root)
            updated = config.with_overrides(
                repo_root=next_root,
                agents=AgentsConfig(planner=RoleAgentConfig(profile="planner-custom")),
            )

            self.assertEqual(updated.project_agent_manifests_dir, manifest_dir.resolve())
            self.assertIsNotNone(updated.agent_profiles)
            profile = updated.agent_profiles["planner"]

            self.assertEqual(profile.name, "planner-custom")
            self.assertEqual(profile.source, "project")
            self.assertEqual(
                profile.metadata["dormammu_runtime"]["manifest_scope"],
                "project",
            )

    def test_with_overrides_recomputes_user_manifest_directory_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            next_global_home_dir = Path(tmpdir) / "alt-home" / ".dormammu"
            manifest_dir = next_global_home_dir / "agent-manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            (manifest_dir / "reviewer.agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "reviewer-custom",
                        "description": "User reviewer",
                        "prompt": "Review from the overridden user manifest.",
                        "source": "user",
                        "model": "claude-sonnet-4-5",
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
            updated = config.with_overrides(
                global_home_dir=next_global_home_dir,
                agents=AgentsConfig(reviewer=RoleAgentConfig(profile="reviewer-custom")),
            )

            self.assertEqual(updated.user_agent_manifests_dir, manifest_dir.resolve())
            self.assertIsNotNone(updated.agent_profiles)
            profile = updated.agent_profiles["reviewer"]

            self.assertEqual(profile.name, "reviewer-custom")
            self.assertEqual(profile.source, "user")
            self.assertEqual(
                profile.metadata["dormammu_runtime"]["manifest_scope"],
                "user",
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
            self.assertEqual(
                config.user_agent_manifests_dir,
                (home_dir / ".dormammu" / "agent-manifests").resolve(),
            )
            self.assertNotEqual(config.user_agent_manifests_dir.parent, config.agents_dir)


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
