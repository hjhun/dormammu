from __future__ import annotations

import os
from pathlib import Path

import pytest

from dormammu.agent.permissions import (
    AgentPermissionPolicy,
    AgentPermissionPolicyOverride,
    FilesystemPermissionPolicy,
    FilesystemPermissionPolicyOverride,
    FilesystemPermissionRule,
    NetworkPermissionPolicy,
    NetworkPermissionPolicyOverride,
    NetworkPermissionRule,
    PermissionDecision,
    SkillPermissionPolicy,
    SkillPermissionPolicyOverride,
    SkillPermissionRule,
    ToolPermissionPolicy,
    ToolPermissionPolicyOverride,
    ToolPermissionRule,
    WorktreePermissionPolicy,
    WorktreePermissionPolicyOverride,
    WorktreePermissionRule,
    merge_permission_policy,
    parse_permission_policy_override,
)


class TestAgentPermissionPolicy:
    def test_named_policies_use_explicit_allow_deny_ask_semantics(self) -> None:
        policy = AgentPermissionPolicy(
            tools=ToolPermissionPolicy(
                default=PermissionDecision.ASK,
                rules=(
                    ToolPermissionRule("shell", PermissionDecision.ALLOW),
                    ToolPermissionRule("deploy", PermissionDecision.DENY),
                ),
            ),
            skills=SkillPermissionPolicy(
                default=PermissionDecision.ASK,
                rules=(SkillPermissionRule("planning-agent", PermissionDecision.DENY),),
            ),
            network=NetworkPermissionPolicy(
                default=PermissionDecision.DENY,
                rules=(NetworkPermissionRule("api.example.com", PermissionDecision.ASK),),
            ),
            worktree=WorktreePermissionPolicy(
                default=PermissionDecision.ASK,
                rules=(WorktreePermissionRule("create", PermissionDecision.ALLOW),),
            ),
        )

        assert policy.evaluate_tool("shell") is PermissionDecision.ALLOW
        assert policy.evaluate_tool("unknown") is PermissionDecision.ASK
        assert policy.evaluate_skill("planning-agent") is PermissionDecision.DENY
        assert policy.evaluate_skill("designing-agent") is PermissionDecision.ASK
        assert policy.evaluate_network("api.example.com") is PermissionDecision.ASK
        assert policy.evaluate_network("other.example.com") is PermissionDecision.DENY
        assert policy.evaluate_worktree("create") is PermissionDecision.ALLOW
        assert policy.evaluate_worktree("reuse") is PermissionDecision.ASK

    def test_filesystem_policy_prefers_more_specific_matching_path(self, tmp_path: Path) -> None:
        root = tmp_path / "workspace"
        project = root / "project"
        secret = project / "secret"
        policy = FilesystemPermissionPolicy(
            default=PermissionDecision.ASK,
            rules=(
                FilesystemPermissionRule(root, PermissionDecision.ALLOW, access=("read",)),
                FilesystemPermissionRule(project, PermissionDecision.DENY, access=("write",)),
                FilesystemPermissionRule(secret, PermissionDecision.ALLOW, access=("write",)),
            ),
        )

        assert policy.evaluate(project / "notes.txt", access="read") is PermissionDecision.ALLOW
        assert policy.evaluate(project / "notes.txt", access="write") is PermissionDecision.DENY
        assert policy.evaluate(secret / "notes.txt", access="write") is PermissionDecision.ALLOW
        assert policy.evaluate(tmp_path / "outside.txt", access="read") is PermissionDecision.ASK

    def test_filesystem_policy_uses_last_matching_rule_for_equal_specificity(
        self,
        tmp_path: Path,
    ) -> None:
        project = tmp_path / "project"
        policy = FilesystemPermissionPolicy(
            default=PermissionDecision.ASK,
            rules=(
                FilesystemPermissionRule(project, PermissionDecision.ALLOW, access=("read",)),
                FilesystemPermissionRule(project, PermissionDecision.DENY, access=("read",)),
            ),
        )

        assert (
            policy.evaluate(project / "notes.txt", access="read")
            is PermissionDecision.DENY
        )

    def test_filesystem_policy_requires_explicit_root_for_relative_requests(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = (tmp_path / "workspace").resolve()
        project = workspace / "project"
        other = (tmp_path / "other").resolve()
        project.mkdir(parents=True)
        other.mkdir()
        policy = FilesystemPermissionPolicy(
            default=PermissionDecision.ASK,
            rules=(
                FilesystemPermissionRule(project, PermissionDecision.ALLOW, access=("read",)),
            ),
        )

        original_cwd = Path.cwd()
        try:
            os.chdir(project)
            assert policy.evaluate("notes.txt", access="read") is PermissionDecision.ASK
            assert (
                policy.evaluate(
                    "notes.txt",
                    access="read",
                    evaluation_root=project,
                )
                is PermissionDecision.ALLOW
            )

            os.chdir(other)
            assert policy.evaluate("notes.txt", access="read") is PermissionDecision.ASK
            assert (
                policy.evaluate(
                    "notes.txt",
                    access="read",
                    evaluation_root=project,
                )
                is PermissionDecision.ALLOW
            )
        finally:
            os.chdir(original_cwd)

    def test_merge_permission_policy_uses_override_defaults_and_rules(self) -> None:
        base = AgentPermissionPolicy(
            tools=ToolPermissionPolicy(
                default=PermissionDecision.ASK,
                rules=(ToolPermissionRule("shell", PermissionDecision.ALLOW),),
            ),
            skills=SkillPermissionPolicy(
                default=PermissionDecision.ASK,
                rules=(SkillPermissionRule("planning-agent", PermissionDecision.ALLOW),),
            ),
            filesystem=FilesystemPermissionPolicy(default=PermissionDecision.DENY),
            network=NetworkPermissionPolicy(default=PermissionDecision.DENY),
            worktree=WorktreePermissionPolicy(default=PermissionDecision.ASK),
        )
        override = AgentPermissionPolicyOverride(
            tools=ToolPermissionPolicyOverride(
                rules=(ToolPermissionRule("shell", PermissionDecision.DENY),)
            ),
            skills=SkillPermissionPolicyOverride(
                default=PermissionDecision.DENY,
                rules=(SkillPermissionRule("designing-agent", PermissionDecision.ALLOW),),
            ),
            filesystem=FilesystemPermissionPolicyOverride(default=PermissionDecision.ASK),
            network=NetworkPermissionPolicyOverride(
                rules=(NetworkPermissionRule("api.example.com", PermissionDecision.ALLOW),)
            ),
            worktree=WorktreePermissionPolicyOverride(default=PermissionDecision.DENY),
        )

        merged = merge_permission_policy(base, override)

        assert merged.evaluate_tool("shell") is PermissionDecision.DENY
        assert merged.evaluate_skill("planning-agent") is PermissionDecision.ALLOW
        assert merged.evaluate_skill("designing-agent") is PermissionDecision.ALLOW
        assert merged.evaluate_skill("reviewer-custom") is PermissionDecision.DENY
        assert merged.evaluate_filesystem("/tmp/example", access="read") is PermissionDecision.ASK
        assert merged.evaluate_network("api.example.com") is PermissionDecision.ALLOW
        assert merged.evaluate_network("other.example.com") is PermissionDecision.DENY
        assert merged.evaluate_worktree("create") is PermissionDecision.DENY

    def test_parse_permission_policy_override_resolves_relative_filesystem_paths(
        self,
        tmp_path: Path,
    ) -> None:
        override = parse_permission_policy_override(
            {
                "tools": "deny",
                "skills": {
                    "default": "deny",
                    "rules": [{"skill": "planning-agent", "decision": "allow"}],
                },
                "filesystem": {
                    "default": "ask",
                    "rules": [
                        {
                            "path": "./sandbox",
                            "access": ["read", "write"],
                            "decision": "allow",
                        }
                    ],
                },
                "network": {"rules": [{"host": "api.example.com", "decision": "allow"}]},
                "worktree": {"default": "deny"},
            },
            config_root=tmp_path,
            field_name="agents.developer.permission_policy",
            source="dormammu.json",
        )

        assert override.tools is not None
        assert override.tools.default is PermissionDecision.DENY
        assert override.skills is not None
        assert override.skills.default is PermissionDecision.DENY
        assert override.skills.rules[0].skill == "planning-agent"
        assert override.filesystem is not None
        assert override.filesystem.rules[0].path == (tmp_path / "sandbox").resolve()
        assert override.network is not None
        assert override.network.rules[0].host == "api.example.com"
        assert override.worktree is not None
        assert override.worktree.default is PermissionDecision.DENY

    def test_parse_permission_policy_override_rejects_unknown_nested_policy_keys(self) -> None:
        with pytest.raises(
            RuntimeError,
            match=r"agents\.developer\.permission_policy\.tools contains unsupported keys \(bogus\)",
        ):
            parse_permission_policy_override(
                {"tools": {"bogus": True}},
                config_root=None,
                field_name="agents.developer.permission_policy",
                source="dormammu.json",
            )

    def test_parse_permission_policy_override_rejects_unknown_rule_keys(self) -> None:
        with pytest.raises(
            RuntimeError,
            match=(
                r"agents\.developer\.permission_policy\.filesystem\.rules\[0\] "
                r"contains unsupported keys \(unexpected\)"
            ),
        ):
            parse_permission_policy_override(
                {
                    "filesystem": {
                        "rules": [
                            {
                                "path": "/tmp/workspace",
                                "decision": "allow",
                                "unexpected": "value",
                            }
                        ]
                    }
                },
                config_root=None,
                field_name="agents.developer.permission_policy",
                source="dormammu.json",
            )
