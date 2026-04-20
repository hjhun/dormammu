from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dormammu.agent.permissions import (
    PermissionDecision,
    parse_permission_policy_override,
)
from dormammu.agent.manifest_loader import LoadedAgentDefinition
from dormammu.agent.profiles import (
    AgentProfile,
    PROFILE_RUNTIME_METADATA_KEY,
    built_in_profile_for_role,
    built_in_profiles,
    normalize_agent_profiles,
    resolve_agent_profile,
    resolve_runtime_role_profile,
)
from dormammu.agent.role_config import AgentsConfig, ROLE_NAMES, RoleAgentConfig
from dormammu.daemon.pipeline_runner import PipelineRunner
from dormammu.loop_runner import LoopRunRequest, LoopRunner


def _manifest_definition(
    *,
    name: str,
    source: str = "project",
) -> LoadedAgentDefinition:
    return LoadedAgentDefinition(
        name=name,
        description=f"{name} description",
        prompt_body=f"{name} prompt",
        source=source,
        manifest_scope=source,
        manifest_path=Path(f"/tmp/{name}.agent.json"),
        cli_override=Path(f"/opt/{name}"),
        model_override=f"{name}-model",
    )


def _make_app_config(*, active_agent_cli: Path | None, agents: AgentsConfig | None = None) -> Any:
    mock = MagicMock()
    mock.active_agent_cli = active_agent_cli
    mock.agents = agents
    mock.repo_root = Path("/tmp/repo")
    mock.base_dev_dir = Path("/tmp/repo/.dev")
    mock.agents_dir = Path("/tmp/repo/agents")
    mock.resolve_agent_profile.side_effect = lambda role: resolve_agent_profile(
        role,
        agents_config=agents,
    )
    return mock


class TestBuiltInProfiles:
    def test_load_deterministically_in_role_order(self) -> None:
        profiles = built_in_profiles()
        assert tuple(profile.name for profile in profiles) == ROLE_NAMES
        assert tuple(profile.source for profile in profiles) == ("built_in",) * len(ROLE_NAMES)
        assert built_in_profiles() == profiles

    def test_missing_optional_fields_are_safe(self) -> None:
        profile = AgentProfile(name="custom", description="Custom profile for tests.")
        assert profile.prompt_body is None
        assert profile.cli_override is None
        assert profile.model_override is None
        assert profile.resolve_cli(None) is None
        assert profile.permission_policy.tools.default is PermissionDecision.ASK
        assert profile.permission_policy.filesystem.default is PermissionDecision.ASK
        assert profile.permission_policy.network.default is PermissionDecision.ASK
        assert profile.worktree_policy.default is PermissionDecision.ASK
        assert profile.preloaded_skills == ()
        assert profile.metadata == {}

    def test_each_builtin_role_exposes_default_permission_foundation(self) -> None:
        for role in ROLE_NAMES:
            profile = built_in_profile_for_role(role)

            assert profile.name == role
            assert profile.source == "built_in"
            assert profile.permission_policy.tools.default is PermissionDecision.ASK
            assert profile.permission_policy.filesystem.default is PermissionDecision.ASK
            assert profile.permission_policy.network.default is PermissionDecision.ASK
            assert profile.permission_policy.worktree.default is PermissionDecision.ASK
            assert profile.permission_policy.tools.rules == ()
            assert profile.permission_policy.filesystem.rules == ()
            assert profile.permission_policy.network.rules == ()
            assert profile.permission_policy.worktree.rules == ()


class TestProfileNormalization:
    def test_existing_role_config_resolves_into_profile(self) -> None:
        agents = AgentsConfig(
            planner=RoleAgentConfig(cli=Path("claude"), model="claude-opus-4-5")
        )

        profile = resolve_agent_profile("planner", agents_config=agents)

        assert profile.name == "planner"
        assert profile.source == "configured"
        assert profile.cli_override == Path("claude")
        assert profile.model_override == "claude-opus-4-5"
        assert profile.resolve_cli(Path("codex")) == Path("claude")

    def test_missing_role_overrides_still_resolve_with_active_cli_fallback(self) -> None:
        profile = resolve_agent_profile("reviewer", agents_config=AgentsConfig())

        assert profile.name == "reviewer"
        assert profile.source == "built_in"
        assert profile.cli_override is None
        assert profile.model_override is None
        assert profile.resolve_cli(Path("codex")) == Path("codex")

    def test_role_permission_policy_override_merges_with_builtin_defaults(self) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(
                permission_policy=parse_permission_policy_override(
                    {
                        "tools": {"rules": [{"tool": "shell", "decision": "deny"}]},
                        "network": "deny",
                    },
                    config_root=None,
                    field_name="agents.developer.permission_policy",
                    source="dormammu.json",
                )
            )
        )

        profile = resolve_agent_profile("developer", agents_config=agents)

        assert profile.source == "configured"
        assert profile.permission_policy.evaluate_tool("shell") is PermissionDecision.DENY
        assert profile.permission_policy.network.default is PermissionDecision.DENY
        assert profile.permission_policy.filesystem.default is PermissionDecision.ASK

    def test_partial_permission_override_keeps_unconfigured_dimensions_on_builtin_defaults(self) -> None:
        agents = AgentsConfig(
            reviewer=RoleAgentConfig(
                permission_policy=parse_permission_policy_override(
                    {
                        "filesystem": {
                            "rules": [
                                {
                                    "path": "/tmp/reports",
                                    "decision": "allow",
                                    "access": ["read"],
                                }
                            ]
                        },
                        "worktree": {"default": "deny"},
                    },
                    config_root=None,
                    field_name="agents.reviewer.permission_policy",
                    source="dormammu.json",
                )
            )
        )

        profile = resolve_agent_profile("reviewer", agents_config=agents)

        assert profile.source == "configured"
        assert profile.permission_policy.filesystem.rules[0].path == Path("/tmp/reports")
        assert profile.permission_policy.evaluate_filesystem(
            "/tmp/reports/checklist.md",
            access="read",
        ) is PermissionDecision.ALLOW
        assert profile.permission_policy.tools.default is PermissionDecision.ASK
        assert profile.permission_policy.network.default is PermissionDecision.ASK
        assert profile.permission_policy.worktree.default is PermissionDecision.DENY

    def test_normalize_agent_profiles_contains_all_runtime_roles(self) -> None:
        profiles = normalize_agent_profiles(agents_config=AgentsConfig())
        assert tuple(profiles.keys()) == ROLE_NAMES

    def test_invalid_runtime_role_mapping_fails_clearly(self) -> None:
        agents = AgentsConfig(planner=RoleAgentConfig(profile="missing-profile"))
        with pytest.raises(
            ValueError,
            match="maps to profile 'missing-profile', but no effective profile",
        ):
            resolve_runtime_role_profile("planner", agents_config=agents)

    def test_runtime_role_can_select_manifest_backed_profile(self) -> None:
        definition = _manifest_definition(name="planner-custom")
        agents = AgentsConfig(planner=RoleAgentConfig(profile="planner-custom"))

        profile = resolve_agent_profile(
            "planner",
            agents_config=agents,
            manifest_definitions=(definition,),
        )

        assert profile.name == "planner-custom"
        assert profile.source == "project"
        assert profile.cli_override == Path("/opt/planner-custom")
        assert profile.model_override == "planner-custom-model"
        assert profile.metadata[PROFILE_RUNTIME_METADATA_KEY] == {
            "runtime_role": "planner",
            "selected_profile_name": "planner-custom",
            "selected_profile_source": "project",
            "selected_via_role_config": True,
            "role_overrides": {
                "cli": False,
                "model": False,
                "permission_policy": False,
            },
            "manifest_scope": "project",
            "manifest_path": "/tmp/planner-custom.agent.json",
        }

    def test_role_overrides_apply_on_top_of_selected_manifest_profile(self) -> None:
        definition = _manifest_definition(name="reviewer-custom", source="user")
        agents = AgentsConfig(
            reviewer=RoleAgentConfig(
                profile="reviewer-custom",
                cli=Path("codex"),
                model="gpt-5.4",
            )
        )

        profile = resolve_agent_profile(
            "reviewer",
            agents_config=agents,
            manifest_definitions=(definition,),
        )

        assert profile.name == "reviewer-custom"
        assert profile.source == "configured"
        assert profile.cli_override == Path("codex")
        assert profile.model_override == "gpt-5.4"
        assert profile.metadata[PROFILE_RUNTIME_METADATA_KEY]["selected_profile_source"] == "user"
        assert profile.metadata[PROFILE_RUNTIME_METADATA_KEY]["manifest_scope"] == "user"


class TestRuntimeProfileResolution:
    def test_loop_and_pipeline_use_the_same_developer_profile_resolution(self) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("codex"), model="gpt-5.4")
        )
        config = _make_app_config(active_agent_cli=Path("claude"), agents=agents)

        loop_runner = LoopRunner(
            config,
            repository=MagicMock(),
            adapter=MagicMock(),
            supervisor=MagicMock(),
        )
        loop_profile = loop_runner.resolve_agent_profile(
            LoopRunRequest(
                cli_path=Path("codex"),
                prompt_text="Implement the active slice.",
                repo_root=Path("/tmp/repo"),
            )
        )

        pipeline_runner = PipelineRunner(
            config,
            agents,
            repository=MagicMock(),
            progress_stream=io.StringIO(),
        )
        pipeline_profile = pipeline_runner._profile_for_role("developer")

        assert loop_profile == pipeline_profile
        assert loop_profile.resolve_cli(config.active_agent_cli) == Path("codex")
        assert loop_profile.model_override == "gpt-5.4"

    def test_loop_and_pipeline_share_manifest_backed_role_resolution(self) -> None:
        definition = _manifest_definition(name="developer-custom")
        agents = AgentsConfig(developer=RoleAgentConfig(profile="developer-custom"))
        config = _make_app_config(active_agent_cli=Path("claude"), agents=agents)
        config.resolve_agent_profile.side_effect = lambda role: resolve_agent_profile(
            role,
            agents_config=agents,
            manifest_definitions=(definition,),
        )

        loop_runner = LoopRunner(
            config,
            repository=MagicMock(),
            adapter=MagicMock(),
            supervisor=MagicMock(),
        )
        loop_profile = loop_runner.resolve_agent_profile(
            LoopRunRequest(
                cli_path=Path("codex"),
                prompt_text="Implement the active slice.",
                repo_root=Path("/tmp/repo"),
            )
        )

        pipeline_runner = PipelineRunner(
            config,
            agents,
            repository=MagicMock(),
            progress_stream=io.StringIO(),
        )
        pipeline_profile = pipeline_runner._profile_for_role("developer")

        assert loop_profile == pipeline_profile
        assert loop_profile.name == "developer-custom"
        assert loop_profile.source == "project"
        assert loop_profile.resolve_cli(config.active_agent_cli) == Path("/opt/developer-custom")
