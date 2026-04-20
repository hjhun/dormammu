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


def discover_selected_agent_manifests(
    config: "AppConfig",
    *,
    names: Sequence[str],
) -> AgentManifestDiscovery:
    """Discover only the manifest-backed profiles requested by name.

    This runtime path is intentionally tolerant of unrelated malformed manifest
    files so one broken catalog entry does not block resolution of a different
    selected profile. Once a candidate declares one of the requested names, the
    full manifest parser and scope validation still apply.
    """

    requested_names = {
        name.strip()
        for name in names
        if isinstance(name, str) and name.strip()
    }
    search_roots = agent_manifest_search_roots(config)
    candidates = enumerate_agent_manifest_candidates(config)
    if not requested_names:
        return AgentManifestDiscovery(
            search_roots=search_roots,
            candidates=candidates,
            selected=(),
            shadowed=(),
        )

    loaded: list[DiscoveredAgentManifest] = []
    for candidate in candidates:
        discovered = _load_requested_agent_manifest(
            candidate,
            requested_names=requested_names,
        )
        if discovered is not None:
            loaded.append(discovered)

    selected, shadowed = _resolve_manifest_precedence(tuple(loaded))
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


def _load_requested_agent_manifest(
    candidate: AgentManifestCandidate,
    *,
    requested_names: set[str],
) -> DiscoveredAgentManifest | None:
    try:
        raw_text = candidate.path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentManifestError(f"Failed to read agent manifest {candidate.path}") from exc

    manifest_name = _peek_manifest_name(raw_text)
    if manifest_name is None or manifest_name not in requested_names:
        return None

    discovered = DiscoveredAgentManifest(
        manifest=parse_agent_manifest_text(
            raw_text,
            source_name=str(candidate.path),
            config_root=candidate.path.parent,
        ),
        candidate=candidate,
    )
    _validate_manifest_scope(discovered)
    return discovered


def _peek_manifest_name(raw_text: str) -> str | None:
    """Best-effort top-level manifest name extraction for requested loads.

    The selected-manifest runtime path must ignore unrelated malformed files,
    but it must not suppress parse errors once a candidate clearly declares a
    requested manifest name. This scanner walks only the top-level JSON object
    and tolerates earlier syntax damage well enough to identify a later
    top-level ``name`` field before full parsing runs.
    """
    def skip_whitespace(index: int) -> int:
        while index < len(raw_text) and raw_text[index] in " \t\r\n":
            index += 1
        return index

    def parse_quoted_string(index: int) -> tuple[str | None, int]:
        assert raw_text[index] == '"'
        index += 1
        chars: list[str] = []
        escaping = False
        while index < len(raw_text):
            char = raw_text[index]
            if escaping:
                chars.append(char)
                escaping = False
                index += 1
                continue
            if char == "\\":
                escaping = True
                index += 1
                continue
            if char == '"':
                return "".join(chars), index + 1
            chars.append(char)
            index += 1
        return None, index

    def parse_identifier(index: int) -> tuple[str | None, int]:
        if not (raw_text[index].isalpha() or raw_text[index] == "_"):
            return None, index
        start = index
        index += 1
        while index < len(raw_text) and (
            raw_text[index].isalnum() or raw_text[index] in {"_", "-"}
        ):
            index += 1
        return raw_text[start:index], index

    index = skip_whitespace(0)
    if index >= len(raw_text) or raw_text[index] != "{":
        return None

    depth = 0
    while index < len(raw_text):
        char = raw_text[index]
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth -= 1
            if depth <= 0:
                return None
            index += 1
            continue
        if char == "[":
            depth += 1
            index += 1
            continue
        if char == "]":
            depth = max(depth - 1, 0)
            index += 1
            continue
        if depth != 1:
            if char == '"':
                _, index = parse_quoted_string(index)
                continue
            index += 1
            continue

        if char in " \t\r\n,:":
            index += 1
            continue

        key: str | None = None
        if char == '"':
            key, next_index = parse_quoted_string(index)
        elif char.isalpha() or char == "_":
            key, next_index = parse_identifier(index)
        else:
            index += 1
            continue

        if key is None:
            return None

        colon_index = skip_whitespace(next_index)
        if colon_index >= len(raw_text) or raw_text[colon_index] != ":":
            index = next_index
            continue

        if key != "name":
            index = colon_index + 1
            continue

        value_index = skip_whitespace(colon_index + 1)
        if value_index >= len(raw_text):
            return None
        if raw_text[value_index] == '"':
            value, _ = parse_quoted_string(value_index)
            return value.strip() if isinstance(value, str) and value.strip() else None

        value, _ = parse_identifier(value_index)
        return value.strip() if isinstance(value, str) and value.strip() else None

    return None


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
