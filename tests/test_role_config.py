"""Unit tests for dormammu.agent.role_config."""
from __future__ import annotations

from pathlib import Path

import pytest

from dormammu.agent.role_config import (
    AgentsConfig,
    GOALS_OR_AUTONOMOUS_ONLY_ROLE_NAMES,
    GOALS_PRELUDE_ROLE_NAMES,
    ROLE_NAMES,
    ROLE_TAXONOMY,
    ROLE_TAXONOMY_BY_NAME,
    RoleAgentConfig,
    RUNTIME_PIPELINE_ROLE_NAMES,
    parse_agents_config,
)


# ---------------------------------------------------------------------------
# RoleAgentConfig
# ---------------------------------------------------------------------------


class TestRoleAgentConfig:
    def test_defaults(self) -> None:
        cfg = RoleAgentConfig()
        assert cfg.cli is None
        assert cfg.model is None
        assert cfg.permission_policy is None

    def test_resolve_cli_uses_own_when_set(self) -> None:
        cfg = RoleAgentConfig(cli=Path("my-cli"))
        assert cfg.resolve_cli(Path("fallback")) == Path("my-cli")

    def test_resolve_cli_falls_back_to_active(self) -> None:
        cfg = RoleAgentConfig()
        assert cfg.resolve_cli(Path("claude")) == Path("claude")

    def test_resolve_cli_returns_none_when_both_none(self) -> None:
        cfg = RoleAgentConfig()
        assert cfg.resolve_cli(None) is None

    def test_to_dict(self) -> None:
        cfg = RoleAgentConfig(cli=Path("claude"), model="claude-opus-4-5")
        d = cfg.to_dict()
        assert d["cli"] == "claude"
        assert d["model"] == "claude-opus-4-5"
        assert d["permission_policy"] is None

    def test_to_dict_none_fields(self) -> None:
        cfg = RoleAgentConfig()
        d = cfg.to_dict()
        assert d["cli"] is None
        assert d["model"] is None


# ---------------------------------------------------------------------------
# AgentsConfig
# ---------------------------------------------------------------------------


class TestAgentsConfig:
    def test_defaults(self) -> None:
        cfg = AgentsConfig()
        for role in ROLE_NAMES:
            assert cfg.for_role(role) == RoleAgentConfig()

    def test_for_role_returns_correct_config(self) -> None:
        analyzer_cfg = RoleAgentConfig(cli=Path("claude"), model="claude-opus-4-5")
        cfg = AgentsConfig(analyzer=analyzer_cfg)
        assert cfg.for_role("analyzer") is analyzer_cfg

    def test_for_role_unknown_raises(self) -> None:
        cfg = AgentsConfig()
        with pytest.raises(ValueError, match="Unknown role"):
            cfg.for_role("unknown")

    def test_to_dict_contains_all_roles(self) -> None:
        cfg = AgentsConfig()
        d = cfg.to_dict()
        assert set(d.keys()) == set(ROLE_NAMES)


# ---------------------------------------------------------------------------
# Role taxonomy
# ---------------------------------------------------------------------------


class TestRoleTaxonomy:
    def test_taxonomy_defines_role_names_once(self) -> None:
        assert tuple(entry.name for entry in ROLE_TAXONOMY) == ROLE_NAMES
        assert set(ROLE_TAXONOMY_BY_NAME) == set(ROLE_NAMES)

    def test_runtime_and_goals_role_boundaries_are_explicit(self) -> None:
        assert RUNTIME_PIPELINE_ROLE_NAMES == (
            "refiner",
            "planner",
            "developer",
            "tester",
            "reviewer",
            "committer",
        )
        assert GOALS_PRELUDE_ROLE_NAMES == ("analyzer", "planner", "designer")
        assert set(GOALS_OR_AUTONOMOUS_ONLY_ROLE_NAMES) == {
            "analyzer",
            "designer",
            "evaluator",
        }

    def test_analyzer_designer_and_planner_have_distinct_scopes(self) -> None:
        assert ROLE_TAXONOMY_BY_NAME["analyzer"].scope == "goals_autonomous_only"
        assert ROLE_TAXONOMY_BY_NAME["designer"].scope == "goals_prelude_only"
        assert ROLE_TAXONOMY_BY_NAME["planner"].scope == "runtime_and_goals_prelude"

    def test_architect_is_not_a_compatibility_alias(self) -> None:
        assert "architect" not in ROLE_NAMES
        assert "architect" not in ROLE_TAXONOMY_BY_NAME


# ---------------------------------------------------------------------------
# parse_agents_config
# ---------------------------------------------------------------------------


class TestParseAgentsConfig:
    def test_none_returns_none(self) -> None:
        assert parse_agents_config(None, config_path=None) is None

    def test_empty_object_returns_defaults(self) -> None:
        result = parse_agents_config({}, config_path=None)
        assert isinstance(result, AgentsConfig)
        for role in ROLE_NAMES:
            assert result.for_role(role) == RoleAgentConfig()

    def test_full_config(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "dormammu.json"
        payload = {
            "analyzer": {"cli": "claude", "model": "claude-sonnet-4-5"},
            "planner": {"cli": "claude", "model": "claude-opus-4-5"},
            "designer": {"model": "claude-opus-4-5"},
            "developer": {
                "cli": "claude",
                "permission_policy": {
                    "tools": {"default": "deny"},
                    "filesystem": {
                        "rules": [
                            {
                                "path": "./sandbox",
                                "decision": "allow",
                                "access": ["read", "write"],
                            }
                        ]
                    },
                },
            },
            "tester": {},
            "reviewer": {"cli": "claude", "model": "claude-sonnet-4-5"},
            "committer": {"model": "claude-haiku-4-5"},
        }
        result = parse_agents_config(payload, config_path=cfg_path)
        assert result is not None
        assert result.analyzer.cli == Path("claude")
        assert result.analyzer.model == "claude-sonnet-4-5"
        assert result.planner.cli == Path("claude")
        assert result.planner.model == "claude-opus-4-5"
        assert result.designer.cli is None
        assert result.designer.model == "claude-opus-4-5"
        assert result.developer.cli == Path("claude")
        assert result.developer.model is None
        assert result.developer.permission_policy is not None
        assert result.developer.permission_policy.tools is not None
        assert result.developer.permission_policy.tools.default is not None
        assert result.developer.permission_policy.filesystem is not None
        assert result.developer.permission_policy.filesystem.rules[0].path == (
            tmp_path / "sandbox"
        ).resolve()
        assert result.tester == RoleAgentConfig()
        assert result.reviewer.cli == Path("claude")
        assert result.committer.cli is None
        assert result.committer.model == "claude-haiku-4-5"

    def test_partial_config_uses_defaults_for_missing_roles(self) -> None:
        payload = {"planner": {"cli": "claude"}}
        result = parse_agents_config(payload, config_path=None)
        assert result is not None
        assert result.planner.cli == Path("claude")
        assert result.developer == RoleAgentConfig()

    def test_not_a_mapping_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "dormammu.json"
        with pytest.raises(RuntimeError, match="agents must be a JSON object"):
            parse_agents_config("bad", config_path=cfg_path)

    def test_role_not_a_mapping_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "dormammu.json"
        with pytest.raises(RuntimeError, match="agents.planner must be a JSON object"):
            parse_agents_config({"planner": "bad"}, config_path=cfg_path)

    def test_cli_empty_string_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "dormammu.json"
        with pytest.raises(RuntimeError, match="agents.planner.cli must be a non-empty string"):
            parse_agents_config({"planner": {"cli": ""}}, config_path=cfg_path)

    def test_model_empty_string_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "dormammu.json"
        with pytest.raises(RuntimeError, match="agents.developer.model must be a non-empty string"):
            parse_agents_config({"developer": {"model": "  "}}, config_path=cfg_path)

    def test_permission_policy_not_a_mapping_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "dormammu.json"
        with pytest.raises(
            RuntimeError,
            match="agents.planner.permission_policy must be a JSON object",
        ):
            parse_agents_config(
                {"planner": {"permission_policy": "deny"}},
                config_path=cfg_path,
            )

    def test_absolute_cli_path(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "dormammu.json"
        abs_cli = str(tmp_path / "my-agent")
        result = parse_agents_config(
            {"planner": {"cli": abs_cli}}, config_path=cfg_path
        )
        assert result is not None
        assert result.planner.cli == Path(abs_cli)

    def test_relative_dotslash_cli_resolved_against_config_dir(
        self, tmp_path: Path
    ) -> None:
        cfg_path = tmp_path / "dormammu.json"
        result = parse_agents_config(
            {"planner": {"cli": "./my-agent"}}, config_path=cfg_path
        )
        assert result is not None
        assert result.planner.cli == (tmp_path / "my-agent").resolve()

    def test_plain_name_cli_not_resolved(self, tmp_path: Path) -> None:
        """Plain command names (e.g. 'claude') stay as-is for PATH lookup."""
        cfg_path = tmp_path / "dormammu.json"
        result = parse_agents_config(
            {"planner": {"cli": "claude"}}, config_path=cfg_path
        )
        assert result is not None
        assert result.planner.cli == Path("claude")


# ---------------------------------------------------------------------------
# Integration: resolve_cli with active_agent_cli
# ---------------------------------------------------------------------------


class TestResolveCli:
    def test_all_roles_fall_back_to_active(self) -> None:
        agents = AgentsConfig()
        active = Path("claude")
        for role in ROLE_NAMES:
            assert agents.for_role(role).resolve_cli(active) == active

    def test_role_override_takes_priority(self) -> None:
        agents = AgentsConfig(
            planner=RoleAgentConfig(cli=Path("my-planner"))
        )
        active = Path("claude")
        assert agents.planner.resolve_cli(active) == Path("my-planner")
        # Other roles still fall back
        assert agents.developer.resolve_cli(active) == active

    def test_model_only_config_keeps_cli_fallback(self) -> None:
        agents = AgentsConfig(
            tester=RoleAgentConfig(model="claude-sonnet-4-5")
        )
        active = Path("claude")
        assert agents.tester.resolve_cli(active) == active
        assert agents.tester.model == "claude-sonnet-4-5"
