from __future__ import annotations

from pathlib import Path

import pytest

from dormammu.skills import (
    SKILL_CONTENT_MODE_INLINE_MARKDOWN,
    SKILL_DOCUMENT_SCHEMA_VERSION,
    SKILL_SOURCE_PRECEDENCE,
    SkillDocumentError,
    load_skill_definition,
    load_skill_document,
    normalize_skill_source_scope,
    parse_skill_document_payload,
    parse_skill_document_text,
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
