from __future__ import annotations

import os
from pathlib import Path

import pytest

from dormammu.config import AppConfig
from dormammu.skills import (
    SKILL_CONTENT_MODE_INLINE_MARKDOWN,
    SKILL_DOCUMENT_SCHEMA_VERSION,
    SKILL_SOURCE_PRECEDENCE,
    SkillDiscoveryError,
    SkillDocumentError,
    discover_skills,
    enumerate_skill_candidates,
    load_skill_definition,
    load_skill_document,
    normalize_skill_source_scope,
    parse_skill_document_payload,
    parse_skill_document_text,
    skill_search_roots,
)

ROOT = Path(__file__).resolve().parents[1]


def _valid_skill_text() -> str:
    return """---
schema_version: 1
name: phase5-custom-skill
description: Project-specific skill for Phase 5 parsing tests.
metadata: {"visibility": "profile_scoped", "tags": ["phase5", "skill"]}
---

# Phase 5 Custom Skill

Use this skill to validate the runtime skill parser.
"""


def _valid_skill_payload() -> dict[str, object]:
    return {
        "schema_version": SKILL_DOCUMENT_SCHEMA_VERSION,
        "name": "phase5-custom-skill",
        "description": "Project-specific skill for Phase 5 parsing tests.",
        "metadata": {"visibility": "profile_scoped", "tags": ["phase5", "skill"]},
    }


def _make_config(repo_root: Path, home_dir: Path) -> AppConfig:
    return AppConfig.load(
        repo_root=repo_root,
        env={
            "HOME": str(home_dir),
            **{key: value for key, value in os.environ.items() if key != "HOME"},
        },
    )


def _write_skill(path: Path, *, name: str, description: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema_version: 1
name: {name}
description: {description or f"{name} description"}
metadata: {{"visibility": "profile_scoped"}}
---

# {name}

Use this skill in discovery tests.
""",
        encoding="utf-8",
    )


class TestSkillDocumentParsing:
    def test_parse_valid_skill_text(self) -> None:
        document = parse_skill_document_text(
            _valid_skill_text(),
            source_name="inline skill",
        )

        assert document.schema_version == SKILL_DOCUMENT_SCHEMA_VERSION
        assert document.name == "phase5-custom-skill"
        assert document.description == "Project-specific skill for Phase 5 parsing tests."
        assert document.content.mode == SKILL_CONTENT_MODE_INLINE_MARKDOWN
        assert document.content.text.startswith("# Phase 5 Custom Skill")
        assert document.metadata == {
            "visibility": "profile_scoped",
            "tags": ["phase5", "skill"],
        }

    def test_parse_payload_missing_required_field_fails_clearly(self) -> None:
        payload = _valid_skill_payload()
        del payload["description"]

        with pytest.raises(
            SkillDocumentError,
            match=r"skill_document\.description must be a non-empty string",
        ):
            parse_skill_document_payload(
                payload,
                source_name="inline skill",
                body="# Skill\n\nBody",
            )

    def test_parse_payload_invalid_field_type_fails_clearly(self) -> None:
        payload = _valid_skill_payload()
        payload["metadata"] = "profile_scoped"

        with pytest.raises(
            SkillDocumentError,
            match=r"skill_document\.metadata must be a JSON object",
        ):
            parse_skill_document_payload(
                payload,
                source_name="inline skill",
                body="# Skill\n\nBody",
            )

    def test_load_skill_document_rejects_non_skill_filenames(self, tmp_path: Path) -> None:
        path = tmp_path / "AGENTS.md"
        path.write_text(_valid_skill_text(), encoding="utf-8")

        with pytest.raises(
            SkillDocumentError,
            match=r"Skill documents must be named SKILL\.md",
        ):
            load_skill_document(path)

    def test_normalize_skill_source_scope(self) -> None:
        assert (
            normalize_skill_source_scope(
                " Project ",
                field_name="skill.source_scope",
                source_name="inline skill",
            )
            == "project"
        )

    def test_invalid_skill_source_scope_fails_clearly(self) -> None:
        with pytest.raises(
            SkillDocumentError,
            match=r"skill\.source_scope must be one of \(built_in, project, user\)",
        ):
            normalize_skill_source_scope(
                "configured",
                field_name="skill.source_scope",
                source_name="inline skill",
            )

    def test_mapping_from_disk_to_runtime_skill_definition(self, tmp_path: Path) -> None:
        path = tmp_path / "agents" / "skills" / "phase5-custom-skill" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_valid_skill_text(), encoding="utf-8")

        loaded = load_skill_definition(path, source_scope="Project")

        assert loaded.name == "phase5-custom-skill"
        assert loaded.description == "Project-specific skill for Phase 5 parsing tests."
        assert loaded.source_scope == "project"
        assert loaded.source_path == path.resolve()
        assert loaded.source_precedence == SKILL_SOURCE_PRECEDENCE["project"]
        assert loaded.content.mode == SKILL_CONTENT_MODE_INLINE_MARKDOWN
        assert loaded.content.text.startswith("# Phase 5 Custom Skill")
        assert loaded.metadata == {
            "visibility": "profile_scoped",
            "tags": ["phase5", "skill"],
        }

    def test_existing_packaged_skill_layout_loads_without_schema_version(self) -> None:
        planning_skill = ROOT / "agents" / "skills" / "planning-agent" / "SKILL.md"

        loaded = load_skill_definition(planning_skill, source_scope="built_in")

        assert loaded.name == "planning-agent"
        assert loaded.schema_version == SKILL_DOCUMENT_SCHEMA_VERSION
        assert loaded.source_scope == "built_in"
        assert loaded.content.mode == SKILL_CONTENT_MODE_INLINE_MARKDOWN
        assert "Use this skill when the next useful action is planning" in loaded.content.text


class TestSkillDiscovery:
    def _config_with_built_in_root(
        self,
        *,
        repo_root: Path,
        home_dir: Path,
        built_in_agents_dir: Path,
    ) -> AppConfig:
        config = _make_config(repo_root, home_dir)
        return config.with_overrides(
            built_in_agents_dir=built_in_agents_dir.resolve(),
            built_in_skills_dir=(built_in_agents_dir / "skills").resolve(),
        )

    def test_project_only_skills_discover_deterministically(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        built_in_agents_dir = tmp_path / "built-in-agents"
        config = self._config_with_built_in_root(
            repo_root=repo_root,
            home_dir=home_dir,
            built_in_agents_dir=built_in_agents_dir,
        )

        _write_skill(
            config.project_skills_dir / "alpha" / "SKILL.md",
            name="alpha-skill",
        )

        roots = skill_search_roots(config)
        candidates = enumerate_skill_candidates(config)
        discovery = discover_skills(config)

        assert [root.scope for root in roots] == ["project", "user", "built_in"]
        assert [root.path for root in roots] == [
            config.project_skills_dir,
            config.user_skills_dir,
            config.built_in_skills_dir,
        ]
        assert [candidate.scope for candidate in candidates] == ["project"]
        assert [candidate.relative_path for candidate in candidates] == ["alpha/SKILL.md"]
        assert tuple(discovery.selected_by_name()) == ("alpha-skill",)
        assert discovery.selected[0].scope == "project"
        assert discovery.shadowed == ()

    def test_user_only_skills_discover_when_project_scope_is_empty(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        built_in_agents_dir = tmp_path / "built-in-agents"
        config = self._config_with_built_in_root(
            repo_root=repo_root,
            home_dir=home_dir,
            built_in_agents_dir=built_in_agents_dir,
        )

        _write_skill(
            config.user_skills_dir / "reviewer" / "SKILL.md",
            name="reviewer-custom",
        )

        candidates = enumerate_skill_candidates(config)
        discovery = discover_skills(config)

        assert len(candidates) == 1
        assert candidates[0].scope == "user"
        assert candidates[0].relative_path == "reviewer/SKILL.md"
        assert tuple(discovery.selected_by_name()) == ("reviewer-custom",)
        assert discovery.selected[0].scope == "user"
        assert discovery.shadowed == ()

    def test_built_in_only_skills_discover_when_other_scopes_are_empty(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        built_in_agents_dir = tmp_path / "built-in-agents"
        config = self._config_with_built_in_root(
            repo_root=repo_root,
            home_dir=home_dir,
            built_in_agents_dir=built_in_agents_dir,
        )

        _write_skill(
            config.built_in_skills_dir / "planning-agent" / "SKILL.md",
            name="planning-agent",
        )

        candidates = enumerate_skill_candidates(config)
        discovery = discover_skills(config)

        assert len(candidates) == 1
        assert candidates[0].scope == "built_in"
        assert candidates[0].relative_path == "planning-agent/SKILL.md"
        assert tuple(discovery.selected_by_name()) == ("planning-agent",)
        assert discovery.selected[0].scope == "built_in"
        assert discovery.shadowed == ()

    def test_project_scope_overrides_user_and_built_in_for_duplicate_names(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        built_in_agents_dir = tmp_path / "built-in-agents"
        config = self._config_with_built_in_root(
            repo_root=repo_root,
            home_dir=home_dir,
            built_in_agents_dir=built_in_agents_dir,
        )

        _write_skill(
            config.built_in_skills_dir / "planner" / "SKILL.md",
            name="planner-custom",
            description="built-in version",
        )
        _write_skill(
            config.user_skills_dir / "planner" / "SKILL.md",
            name="planner-custom",
            description="user version",
        )
        _write_skill(
            config.project_skills_dir / "planner" / "SKILL.md",
            name="planner-custom",
            description="project version",
        )

        discovery = discover_skills(config)
        selected = discovery.selected_by_name()["planner-custom"]

        assert selected.scope == "project"
        assert selected.path == (config.project_skills_dir / "planner" / "SKILL.md").resolve()
        assert [skill.scope for skill in discovery.shadowed] == ["user", "built_in"]
        assert [skill.path for skill in discovery.shadowed] == [
            (config.user_skills_dir / "planner" / "SKILL.md").resolve(),
            (config.built_in_skills_dir / "planner" / "SKILL.md").resolve(),
        ]

    def test_duplicate_names_within_same_scope_fail_clearly(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        built_in_agents_dir = tmp_path / "built-in-agents"
        config = self._config_with_built_in_root(
            repo_root=repo_root,
            home_dir=home_dir,
            built_in_agents_dir=built_in_agents_dir,
        )

        _write_skill(
            config.project_skills_dir / "alpha" / "SKILL.md",
            name="shared-skill",
        )
        _write_skill(
            config.project_skills_dir / "nested" / "beta" / "SKILL.md",
            name="shared-skill",
        )

        with pytest.raises(
            SkillDiscoveryError,
            match=r"Duplicate skill name 'shared-skill' in project scope",
        ):
            discover_skills(config)

    def test_repo_root_override_recomputes_project_skill_root_with_manifest_override(
        self,
        tmp_path: Path,
    ) -> None:
        initial_repo_root = tmp_path / "initial-repo"
        initial_repo_root.mkdir()
        next_repo_root = tmp_path / "next-repo"
        next_repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        built_in_agents_dir = tmp_path / "built-in-agents"
        config = self._config_with_built_in_root(
            repo_root=initial_repo_root,
            home_dir=home_dir,
            built_in_agents_dir=built_in_agents_dir,
        )

        manifest_dir = tmp_path / "custom-project-manifests"
        manifest_dir.mkdir()
        expected_skill_path = next_repo_root / "agents" / "skills" / "alpha" / "SKILL.md"
        _write_skill(expected_skill_path, name="alpha-skill")

        updated = config.with_overrides(
            repo_root=next_repo_root.resolve(),
            project_agent_manifests_dir=manifest_dir.resolve(),
        )
        discovery = discover_skills(updated)

        assert updated.project_agents_dir == (next_repo_root / "agents").resolve()
        assert updated.project_skills_dir == (next_repo_root / "agents" / "skills").resolve()
        assert updated.project_agent_manifests_dir == manifest_dir.resolve()
        assert tuple(discovery.selected_by_name()) == ("alpha-skill",)
        assert discovery.selected[0].path == expected_skill_path.resolve()

    def test_global_home_override_recomputes_user_skill_root_with_manifest_override(
        self,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        initial_home_dir = tmp_path / "home"
        initial_home_dir.mkdir()
        next_global_home_dir = (tmp_path / "alt-home" / ".dormammu").resolve()
        built_in_agents_dir = tmp_path / "built-in-agents"
        config = self._config_with_built_in_root(
            repo_root=repo_root,
            home_dir=initial_home_dir,
            built_in_agents_dir=built_in_agents_dir,
        )

        manifest_dir = tmp_path / "custom-user-manifests"
        manifest_dir.mkdir()
        expected_skill_path = (
            next_global_home_dir / "agents" / "skills" / "reviewer" / "SKILL.md"
        )
        _write_skill(expected_skill_path, name="reviewer-custom")

        updated = config.with_overrides(
            global_home_dir=next_global_home_dir,
            user_agent_manifests_dir=manifest_dir.resolve(),
        )
        discovery = discover_skills(updated)

        assert updated.user_agents_dir == (next_global_home_dir / "agents").resolve()
        assert updated.user_skills_dir == (next_global_home_dir / "agents" / "skills").resolve()
        assert updated.user_agent_manifests_dir == manifest_dir.resolve()
        assert tuple(discovery.selected_by_name()) == ("reviewer-custom",)
        assert discovery.selected[0].path == expected_skill_path.resolve()

    def test_missing_and_empty_skill_roots_are_stable_noops(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        built_in_agents_dir = tmp_path / "built-in-agents"
        config = self._config_with_built_in_root(
            repo_root=repo_root,
            home_dir=home_dir,
            built_in_agents_dir=built_in_agents_dir,
        )

        initial = discover_skills(config)

        assert initial.candidates == ()
        assert initial.selected == ()
        assert initial.shadowed == ()

        config.project_skills_dir.mkdir(parents=True, exist_ok=True)
        config.user_skills_dir.mkdir(parents=True, exist_ok=True)
        config.built_in_skills_dir.mkdir(parents=True, exist_ok=True)

        empty = discover_skills(config)

        assert empty.candidates == ()
        assert empty.selected == ()
        assert empty.shadowed == ()
