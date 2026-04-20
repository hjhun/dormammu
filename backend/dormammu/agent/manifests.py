from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from dormammu.agent.permissions import (
    AgentPermissionPolicy,
    merge_permission_policy,
    parse_permission_policy_override,
)
from dormammu.agent.profiles import AgentProfile


AGENT_MANIFEST_SCHEMA_VERSION = 1
AGENT_MANIFEST_SOURCES: tuple[str, ...] = ("built_in", "project", "user")


class AgentManifestError(RuntimeError):
    """Raised when an agent manifest document is malformed."""


@dataclass(frozen=True, slots=True)
class AgentManifest:
    """Typed v1 schema for an on-disk agent manifest."""

    schema_version: int
    name: str
    description: str
    prompt: str
    source: str
    cli_override: Path | None = None
    model_override: str | None = None
    permission_policy: AgentPermissionPolicy = field(default_factory=AgentPermissionPolicy)
    preloaded_skills: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_profile(self) -> AgentProfile:
        return AgentProfile(
            name=self.name,
            description=self.description,
            source=self.source,
            prompt_body=self.prompt,
            cli_override=self.cli_override,
            model_override=self.model_override,
            permission_policy=self.permission_policy,
            preloaded_skills=self.preloaded_skills,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt,
            "source": self.source,
            "cli": str(self.cli_override) if self.cli_override is not None else None,
            "model": self.model_override,
            "permissions": self.permission_policy.to_dict(),
            "skills": list(self.preloaded_skills),
            "metadata": dict(self.metadata),
        }


def load_agent_manifest(path: Path) -> AgentManifest:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentManifestError(f"Failed to read agent manifest {path}") from exc
    return parse_agent_manifest_text(
        raw_text,
        source_name=str(path),
        config_root=path.parent,
    )


def parse_agent_manifest_text(
    raw_text: str,
    *,
    source_name: str,
    config_root: Path | None = None,
) -> AgentManifest:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AgentManifestError(
            "Failed to parse agent manifest JSON "
            f"in {source_name}: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    return parse_agent_manifest_payload(
        payload,
        source_name=source_name,
        config_root=config_root,
    )


def parse_agent_manifest_payload(
    payload: Any,
    *,
    source_name: str,
    config_root: Path | None = None,
) -> AgentManifest:
    field_prefix = "agent_manifest"
    manifest = _coerce_mapping(payload, field_name=field_prefix, source_name=source_name)
    unknown_keys = set(manifest.keys()) - {
        "schema_version",
        "name",
        "description",
        "prompt",
        "source",
        "cli",
        "model",
        "permissions",
        "skills",
        "metadata",
    }
    if unknown_keys:
        keys = ", ".join(sorted(unknown_keys))
        raise AgentManifestError(
            f"{field_prefix} contains unsupported keys ({keys}) in {source_name}"
        )

    schema_version = _parse_schema_version(
        manifest.get("schema_version"),
        field_name=f"{field_prefix}.schema_version",
        source_name=source_name,
    )
    name = _require_non_empty_string(
        manifest.get("name"),
        field_name=f"{field_prefix}.name",
        source_name=source_name,
    )
    description = _require_non_empty_string(
        manifest.get("description"),
        field_name=f"{field_prefix}.description",
        source_name=source_name,
    )
    prompt = _require_non_empty_string(
        manifest.get("prompt"),
        field_name=f"{field_prefix}.prompt",
        source_name=source_name,
    )
    scope = _parse_source_scope(
        manifest.get("source"),
        field_name=f"{field_prefix}.source",
        source_name=source_name,
    )
    cli_override = _parse_cli_override(
        manifest.get("cli"),
        field_name=f"{field_prefix}.cli",
        source_name=source_name,
        config_root=config_root,
    )
    model_override = _optional_non_empty_string(
        manifest.get("model"),
        field_name=f"{field_prefix}.model",
        source_name=source_name,
    )
    preloaded_skills = _parse_skill_list(
        manifest.get("skills"),
        field_name=f"{field_prefix}.skills",
        source_name=source_name,
    )
    metadata = _parse_metadata(
        manifest.get("metadata"),
        field_name=f"{field_prefix}.metadata",
        source_name=source_name,
    )

    permissions_override = None
    if manifest.get("permissions") is not None:
        try:
            permissions_override = parse_permission_policy_override(
                manifest.get("permissions"),
                config_root=config_root,
                field_name=f"{field_prefix}.permissions",
                source=source_name,
            )
        except RuntimeError as exc:
            raise AgentManifestError(str(exc)) from exc

    return AgentManifest(
        schema_version=schema_version,
        name=name,
        description=description,
        prompt=prompt,
        source=scope,
        cli_override=cli_override,
        model_override=model_override,
        permission_policy=merge_permission_policy(
            AgentPermissionPolicy(),
            permissions_override,
        ),
        preloaded_skills=preloaded_skills,
        metadata=metadata,
    )


def _coerce_mapping(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentManifestError(f"{field_name} must be a JSON object in {source_name}")
    return value


def _require_non_empty_string(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentManifestError(
            f"{field_name} must be a non-empty string in {source_name}"
        )
    return value.strip()


def _optional_non_empty_string(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(
        value,
        field_name=field_name,
        source_name=source_name,
    )


def _parse_schema_version(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> int:
    if type(value) is not int:
        raise AgentManifestError(f"{field_name} must be the integer 1 in {source_name}")
    if value != AGENT_MANIFEST_SCHEMA_VERSION:
        raise AgentManifestError(
            f"{field_name} must be {AGENT_MANIFEST_SCHEMA_VERSION} in {source_name}"
        )
    return value


def _parse_source_scope(
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
    if normalized not in AGENT_MANIFEST_SOURCES:
        allowed = ", ".join(AGENT_MANIFEST_SOURCES)
        raise AgentManifestError(
            f"{field_name} must be one of ({allowed}) in {source_name}"
        )
    return normalized


def _parse_cli_override(
    value: Any,
    *,
    field_name: str,
    source_name: str,
    config_root: Path | None,
) -> Path | None:
    cli_raw = _optional_non_empty_string(
        value,
        field_name=field_name,
        source_name=source_name,
    )
    if cli_raw is None:
        return None
    candidate = Path(cli_raw).expanduser()
    if candidate.is_absolute():
        return candidate
    if config_root is not None and ("/" in cli_raw or cli_raw.startswith(".")):
        return (config_root / candidate).resolve()
    return candidate


def _parse_skill_list(
    value: Any,
    *,
    field_name: str,
    source_name: str,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AgentManifestError(f"{field_name} must be a JSON array in {source_name}")
    normalized: list[str] = []
    for index, item in enumerate(value):
        skill = _require_non_empty_string(
            item,
            field_name=f"{field_name}[{index}]",
            source_name=source_name,
        )
        if skill not in normalized:
            normalized.append(skill)
    return tuple(normalized)


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
