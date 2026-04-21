from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping


SKILL_DOCUMENT_FILENAME = "SKILL.md"
SKILL_DOCUMENT_SCHEMA_VERSION = 1
SKILL_CONTENT_MODE_INLINE_MARKDOWN = "inline_markdown"
SKILL_SOURCE_SCOPES: tuple[str, ...] = ("built_in", "project", "user")
# Lower rank wins when later discovery resolves duplicate names.
SKILL_SOURCE_PRECEDENCE_ORDER: tuple[str, ...] = ("project", "user", "built_in")
SKILL_SOURCE_PRECEDENCE: dict[str, int] = {
    scope: index for index, scope in enumerate(SKILL_SOURCE_PRECEDENCE_ORDER)
}


class SkillDocumentError(RuntimeError):
    """Raised when a skill document is malformed."""


@dataclass(frozen=True, slots=True)
class SkillContent:
    mode: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class SkillDocument:
    """Typed v1 schema for a parsed ``SKILL.md`` document."""

    schema_version: int
    name: str
    description: str
    content: SkillContent
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "description": self.description,
            "content": self.content.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class LoadedSkillDefinition:
    """Runtime-ready skill definition with explicit source metadata."""

    document: SkillDocument
    source_scope: str
    source_path: Path

    @classmethod
    def from_document(
        cls,
        document: SkillDocument,
        *,
        source_scope: str,
        source_path: Path,
    ) -> "LoadedSkillDefinition":
        return cls(
            document=document,
            source_scope=normalize_skill_source_scope(
                source_scope,
                field_name="loaded_skill.source_scope",
                source_name=str(source_path),
            ),
            source_path=source_path.resolve(),
        )

    @property
    def name(self) -> str:
        return self.document.name

    @property
    def description(self) -> str:
        return self.document.description

    @property
    def content(self) -> SkillContent:
        return self.document.content

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.document.metadata)

    @property
    def schema_version(self) -> int:
        return self.document.schema_version

    @property
    def source_precedence(self) -> int:
        return skill_source_precedence(self.source_scope)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "schema_version": self.schema_version,
            "source_scope": self.source_scope,
            "source_precedence": self.source_precedence,
            "source_path": str(self.source_path),
            "content": self.content.to_dict(),
            "metadata": dict(self.document.metadata),
        }


def load_skill_document(path: Path) -> SkillDocument:
    normalized_path = path.resolve()
    if normalized_path.name != SKILL_DOCUMENT_FILENAME:
        raise SkillDocumentError(
            f"Skill documents must be named {SKILL_DOCUMENT_FILENAME}: {normalized_path}"
        )

    try:
        raw_text = normalized_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillDocumentError(f"Failed to read skill document {normalized_path}") from exc
    return parse_skill_document_text(raw_text, source_name=str(normalized_path))


def load_skill_definition(
    path: Path,
    *,
    source_scope: str,
) -> LoadedSkillDefinition:
    document = load_skill_document(path)
    return LoadedSkillDefinition.from_document(
        document,
        source_scope=source_scope,
        source_path=path,
    )


def parse_skill_document_text(
    raw_text: str,
    *,
    source_name: str,
) -> SkillDocument:
    frontmatter_text, body = _split_frontmatter(raw_text, source_name=source_name)
    payload = _parse_frontmatter(frontmatter_text, source_name=source_name)
    return parse_skill_document_payload(
        payload,
        source_name=source_name,
        body=body,
    )


def parse_skill_document_payload(
    payload: Any,
    *,
    source_name: str,
    body: str,
) -> SkillDocument:
    field_prefix = "skill_document"
    document = _coerce_mapping(payload, field_name=field_prefix, source_name=source_name)
    unknown_keys = set(document.keys()) - {
        "schema_version",
        "name",
        "description",
        "metadata",
    }
    if unknown_keys:
        keys = ", ".join(sorted(unknown_keys))
        raise SkillDocumentError(
            f"{field_prefix} contains unsupported keys ({keys}) in {source_name}"
        )

    schema_version = _parse_schema_version(
        document.get("schema_version"),
        field_name=f"{field_prefix}.schema_version",
        source_name=source_name,
    )
    name = _require_non_empty_string(
        document.get("name"),
        field_name=f"{field_prefix}.name",
        source_name=source_name,
    )
    description = _require_non_empty_string(
        document.get("description"),
        field_name=f"{field_prefix}.description",
        source_name=source_name,
    )
    metadata = _parse_metadata(
        document.get("metadata"),
        field_name=f"{field_prefix}.metadata",
        source_name=source_name,
    )
    content_text = _require_non_empty_string(
        body,
        field_name=f"{field_prefix}.content",
        source_name=source_name,
    )

    return SkillDocument(
        schema_version=schema_version,
        name=name,
        description=description,
        content=SkillContent(
            mode=SKILL_CONTENT_MODE_INLINE_MARKDOWN,
            text=content_text,
        ),
        metadata=metadata,
    )


def normalize_skill_source_scope(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> str:
    normalized = _require_non_empty_string(
        value,
        field_name=field_name,
        source_name=source_name,
    ).lower()
    if normalized not in SKILL_SOURCE_SCOPES:
        allowed = ", ".join(SKILL_SOURCE_SCOPES)
        raise SkillDocumentError(
            f"{field_name} must be one of ({allowed}) in {source_name}"
        )
    return normalized


def skill_source_precedence(scope: str) -> int:
    normalized_scope = normalize_skill_source_scope(
        scope,
        field_name="skill.source_scope",
        source_name="skill source precedence",
    )
    return SKILL_SOURCE_PRECEDENCE[normalized_scope]


def _split_frontmatter(
    raw_text: str,
    *,
    source_name: str,
) -> tuple[str, str]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillDocumentError(
            f"Skill document must begin with frontmatter delimited by --- in {source_name}"
        )

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1:]).strip()
            return frontmatter, body

    raise SkillDocumentError(
        f"Skill document frontmatter must terminate with --- in {source_name}"
    )


def _parse_frontmatter(
    frontmatter_text: str,
    *,
    source_name: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for index, raw_line in enumerate(frontmatter_text.splitlines(), start=2):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if raw_line[:1].isspace():
            raise SkillDocumentError(
                "Skill document frontmatter does not support nested mappings "
                f"in {source_name} at line {index}"
            )
        if ":" not in raw_line:
            raise SkillDocumentError(
                f"Invalid skill document frontmatter in {source_name} at line {index}"
            )

        key, raw_value = raw_line.split(":", 1)
        normalized_key = key.strip()
        if not normalized_key:
            raise SkillDocumentError(
                f"Skill document frontmatter key must be non-empty in {source_name} at line {index}"
            )
        if normalized_key in payload:
            raise SkillDocumentError(
                f"Duplicate skill document frontmatter key {normalized_key!r} in {source_name}"
            )
        payload[normalized_key] = _parse_frontmatter_value(
            raw_value.strip(),
            field_name=f"skill_document.{normalized_key}",
            source_name=source_name,
        )
    return payload


def _parse_frontmatter_value(
    raw_value: str,
    *,
    field_name: str,
    source_name: str,
) -> Any:
    if not raw_value:
        return ""

    if raw_value.startswith("'") and raw_value.endswith("'") and len(raw_value) >= 2:
        return raw_value[1:-1]

    if raw_value.startswith('"') and raw_value.endswith('"') and len(raw_value) >= 2:
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise SkillDocumentError(
                f"{field_name} contains invalid quoted JSON string in {source_name}: {exc.msg}"
            ) from exc

    if raw_value.startswith("{") or raw_value.startswith("["):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise SkillDocumentError(
                f"{field_name} contains invalid JSON literal in {source_name}: {exc.msg}"
            ) from exc

    if raw_value in {"true", "false", "null"} or re.fullmatch(r"-?\d+", raw_value):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            pass

    return raw_value


def _coerce_mapping(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SkillDocumentError(f"{field_name} must be a JSON object in {source_name}")
    return value


def _require_non_empty_string(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillDocumentError(
            f"{field_name} must be a non-empty string in {source_name}"
        )
    return value.strip()


def _parse_schema_version(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> int:
    if value is None:
        return SKILL_DOCUMENT_SCHEMA_VERSION
    if type(value) is not int:
        raise SkillDocumentError(
            f"{field_name} must be the integer {SKILL_DOCUMENT_SCHEMA_VERSION} in {source_name}"
        )
    if value != SKILL_DOCUMENT_SCHEMA_VERSION:
        raise SkillDocumentError(
            f"{field_name} must be {SKILL_DOCUMENT_SCHEMA_VERSION} in {source_name}"
        )
    return value


def _parse_metadata(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    payload = _coerce_mapping(value, field_name=field_name, source_name=source_name)
    return dict(payload)
