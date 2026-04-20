from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from dormammu.agent.permissions import (
    AgentPermissionPolicy,
    merge_permission_policy,
    parse_permission_policy_override,
)
from dormammu.agent.profiles import AgentProfile, PROJECT_PROFILE_SOURCE, USER_PROFILE_SOURCE

if TYPE_CHECKING:
    from dormammu.config import AppConfig


AGENT_MANIFEST_SCHEMA_VERSION = 1
AGENT_MANIFEST_SOURCES: tuple[str, ...] = ("built_in", "project", "user")
AGENT_MANIFEST_DISCOVERY_SCOPES: tuple[str, ...] = (
    PROJECT_PROFILE_SOURCE,
    USER_PROFILE_SOURCE,
)
AGENT_MANIFEST_FILENAME_GLOB = "*.agent.json"
AGENT_MANIFEST_SCOPE_PRECEDENCE: dict[str, int] = {
    scope: index for index, scope in enumerate(AGENT_MANIFEST_DISCOVERY_SCOPES)
}


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


@dataclass(frozen=True, slots=True)
class AgentManifestSearchRoot:
    scope: str
    path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "scope": self.scope,
            "path": str(self.path),
        }


@dataclass(frozen=True, slots=True)
class AgentManifestCandidate:
    scope: str
    root_dir: Path
    path: Path

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.root_dir).as_posix()

    def to_dict(self) -> dict[str, str]:
        return {
            "scope": self.scope,
            "root_dir": str(self.root_dir),
            "path": str(self.path),
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True, slots=True)
class DiscoveredAgentManifest:
    manifest: AgentManifest
    candidate: AgentManifestCandidate

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def scope(self) -> str:
        return self.candidate.scope

    @property
    def path(self) -> Path:
        return self.candidate.path

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "scope": self.scope,
            "path": str(self.path),
            "relative_path": self.candidate.relative_path,
            "manifest_source": self.manifest.source,
        }


@dataclass(frozen=True, slots=True)
class AgentManifestDiscovery:
    search_roots: tuple[AgentManifestSearchRoot, ...]
    candidates: tuple[AgentManifestCandidate, ...]
    selected: tuple[DiscoveredAgentManifest, ...]
    shadowed: tuple[DiscoveredAgentManifest, ...]

    def selected_by_name(self) -> dict[str, DiscoveredAgentManifest]:
        return {manifest.name: manifest for manifest in self.selected}

    def to_dict(self) -> dict[str, object]:
        return {
            "search_roots": [root.to_dict() for root in self.search_roots],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected": [manifest.to_dict() for manifest in self.selected],
            "shadowed": [manifest.to_dict() for manifest in self.shadowed],
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


def agent_manifest_search_roots(config: "AppConfig") -> tuple[AgentManifestSearchRoot, ...]:
    return (
        AgentManifestSearchRoot(
            scope=PROJECT_PROFILE_SOURCE,
            path=config.project_agent_manifests_dir,
        ),
        AgentManifestSearchRoot(
            scope=USER_PROFILE_SOURCE,
            path=config.user_agent_manifests_dir,
        ),
    )


def enumerate_agent_manifest_candidates(
    config: "AppConfig",
) -> tuple[AgentManifestCandidate, ...]:
    candidates: list[AgentManifestCandidate] = []
    for root in agent_manifest_search_roots(config):
        if not root.path.is_dir():
            continue
        for path in sorted(
            candidate.resolve()
            for candidate in root.path.rglob(AGENT_MANIFEST_FILENAME_GLOB)
            if candidate.is_file()
        ):
            candidates.append(
                AgentManifestCandidate(
                    scope=root.scope,
                    root_dir=root.path,
                    path=path,
                )
            )
    return tuple(candidates)


def discover_agent_manifests(config: "AppConfig") -> AgentManifestDiscovery:
    search_roots = agent_manifest_search_roots(config)
    candidates = enumerate_agent_manifest_candidates(config)
    loaded = tuple(
        _load_discovered_agent_manifest(candidate)
        for candidate in candidates
    )
    selected, shadowed = _resolve_manifest_precedence(loaded)
    return AgentManifestDiscovery(
        search_roots=search_roots,
        candidates=candidates,
        selected=selected,
        shadowed=shadowed,
    )


def _load_discovered_agent_manifest(
    candidate: AgentManifestCandidate,
) -> DiscoveredAgentManifest:
    discovered = DiscoveredAgentManifest(
        manifest=load_agent_manifest(candidate.path),
        candidate=candidate,
    )
    _validate_manifest_scope(discovered)
    return discovered


def _validate_manifest_scope(discovered: DiscoveredAgentManifest) -> None:
    if discovered.manifest.source == discovered.scope:
        return
    raise AgentManifestError(
        "Agent manifest source/scope mismatch for "
        f"{discovered.path}: declared source {discovered.manifest.source!r} "
        f"does not match discovered scope {discovered.scope!r}."
    )


def _resolve_manifest_precedence(
    manifests: Sequence[DiscoveredAgentManifest],
) -> tuple[tuple[DiscoveredAgentManifest, ...], tuple[DiscoveredAgentManifest, ...]]:
    selected: dict[str, DiscoveredAgentManifest] = {}
    shadowed: list[DiscoveredAgentManifest] = []

    for discovered in sorted(manifests, key=_discovered_manifest_sort_key):
        current = selected.get(discovered.name)
        if current is None:
            selected[discovered.name] = discovered
            continue
        if current.scope == discovered.scope:
            raise AgentManifestError(
                "Duplicate agent manifest name "
                f"{discovered.name!r} in {discovered.scope} scope: "
                f"{current.path} and {discovered.path}. "
                "Use unique manifest names within the same scope."
            )
        winner, loser = _pick_manifest_winner(current, discovered)
        selected[discovered.name] = winner
        shadowed.append(loser)

    return (
        tuple(selected[name] for name in sorted(selected)),
        tuple(sorted(shadowed, key=_discovered_manifest_sort_key)),
    )


def _pick_manifest_winner(
    left: DiscoveredAgentManifest,
    right: DiscoveredAgentManifest,
) -> tuple[DiscoveredAgentManifest, DiscoveredAgentManifest]:
    if _scope_precedence_rank(left.scope) <= _scope_precedence_rank(right.scope):
        return left, right
    return right, left


def _discovered_manifest_sort_key(item: DiscoveredAgentManifest) -> tuple[int, str, str]:
    return (
        _scope_precedence_rank(item.scope),
        item.name,
        str(item.path),
    )


def _scope_precedence_rank(scope: str) -> int:
    try:
        return AGENT_MANIFEST_SCOPE_PRECEDENCE[scope]
    except KeyError as exc:
        allowed = ", ".join(AGENT_MANIFEST_DISCOVERY_SCOPES)
        raise ValueError(
            "Unsupported agent manifest discovery scope "
            f"{scope!r}; expected one of {allowed}"
        ) from exc


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
