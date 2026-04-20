from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dormammu.agent.manifests import (
    AgentManifestError,
    discover_agent_manifests,
    enumerate_agent_manifest_candidates,
)
from dormammu.config import AppConfig


def _make_config(repo_root: Path, home_dir: Path) -> AppConfig:
    return AppConfig.load(
        repo_root=repo_root,
        env={
            "HOME": str(home_dir),
            **{key: value for key, value in os.environ.items() if key != "HOME"},
        },
    )


def _write_manifest(
    path: Path,
    *,
    name: str,
    source: str,
    description: str | None = None,
    prompt: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": name,
                "description": description or f"{name} description",
                "prompt": prompt or f"{name} prompt",
                "source": source,
            }
        ),
        encoding="utf-8",
    )


class TestAgentManifestDiscovery:
    def test_project_only_manifests_discover_deterministically(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        _write_manifest(
            config.project_agent_manifests_dir / "zebra.agent.json",
            name="zebra",
            source="project",
        )
        _write_manifest(
            config.project_agent_manifests_dir / "nested" / "alpha.agent.json",
            name="alpha",
            source="project",
        )

        candidates = enumerate_agent_manifest_candidates(config)
        discovery = discover_agent_manifests(config)

        assert [candidate.scope for candidate in candidates] == ["project", "project"]
        assert [candidate.relative_path for candidate in candidates] == [
            "nested/alpha.agent.json",
            "zebra.agent.json",
        ]
        assert tuple(discovery.selected_by_name()) == ("alpha", "zebra")
        assert all(manifest.scope == "project" for manifest in discovery.selected)
        assert discovery.shadowed == ()

    def test_user_only_manifests_discover_when_project_scope_is_empty(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        _write_manifest(
            config.user_agent_manifests_dir / "reviewer.agent.json",
            name="reviewer-custom",
            source="user",
        )

        candidates = enumerate_agent_manifest_candidates(config)
        discovery = discover_agent_manifests(config)

        assert len(candidates) == 1
        assert candidates[0].scope == "user"
        assert candidates[0].relative_path == "reviewer.agent.json"
        assert tuple(discovery.selected_by_name()) == ("reviewer-custom",)
        assert discovery.selected[0].scope == "user"
        assert discovery.shadowed == ()

    def test_project_scope_overrides_user_scope_for_duplicate_names(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        _write_manifest(
            config.user_agent_manifests_dir / "planner.agent.json",
            name="planner-custom",
            source="user",
            description="user version",
        )
        _write_manifest(
            config.project_agent_manifests_dir / "planner.agent.json",
            name="planner-custom",
            source="project",
            description="project version",
        )

        discovery = discover_agent_manifests(config)
        selected = discovery.selected_by_name()["planner-custom"]

        assert selected.scope == "project"
        assert selected.path == (
            config.project_agent_manifests_dir / "planner.agent.json"
        ).resolve()
        assert len(discovery.shadowed) == 1
        assert discovery.shadowed[0].scope == "user"
        assert discovery.shadowed[0].path == (
            config.user_agent_manifests_dir / "planner.agent.json"
        ).resolve()

    def test_discovery_rejects_manifest_when_declared_source_disagrees_with_scope(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        _write_manifest(
            config.project_agent_manifests_dir / "planner.agent.json",
            name="planner-custom",
            source="user",
        )

        with pytest.raises(
            AgentManifestError,
            match=(
                r"Agent manifest source/scope mismatch .* declared source 'user' "
                r"does not match discovered scope 'project'"
            ),
        ):
            discover_agent_manifests(config)

    def test_duplicate_names_within_same_scope_fail_clearly(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        _write_manifest(
            config.project_agent_manifests_dir / "alpha.agent.json",
            name="shared-name",
            source="project",
        )
        _write_manifest(
            config.project_agent_manifests_dir / "nested" / "beta.agent.json",
            name="shared-name",
            source="project",
        )

        with pytest.raises(
            AgentManifestError,
            match=r"Duplicate agent manifest name 'shared-name' in project scope",
        ):
            discover_agent_manifests(config)

    def test_missing_and_empty_manifest_directories_are_stable_noops(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        config = _make_config(repo_root, home_dir)

        initial = discover_agent_manifests(config)

        assert initial.candidates == ()
        assert initial.selected == ()
        assert initial.shadowed == ()

        config.project_agent_manifests_dir.mkdir(parents=True, exist_ok=True)
        config.user_agent_manifests_dir.mkdir(parents=True, exist_ok=True)

        empty = discover_agent_manifests(config)

        assert empty.candidates == ()
        assert empty.selected == ()
        assert empty.shadowed == ()
