from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
import re

if TYPE_CHECKING:
    from dormammu.agent.profiles import AgentProfile


_NORMALIZE_TOKEN_RE = re.compile(r"[^a-z0-9]+")


class McpTransportKind(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class McpFailurePolicy(str, Enum):
    FAIL = "fail"
    WARN = "warn"
    IGNORE = "ignore"


SUPPORTED_MCP_TRANSPORT_KINDS: tuple[str, ...] = tuple(
    item.value for item in McpTransportKind
)
SUPPORTED_MCP_FAILURE_POLICIES: tuple[str, ...] = tuple(
    item.value for item in McpFailurePolicy
)


def _normalize_token(value: str) -> str:
    return _NORMALIZE_TOKEN_RE.sub("_", value.strip().lower()).strip("_")


def _normalize_non_empty_string(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{field_name} must be a non-empty string in {source}")
    return value.strip()


def _coerce_mapping(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{field_name} must be a JSON object in {source}")
    return value


def _coerce_mapping_copy(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> dict[str, Any]:
    mapping = _coerce_mapping(value, field_name=field_name, source=source)
    copied: dict[str, Any] = {}
    for key, item in mapping.items():
        if not isinstance(key, str) or not key.strip():
            raise RuntimeError(f"{field_name} keys must be non-empty strings in {source}")
        copied[key.strip()] = item
    return copied


def _coerce_list(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> list[Any]:
    if not isinstance(value, list):
        raise RuntimeError(f"{field_name} must be a JSON array in {source}")
    return value


def _reject_unknown_keys(
    payload: Mapping[str, Any],
    *,
    allowed_keys: set[str],
    field_name: str,
    source: str,
) -> None:
    unknown_keys = set(payload.keys()) - allowed_keys
    if unknown_keys:
        keys = ", ".join(sorted(unknown_keys))
        raise RuntimeError(f"{field_name} contains unsupported keys ({keys}) in {source}")


def _normalize_optional_path(
    value: Any,
    *,
    config_path: Path | None,
    field_name: str,
    source: str,
) -> Path | None:
    if value is None:
        return None
    raw = _normalize_non_empty_string(value, field_name=field_name, source=source)
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    if config_path is None:
        return candidate
    return (config_path.parent / candidate).resolve(strict=False)


def _normalize_string_tuple(
    value: Any,
    *,
    field_name: str,
    source: str,
    dedupe: bool = True,
) -> tuple[str, ...]:
    if value is None:
        return ()
    values = _coerce_list(value, field_name=field_name, source=source)
    normalized: list[str] = []
    for index, item in enumerate(values):
        entry = _normalize_non_empty_string(
            item,
            field_name=f"{field_name}[{index}]",
            source=source,
        )
        if not dedupe or entry not in normalized:
            normalized.append(entry)
    return tuple(normalized)


def _normalize_string_map(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> dict[str, str]:
    if value is None:
        return {}
    payload = _coerce_mapping_copy(value, field_name=field_name, source=source)
    normalized: dict[str, str] = {}
    for key, item in payload.items():
        if not isinstance(item, str):
            raise RuntimeError(f"{field_name}.{key} must be a string in {source}")
        normalized[key] = item
    return normalized


def _normalize_metadata_map(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    return _coerce_mapping_copy(value, field_name=field_name, source=source)


def _normalize_transport_kind(
    value: McpTransportKind | str,
    *,
    field_name: str,
    source: str,
) -> McpTransportKind:
    if isinstance(value, McpTransportKind):
        return value
    if not isinstance(value, str):
        raise RuntimeError(
            f"{field_name} must be one of {SUPPORTED_MCP_TRANSPORT_KINDS} in {source}"
        )
    normalized = _normalize_token(value)
    for kind in McpTransportKind:
        if kind.value == normalized:
            return kind
    raise RuntimeError(
        f"{field_name} must be one of {SUPPORTED_MCP_TRANSPORT_KINDS} in {source}"
    )


def _normalize_failure_policy(
    value: McpFailurePolicy | str,
    *,
    field_name: str,
    source: str,
) -> McpFailurePolicy:
    if isinstance(value, McpFailurePolicy):
        return value
    if not isinstance(value, str):
        raise RuntimeError(
            f"{field_name} must be one of {SUPPORTED_MCP_FAILURE_POLICIES} in {source}"
        )
    normalized = _normalize_token(value)
    for policy in McpFailurePolicy:
        if policy.value == normalized:
            return policy
    raise RuntimeError(
        f"{field_name} must be one of {SUPPORTED_MCP_FAILURE_POLICIES} in {source}"
    )


@dataclass(frozen=True, slots=True)
class McpAccessPolicy:
    profiles: tuple[str, ...] = ()

    def allows(self, profile_name: str) -> bool:
        return profile_name in self.profiles

    def to_dict(self) -> dict[str, object]:
        return {
            "profiles": list(self.profiles),
        }


@dataclass(frozen=True, slots=True)
class McpStdioTransport:
    kind: McpTransportKind = McpTransportKind.STDIO
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "cwd": str(self.cwd) if self.cwd is not None else None,
        }


@dataclass(frozen=True, slots=True)
class McpSseTransport:
    kind: McpTransportKind = McpTransportKind.SSE
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "url": self.url,
            "headers": dict(self.headers),
        }


@dataclass(frozen=True, slots=True)
class McpStreamableHttpTransport:
    kind: McpTransportKind = McpTransportKind.STREAMABLE_HTTP
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "url": self.url,
            "headers": dict(self.headers),
        }


McpTransport = McpStdioTransport | McpSseTransport | McpStreamableHttpTransport


@dataclass(frozen=True, slots=True)
class McpServerDefinition:
    id: str
    transport: McpTransport
    access: McpAccessPolicy
    enabled: bool = True
    failure_policy: McpFailurePolicy = McpFailurePolicy.FAIL
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_visible_to_profile(self, profile_name: str) -> bool:
        return self.access.allows(profile_name)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "enabled": self.enabled,
            "transport": self.transport.to_dict(),
            "access": self.access.to_dict(),
            "failure_policy": self.failure_policy.value,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class McpConfigLayer:
    scope: str
    config_path: Path
    servers: tuple[McpServerDefinition, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "config_path": str(self.config_path),
            "servers": [server.to_dict() for server in self.servers],
        }


@dataclass(frozen=True, slots=True)
class EffectiveMcpServer:
    definition: McpServerDefinition
    scope: str
    config_path: Path

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def enabled(self) -> bool:
        return self.definition.enabled

    def is_visible_to_profile(self, profile_name: str) -> bool:
        return self.definition.is_visible_to_profile(profile_name)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "scope": self.scope,
            "config_path": str(self.config_path),
            "definition": self.definition.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class McpProfileResolution:
    profile_name: str
    visible_servers: tuple[EffectiveMcpServer, ...] = ()
    denied_servers: tuple[EffectiveMcpServer, ...] = ()
    disabled_servers: tuple[EffectiveMcpServer, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_name": self.profile_name,
            "visible_servers": [server.to_dict() for server in self.visible_servers],
            "denied_servers": [server.to_dict() for server in self.denied_servers],
            "disabled_servers": [server.to_dict() for server in self.disabled_servers],
        }


@dataclass(frozen=True, slots=True)
class McpCatalog:
    layers: tuple[McpConfigLayer, ...] = ()
    servers: tuple[EffectiveMcpServer, ...] = ()
    shadowed: tuple[EffectiveMcpServer, ...] = ()

    def definitions_by_id(self) -> dict[str, EffectiveMcpServer]:
        return {server.id: server for server in self.servers}

    def configured_servers(self) -> tuple[EffectiveMcpServer, ...]:
        return self.servers

    def enabled_servers(self) -> tuple[EffectiveMcpServer, ...]:
        return tuple(server for server in self.servers if server.enabled)

    def disabled_servers(self) -> tuple[EffectiveMcpServer, ...]:
        return tuple(server for server in self.servers if not server.enabled)

    def resolve_profile_access(
        self,
        profile: "AgentProfile | str",
    ) -> McpProfileResolution:
        profile_name = _profile_name(profile)
        visible_servers: list[EffectiveMcpServer] = []
        denied_servers: list[EffectiveMcpServer] = []
        disabled_servers: list[EffectiveMcpServer] = []

        for server in self.servers:
            if not server.is_visible_to_profile(profile_name):
                denied_servers.append(server)
                continue
            if server.enabled:
                visible_servers.append(server)
                continue
            disabled_servers.append(server)

        return McpProfileResolution(
            profile_name=profile_name,
            visible_servers=tuple(visible_servers),
            denied_servers=tuple(denied_servers),
            disabled_servers=tuple(disabled_servers),
        )

    def visible_servers_for_profile(
        self,
        profile: "AgentProfile | str",
    ) -> tuple[EffectiveMcpServer, ...]:
        return self.resolve_profile_access(profile).visible_servers

    def to_dict(self) -> dict[str, object]:
        return {
            "layers": [layer.to_dict() for layer in self.layers],
            "servers": [server.to_dict() for server in self.servers],
            "enabled_servers": [server.to_dict() for server in self.enabled_servers()],
            "disabled_servers": [server.to_dict() for server in self.disabled_servers()],
            "shadowed": [server.to_dict() for server in self.shadowed],
        }


def _profile_name(profile: "AgentProfile | str") -> str:
    if isinstance(profile, str):
        return profile
    return profile.name


def parse_mcp_access_policy(
    value: Any,
    *,
    valid_profile_names: tuple[str, ...] = (),
    field_name: str = "mcp.servers[].access",
    source: str = "mcp config",
) -> McpAccessPolicy:
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    _reject_unknown_keys(
        payload,
        allowed_keys={"profiles"},
        field_name=field_name,
        source=source,
    )

    profiles = _normalize_string_tuple(
        payload.get("profiles"),
        field_name=f"{field_name}.profiles",
        source=source,
    )
    if not profiles:
        raise RuntimeError(
            f"{field_name}.profiles must be a non-empty JSON array of strings in {source}"
        )

    known = set(valid_profile_names)
    if known:
        for index, profile_name in enumerate(profiles):
            if profile_name in known:
                continue
            known_profiles = ", ".join(sorted(known))
            raise RuntimeError(
                f"{field_name}.profiles[{index}] references unknown profile "
                f"{profile_name!r} in {source}. Known profiles: {known_profiles}"
            )

    return McpAccessPolicy(profiles=profiles)


def parse_mcp_transport(
    value: Any,
    *,
    config_path: Path | None,
    field_name: str = "mcp.servers[].transport",
    source: str = "mcp config",
) -> McpTransport:
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    kind = _normalize_transport_kind(
        payload.get("kind", McpTransportKind.STDIO.value),
        field_name=f"{field_name}.kind",
        source=source,
    )

    if kind is McpTransportKind.STDIO:
        _reject_unknown_keys(
            payload,
            allowed_keys={"kind", "command", "args", "env", "cwd"},
            field_name=field_name,
            source=source,
        )
        return McpStdioTransport(
            command=_normalize_non_empty_string(
                payload.get("command"),
                field_name=f"{field_name}.command",
                source=source,
            ),
            args=_normalize_string_tuple(
                payload.get("args"),
                field_name=f"{field_name}.args",
                source=source,
                dedupe=False,
            ),
            env=_normalize_string_map(
                payload.get("env"),
                field_name=f"{field_name}.env",
                source=source,
            ),
            cwd=_normalize_optional_path(
                payload.get("cwd"),
                config_path=config_path,
                field_name=f"{field_name}.cwd",
                source=source,
            ),
        )

    _reject_unknown_keys(
        payload,
        allowed_keys={"kind", "url", "headers"},
        field_name=field_name,
        source=source,
    )
    url = _normalize_non_empty_string(
        payload.get("url"),
        field_name=f"{field_name}.url",
        source=source,
    )
    headers = _normalize_string_map(
        payload.get("headers"),
        field_name=f"{field_name}.headers",
        source=source,
    )

    if kind is McpTransportKind.SSE:
        return McpSseTransport(url=url, headers=headers)
    return McpStreamableHttpTransport(url=url, headers=headers)


def parse_mcp_server_definition(
    value: Any,
    *,
    config_path: Path | None,
    valid_profile_names: tuple[str, ...] = (),
    field_name: str = "mcp.servers[]",
    source: str = "mcp config",
) -> McpServerDefinition:
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    _reject_unknown_keys(
        payload,
        allowed_keys={"id", "enabled", "transport", "access", "failure_policy", "metadata"},
        field_name=field_name,
        source=source,
    )

    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise RuntimeError(f"{field_name}.enabled must be a boolean in {source}")

    return McpServerDefinition(
        id=_normalize_non_empty_string(
            payload.get("id"),
            field_name=f"{field_name}.id",
            source=source,
        ),
        enabled=enabled,
        transport=parse_mcp_transport(
            payload.get("transport"),
            config_path=config_path,
            field_name=f"{field_name}.transport",
            source=source,
        ),
        access=parse_mcp_access_policy(
            payload.get("access"),
            valid_profile_names=valid_profile_names,
            field_name=f"{field_name}.access",
            source=source,
        ),
        failure_policy=_normalize_failure_policy(
            payload.get("failure_policy", McpFailurePolicy.FAIL.value),
            field_name=f"{field_name}.failure_policy",
            source=source,
        ),
        metadata=_normalize_metadata_map(
            payload.get("metadata"),
            field_name=f"{field_name}.metadata",
            source=source,
        ),
    )


def parse_mcp_server_definitions(
    value: Any,
    *,
    config_path: Path | None,
    valid_profile_names: tuple[str, ...] = (),
    field_name: str = "mcp.servers",
    source: str = "mcp config",
) -> tuple[McpServerDefinition, ...]:
    entries = _coerce_list(value, field_name=field_name, source=source)
    return tuple(
        parse_mcp_server_definition(
            item,
            config_path=config_path,
            valid_profile_names=valid_profile_names,
            field_name=f"{field_name}[{index}]",
            source=source,
        )
        for index, item in enumerate(entries)
    )


def load_mcp_config_layer(
    value: Any,
    *,
    scope: str,
    config_path: Path | None,
    valid_profile_names: tuple[str, ...] = (),
    field_name: str = "mcp",
) -> McpConfigLayer | None:
    if value is None:
        return None

    source = str(config_path) if config_path is not None else "dormammu.json"
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    _reject_unknown_keys(
        payload,
        allowed_keys={"servers"},
        field_name=field_name,
        source=source,
    )
    servers = parse_mcp_server_definitions(
        payload.get("servers", []),
        config_path=config_path,
        valid_profile_names=valid_profile_names,
        field_name=f"{field_name}.servers",
        source=source,
    )

    seen: dict[str, int] = {}
    for index, server in enumerate(servers):
        previous_index = seen.get(server.id)
        if previous_index is not None:
            raise RuntimeError(
                f"Duplicate MCP server id {server.id!r} in {scope} MCP config "
                f"{source} at {field_name}.servers[{previous_index}] and {field_name}.servers[{index}]"
            )
        seen[server.id] = index

    if config_path is None:
        raise RuntimeError(f"{field_name} requires a concrete config path for scope {scope!r}")

    return McpConfigLayer(
        scope=scope,
        config_path=config_path,
        servers=servers,
    )


def resolve_mcp_catalog(
    layers: tuple[McpConfigLayer, ...],
) -> McpCatalog:
    selected: dict[str, EffectiveMcpServer] = {}
    shadowed: list[EffectiveMcpServer] = []

    for layer in layers:
        for server in layer.servers:
            effective = EffectiveMcpServer(
                definition=server,
                scope=layer.scope,
                config_path=layer.config_path,
            )
            previous = selected.get(server.id)
            if previous is not None:
                shadowed.append(previous)
            selected[server.id] = effective

    return McpCatalog(
        layers=layers,
        servers=tuple(selected.values()),
        shadowed=tuple(shadowed),
    )
