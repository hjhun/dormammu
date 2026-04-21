from __future__ import annotations

import json
from pathlib import Path

import pytest

from dormammu.agent.manifests import (
    AGENT_MANIFEST_SCHEMA_VERSION,
    AgentManifestError,
    load_agent_manifest,
    parse_agent_manifest_payload,
    parse_agent_manifest_text,
)
from dormammu.agent.permissions import PermissionDecision


def _valid_manifest_payload() -> dict[str, object]:
    return {
        "schema_version": AGENT_MANIFEST_SCHEMA_VERSION,
        "name": "project-planner",
        "description": "Project-specific planning agent.",
        "prompt": "Plan the active slice with repository context.",
        "source": "project",
        "cli": "./bin/project-planner",
        "model": "gpt-5.4",
        "permissions": {
            "tools": {
                "rules": [
                    {"tool": "shell", "decision": "deny"},
                    {"tool": "rg", "decision": "allow"},
                ]
            },
            "skills": {
                "default": "deny",
                "rules": [{"skill": "planning-agent", "decision": "allow"}],
            },
            "filesystem": {
                "rules": [
                    {
                        "path": "./workspace",
                        "decision": "allow",
                        "access": ["read", "write"],
                    }
                ]
            },
            "network": "deny",
            "worktree": {"default": "allow"},
        },
        "skills": ["planning-agent", "designing-agent", "planning-agent"],
        "metadata": {"owner": "project", "priority": 2},
    }


class TestAgentManifestParsing:
    def test_load_valid_manifest_file(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "planner.agent.json"
        manifest_path.write_text(
            json.dumps(_valid_manifest_payload()),
            encoding="utf-8",
        )

        manifest = load_agent_manifest(manifest_path)

        assert manifest.schema_version == AGENT_MANIFEST_SCHEMA_VERSION
        assert manifest.name == "project-planner"
        assert manifest.description == "Project-specific planning agent."
        assert manifest.prompt == "Plan the active slice with repository context."
        assert manifest.source == "project"
        assert manifest.cli_override == (tmp_path / "bin" / "project-planner").resolve()
        assert manifest.model_override == "gpt-5.4"
        assert manifest.permission_policy.evaluate_tool("shell") is PermissionDecision.DENY
        assert manifest.permission_policy.evaluate_tool("rg") is PermissionDecision.ALLOW
        assert (
            manifest.permission_policy.evaluate_skill("planning-agent")
            is PermissionDecision.ALLOW
        )
        assert (
            manifest.permission_policy.evaluate_skill("designing-agent")
            is PermissionDecision.DENY
        )
        assert (
            manifest.permission_policy.evaluate_filesystem(
                tmp_path / "workspace" / "note.md",
                access="write",
            )
            is PermissionDecision.ALLOW
        )
        assert manifest.permission_policy.network.default is PermissionDecision.DENY
        assert manifest.permission_policy.worktree.default is PermissionDecision.ALLOW
        assert manifest.preloaded_skills == ("planning-agent", "designing-agent")
        assert manifest.metadata == {"owner": "project", "priority": 2}

    def test_parse_payload_missing_required_field_fails_clearly(self) -> None:
        payload = _valid_manifest_payload()
        del payload["prompt"]

        with pytest.raises(
            AgentManifestError,
            match=r"agent_manifest\.prompt must be a non-empty string",
        ):
            parse_agent_manifest_payload(payload, source_name="inline manifest")

    def test_parse_payload_invalid_field_type_fails_clearly(self) -> None:
        payload = _valid_manifest_payload()
        payload["skills"] = "planning-agent"

        with pytest.raises(
            AgentManifestError,
            match=r"agent_manifest\.skills must be a JSON array",
        ):
            parse_agent_manifest_payload(payload, source_name="inline manifest")

    def test_parse_payload_rejects_unknown_top_level_fields(self) -> None:
        payload = _valid_manifest_payload()
        payload["extra"] = True

        with pytest.raises(
            AgentManifestError,
            match=r"agent_manifest contains unsupported keys \(extra\)",
        ):
            parse_agent_manifest_payload(payload, source_name="inline manifest")

    def test_parse_payload_rejects_unknown_nested_permission_policy_keys(self) -> None:
        payload = _valid_manifest_payload()
        payload["permissions"] = {"tools": {"bogus": True}}

        with pytest.raises(
            AgentManifestError,
            match=(
                r"agent_manifest\.permissions\.tools contains unsupported keys \(bogus\)"
            ),
        ):
            parse_agent_manifest_payload(payload, source_name="inline manifest")

    def test_parse_payload_rejects_unknown_nested_permission_rule_keys(self) -> None:
        payload = _valid_manifest_payload()
        payload["permissions"] = {
            "tools": {
                "rules": [
                    {
                        "tool": "shell",
                        "decision": "deny",
                        "unexpected": True,
                    }
                ]
            }
        }

        with pytest.raises(
            AgentManifestError,
            match=(
                r"agent_manifest\.permissions\.tools\.rules\[0\] "
                r"contains unsupported keys \(unexpected\)"
            ),
        ):
            parse_agent_manifest_payload(payload, source_name="inline manifest")

    def test_parse_text_reports_json_syntax_errors_with_location(self) -> None:
        with pytest.raises(
            AgentManifestError,
            match=r"Failed to parse agent manifest JSON in inline manifest: .* line 1 column",
        ):
            parse_agent_manifest_text(
                '{"schema_version": 1, "name": "planner", }',
                source_name="inline manifest",
            )

    def test_manifest_converts_to_agent_profile(self, tmp_path: Path) -> None:
        manifest = parse_agent_manifest_payload(
            _valid_manifest_payload(),
            source_name="inline manifest",
            config_root=tmp_path,
        )

        profile = manifest.to_profile()

        assert profile.name == "project-planner"
        assert profile.description == "Project-specific planning agent."
        assert profile.source == "project"
        assert profile.prompt_body == "Plan the active slice with repository context."
        assert profile.cli_override == (tmp_path / "bin" / "project-planner").resolve()
        assert profile.model_override == "gpt-5.4"
        assert profile.permission_policy.evaluate_tool("shell") is PermissionDecision.DENY
        assert profile.permission_policy.evaluate_skill("planning-agent") is PermissionDecision.ALLOW
        assert profile.preloaded_skills == ("planning-agent", "designing-agent")
        assert profile.metadata == {"owner": "project", "priority": 2}

    def test_parse_payload_rejects_invalid_source_scope(self) -> None:
        payload = _valid_manifest_payload()
        payload["source"] = "configured"

        with pytest.raises(
            AgentManifestError,
            match=r"agent_manifest\.source must be one of \(built_in, project, user\)",
        ):
            parse_agent_manifest_payload(payload, source_name="inline manifest")
