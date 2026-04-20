from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dormammu.agent.manifest_loader import (
    AgentManifestLoadError,
    load_agent_manifest_definitions,
)
from dormammu.agent.permissions import PermissionDecision
from dormammu.config import AppConfig


def _make_config(repo_root: Path, home_dir: Path) -> AppConfig:
    return AppConfig.load(
        repo_root=repo_root,
        env={
            "HOME": str(home_dir),
            **{key: value for key, value in os.environ.items() if key != "HOME"},
        },
    )


def _write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _base_manifest_payload(
    *,
    name: str,
    source: str,
    description: str | None = None,
    prompt: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": name,
        "description": description or f"{name} description",
        "prompt": prompt or f"{name} prompt",
        "source": source,
    }


class TestAgentManifestLoader:
    def test_loads_multiple_manifests_into_runtime_ready_definitions(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        project_manifest_path = _write_manifest(
            config.project_agent_manifests_dir / "nested" / "planner.agent.json",
            {
                **_base_manifest_payload(
                    name="planner-custom",
                    source="project",
                    description="Project planner",
                    prompt="Plan from the project manifest.",
                ),
                "cli": "../bin/project-planner",
                "model": "gpt-5.4",
                "permissions": {
                    "filesystem": {
                        "rules": [
                            {
                                "path": "../workspace",
                                "decision": "allow",
                                "access": ["read", "write"],
                            }
                        ]
                    }
                },
                "skills": ["planning-agent", "designing-agent"],
                "metadata": {"owner": "project"},
            },
        )
        user_manifest_path = _write_manifest(
            config.user_agent_manifests_dir / "reviewer.agent.json",
            _base_manifest_payload(
                name="reviewer-custom",
                source="user",
                description="User reviewer",
                prompt="Review from the user manifest.",
            ),
        )

        loaded = config.load_agent_manifest_definitions()
        definitions = loaded.definitions_by_name()

        assert tuple(definitions) == ("planner-custom", "reviewer-custom")
        assert loaded.discovery.shadowed == ()

        planner = definitions["planner-custom"]
        assert planner.manifest_scope == "project"
        assert planner.manifest_path == project_manifest_path.resolve()
        assert planner.source == "project"
        assert planner.cli_override == (
            config.project_agent_manifests_dir / "bin" / "project-planner"
        ).resolve()
        assert (
            planner.permission_policy.evaluate_filesystem(
                config.project_agent_manifests_dir / "workspace" / "notes.md",
                access="write",
            )
            is PermissionDecision.ALLOW
        )
        assert planner.preloaded_skills == ("planning-agent", "designing-agent")
        assert planner.metadata == {"owner": "project"}

        profile = planner.to_profile()
        assert profile.name == "planner-custom"
        assert profile.prompt_body == "Plan from the project manifest."
        assert profile.cli_override == (
            config.project_agent_manifests_dir / "bin" / "project-planner"
        ).resolve()

        reviewer = definitions["reviewer-custom"]
        assert reviewer.manifest_scope == "user"
        assert reviewer.manifest_path == user_manifest_path.resolve()
        assert reviewer.source == "user"

    def test_loader_preserves_project_over_user_precedence_metadata(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        user_manifest_path = _write_manifest(
            config.user_agent_manifests_dir / "planner.agent.json",
            _base_manifest_payload(
                name="planner-custom",
                source="user",
                description="User planner",
            ),
        )
        project_manifest_path = _write_manifest(
            config.project_agent_manifests_dir / "planner.agent.json",
            _base_manifest_payload(
                name="planner-custom",
                source="project",
                description="Project planner",
            ),
        )

        loaded = load_agent_manifest_definitions(config)

        assert tuple(loaded.definitions_by_name()) == ("planner-custom",)
        assert loaded.definitions[0].manifest_path == project_manifest_path.resolve()
        assert len(loaded.discovery.shadowed) == 1
        assert loaded.discovery.shadowed[0].path == user_manifest_path.resolve()

    def test_loader_reports_malformed_manifest_content_with_manifest_path(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        manifest_path = config.project_agent_manifests_dir / "broken.agent.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            '{"schema_version": 1, "name": "broken", }',
            encoding="utf-8",
        )

        with pytest.raises(
            AgentManifestLoadError,
            match=(
                rf"Failed to parse agent manifest JSON in {manifest_path.resolve()}: .*"
                r"line 1 column"
            ),
        ):
            load_agent_manifest_definitions(config)

    def test_loader_reports_field_specific_validation_errors_clearly(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        manifest_path = _write_manifest(
            config.project_agent_manifests_dir / "planner.agent.json",
            {
                **_base_manifest_payload(name="planner-custom", source="project"),
                "permissions": {
                    "filesystem": {
                        "rules": [
                            {
                                "path": "",
                                "decision": "allow",
                            }
                        ]
                    }
                },
            },
        )

        with pytest.raises(
            AgentManifestLoadError,
            match=(
                rf"agent_manifest\.permissions\.filesystem\.rules\[0\]\.path "
                rf"must be a non-empty string in {manifest_path.resolve()}"
            ),
        ):
            load_agent_manifest_definitions(config)
