from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from dormammu.agent.permissions import (
    PermissionDecision,
    parse_permission_policy_override,
)
from dormammu.agent.profiles import (
    AgentProfile,
    built_in_profiles,
    normalize_agent_profiles,
    resolve_agent_profile,
)
from dormammu.agent.role_config import AgentsConfig, ROLE_NAMES, RoleAgentConfig
from dormammu.daemon.pipeline_runner import PipelineRunner
from dormammu.loop_runner import LoopRunRequest, LoopRunner


def _make_app_config(*, active_agent_cli: Path | None, agents: AgentsConfig | None = None) -> Any:
    mock = MagicMock()
    mock.active_agent_cli = active_agent_cli
    mock.agents = agents
    mock.repo_root = Path("/tmp/repo")
    mock.base_dev_dir = Path("/tmp/repo/.dev")
    mock.agents_dir = Path("/tmp/repo/agents")
    return mock


class TestBuiltInProfiles:
    def test_load_deterministically_in_role_order(self) -> None:
        profiles = built_in_profiles()
        assert tuple(profile.name for profile in profiles) == ROLE_NAMES
        assert tuple(profile.source for profile in profiles) == ("built_in",) * len(ROLE_NAMES)
        assert built_in_profiles() == profiles

    def test_missing_optional_fields_are_safe(self) -> None:
        profile = AgentProfile(name="custom", description="Custom profile for tests.")
        assert profile.cli_override is None
        assert profile.model_override is None
        assert profile.resolve_cli(None) is None
        assert profile.permission_policy.tools.default is PermissionDecision.ASK
        assert profile.permission_policy.filesystem.default is PermissionDecision.ASK
        assert profile.permission_policy.network.default is PermissionDecision.ASK
        assert profile.worktree_policy.default is PermissionDecision.ASK


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

    def test_normalize_agent_profiles_contains_all_runtime_roles(self) -> None:
        profiles = normalize_agent_profiles(agents_config=AgentsConfig())
        assert tuple(profiles.keys()) == ROLE_NAMES


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
