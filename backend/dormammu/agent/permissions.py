from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


FILESYSTEM_ACCESS_ANY = "*"
_PERMISSION_DECISIONS = ("allow", "deny", "ask")


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


def _normalize_decision(
    value: PermissionDecision | str,
    *,
    field_name: str,
    source: str,
) -> PermissionDecision:
    if isinstance(value, PermissionDecision):
        return value
    if not isinstance(value, str):
        raise RuntimeError(
            f"{field_name} must be one of {_PERMISSION_DECISIONS} in {source}"
        )
    normalized = value.strip().lower()
    if normalized not in _PERMISSION_DECISIONS:
        raise RuntimeError(
            f"{field_name} must be one of {_PERMISSION_DECISIONS} in {source}"
        )
    return PermissionDecision(normalized)


def _normalize_non_empty_string(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{field_name} must be a non-empty string in {source}")
    return value.strip()


def _resolve_policy_path(
    value: str | Path,
    *,
    config_root: Path | None,
) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        if config_root is None:
            raise RuntimeError("relative filesystem permission paths require an explicit config root")
        candidate = config_root / candidate
    return candidate.resolve(strict=False)


def _resolve_filesystem_request_path(
    value: str | Path,
    *,
    evaluation_root: Path | None,
) -> Path | None:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    if evaluation_root is None:
        return None
    root = Path(evaluation_root).expanduser()
    if not root.is_absolute():
        raise RuntimeError("filesystem evaluation root must be absolute")
    return (root.resolve(strict=False) / candidate).resolve(strict=False)


def _coerce_mapping(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{field_name} must be a JSON object in {source}")
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


def _coerce_rule_list(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeError(f"{field_name} must be a JSON array in {source}")
    return value


def _coerce_access_list(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> tuple[str, ...]:
    if value is None:
        return (FILESYSTEM_ACCESS_ANY,)
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        raise RuntimeError(
            f"{field_name} must be a string or JSON array in {source}"
        )

    normalized: list[str] = []
    for item in values:
        entry = _normalize_non_empty_string(
            item,
            field_name=field_name,
            source=source,
        ).lower()
        if entry not in normalized:
            normalized.append(entry)
    return tuple(normalized or (FILESYSTEM_ACCESS_ANY,))


@dataclass(frozen=True, slots=True)
class ToolPermissionRule:
    tool: str
    decision: PermissionDecision

    def to_dict(self) -> dict[str, str]:
        return {"tool": self.tool, "decision": self.decision.value}


@dataclass(frozen=True, slots=True)
class NetworkPermissionRule:
    host: str
    decision: PermissionDecision

    def to_dict(self) -> dict[str, str]:
        return {"host": self.host, "decision": self.decision.value}


@dataclass(frozen=True, slots=True)
class WorktreePermissionRule:
    action: str
    decision: PermissionDecision

    def to_dict(self) -> dict[str, str]:
        return {"action": self.action, "decision": self.decision.value}


@dataclass(frozen=True, slots=True)
class FilesystemPermissionRule:
    path: Path
    decision: PermissionDecision
    access: tuple[str, ...] = (FILESYSTEM_ACCESS_ANY,)

    def matches(self, path: Path, *, access: str) -> bool:
        normalized_access = access.strip().lower()
        if normalized_access not in self.access and FILESYSTEM_ACCESS_ANY not in self.access:
            return False
        return path == self.path or path.is_relative_to(self.path)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "decision": self.decision.value,
            "access": list(self.access),
        }


@dataclass(frozen=True, slots=True)
class ToolPermissionPolicy:
    default: PermissionDecision = PermissionDecision.ASK
    rules: tuple[ToolPermissionRule, ...] = ()

    def evaluate(self, tool: str) -> PermissionDecision:
        normalized_tool = tool.strip()
        for rule in reversed(self.rules):
            if rule.tool == normalized_tool:
                return rule.decision
        return self.default

    def to_dict(self) -> dict[str, object]:
        return {
            "default": self.default.value,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class FilesystemPermissionPolicy:
    default: PermissionDecision = PermissionDecision.ASK
    rules: tuple[FilesystemPermissionRule, ...] = ()

    def evaluate(
        self,
        path: str | Path,
        *,
        access: str = "read",
        evaluation_root: Path | None = None,
    ) -> PermissionDecision:
        normalized_path = _resolve_filesystem_request_path(
            path,
            evaluation_root=evaluation_root,
        )
        if normalized_path is None:
            return self.default
        best_depth = -1
        best_index = -1
        best_decision: PermissionDecision | None = None
        for index, rule in enumerate(self.rules):
            if not rule.matches(normalized_path, access=access):
                continue
            depth = len(rule.path.parts)
            if depth > best_depth or (depth == best_depth and index >= best_index):
                best_depth = depth
                best_index = index
                best_decision = rule.decision
        return best_decision if best_decision is not None else self.default

    def to_dict(self) -> dict[str, object]:
        return {
            "default": self.default.value,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class NetworkPermissionPolicy:
    default: PermissionDecision = PermissionDecision.ASK
    rules: tuple[NetworkPermissionRule, ...] = ()

    def evaluate(self, host: str) -> PermissionDecision:
        normalized_host = host.strip()
        for rule in reversed(self.rules):
            if rule.host == normalized_host:
                return rule.decision
        return self.default

    def to_dict(self) -> dict[str, object]:
        return {
            "default": self.default.value,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class WorktreePermissionPolicy:
    default: PermissionDecision = PermissionDecision.ASK
    rules: tuple[WorktreePermissionRule, ...] = ()

    def evaluate(self, action: str) -> PermissionDecision:
        normalized_action = action.strip()
        for rule in reversed(self.rules):
            if rule.action == normalized_action:
                return rule.decision
        return self.default

    def to_dict(self) -> dict[str, object]:
        return {
            "default": self.default.value,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class AgentPermissionPolicy:
    tools: ToolPermissionPolicy = field(default_factory=ToolPermissionPolicy)
    filesystem: FilesystemPermissionPolicy = field(default_factory=FilesystemPermissionPolicy)
    network: NetworkPermissionPolicy = field(default_factory=NetworkPermissionPolicy)
    worktree: WorktreePermissionPolicy = field(default_factory=WorktreePermissionPolicy)

    def evaluate_tool(self, tool: str) -> PermissionDecision:
        return self.tools.evaluate(tool)

    def evaluate_filesystem(
        self,
        path: str | Path,
        *,
        access: str = "read",
        evaluation_root: Path | None = None,
    ) -> PermissionDecision:
        return self.filesystem.evaluate(
            path,
            access=access,
            evaluation_root=evaluation_root,
        )

    def evaluate_network(self, host: str) -> PermissionDecision:
        return self.network.evaluate(host)

    def evaluate_worktree(self, action: str) -> PermissionDecision:
        return self.worktree.evaluate(action)

    def to_dict(self) -> dict[str, object]:
        return {
            "tools": self.tools.to_dict(),
            "filesystem": self.filesystem.to_dict(),
            "network": self.network.to_dict(),
            "worktree": self.worktree.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ToolPermissionPolicyOverride:
    default: PermissionDecision | None = None
    rules: tuple[ToolPermissionRule, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "default": self.default.value if self.default is not None else None,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class FilesystemPermissionPolicyOverride:
    default: PermissionDecision | None = None
    rules: tuple[FilesystemPermissionRule, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "default": self.default.value if self.default is not None else None,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class NetworkPermissionPolicyOverride:
    default: PermissionDecision | None = None
    rules: tuple[NetworkPermissionRule, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "default": self.default.value if self.default is not None else None,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class WorktreePermissionPolicyOverride:
    default: PermissionDecision | None = None
    rules: tuple[WorktreePermissionRule, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "default": self.default.value if self.default is not None else None,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class AgentPermissionPolicyOverride:
    tools: ToolPermissionPolicyOverride | None = None
    filesystem: FilesystemPermissionPolicyOverride | None = None
    network: NetworkPermissionPolicyOverride | None = None
    worktree: WorktreePermissionPolicyOverride | None = None

    def is_empty(self) -> bool:
        return (
            self.tools is None
            and self.filesystem is None
            and self.network is None
            and self.worktree is None
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "tools": self.tools.to_dict() if self.tools is not None else None,
            "filesystem": (
                self.filesystem.to_dict() if self.filesystem is not None else None
            ),
            "network": self.network.to_dict() if self.network is not None else None,
            "worktree": self.worktree.to_dict() if self.worktree is not None else None,
        }


def merge_permission_policy_override(
    base: AgentPermissionPolicyOverride | None,
    override: AgentPermissionPolicyOverride | None,
) -> AgentPermissionPolicyOverride | None:
    if base is None or base.is_empty():
        return override
    if override is None or override.is_empty():
        return base
    return AgentPermissionPolicyOverride(
        tools=_merge_tool_policy_override(base.tools, override.tools),
        filesystem=_merge_filesystem_policy_override(base.filesystem, override.filesystem),
        network=_merge_network_policy_override(base.network, override.network),
        worktree=_merge_worktree_policy_override(base.worktree, override.worktree),
    )


def merge_permission_policy(
    base: AgentPermissionPolicy,
    override: AgentPermissionPolicyOverride | None,
) -> AgentPermissionPolicy:
    if override is None or override.is_empty():
        return base
    return AgentPermissionPolicy(
        tools=ToolPermissionPolicy(
            default=(
                override.tools.default
                if override.tools is not None and override.tools.default is not None
                else base.tools.default
            ),
            rules=base.tools.rules + (override.tools.rules if override.tools is not None else ()),
        ),
        filesystem=FilesystemPermissionPolicy(
            default=(
                override.filesystem.default
                if override.filesystem is not None and override.filesystem.default is not None
                else base.filesystem.default
            ),
            rules=base.filesystem.rules + (
                override.filesystem.rules if override.filesystem is not None else ()
            ),
        ),
        network=NetworkPermissionPolicy(
            default=(
                override.network.default
                if override.network is not None and override.network.default is not None
                else base.network.default
            ),
            rules=base.network.rules + (
                override.network.rules if override.network is not None else ()
            ),
        ),
        worktree=WorktreePermissionPolicy(
            default=(
                override.worktree.default
                if override.worktree is not None and override.worktree.default is not None
                else base.worktree.default
            ),
            rules=base.worktree.rules + (
                override.worktree.rules if override.worktree is not None else ()
            ),
        ),
    )


def _merge_tool_policy_override(
    base: ToolPermissionPolicyOverride | None,
    override: ToolPermissionPolicyOverride | None,
) -> ToolPermissionPolicyOverride | None:
    if base is None:
        return override
    if override is None:
        return base
    return ToolPermissionPolicyOverride(
        default=override.default if override.default is not None else base.default,
        rules=base.rules + override.rules,
    )


def _merge_filesystem_policy_override(
    base: FilesystemPermissionPolicyOverride | None,
    override: FilesystemPermissionPolicyOverride | None,
) -> FilesystemPermissionPolicyOverride | None:
    if base is None:
        return override
    if override is None:
        return base
    return FilesystemPermissionPolicyOverride(
        default=override.default if override.default is not None else base.default,
        rules=base.rules + override.rules,
    )


def _merge_network_policy_override(
    base: NetworkPermissionPolicyOverride | None,
    override: NetworkPermissionPolicyOverride | None,
) -> NetworkPermissionPolicyOverride | None:
    if base is None:
        return override
    if override is None:
        return base
    return NetworkPermissionPolicyOverride(
        default=override.default if override.default is not None else base.default,
        rules=base.rules + override.rules,
    )


def _merge_worktree_policy_override(
    base: WorktreePermissionPolicyOverride | None,
    override: WorktreePermissionPolicyOverride | None,
) -> WorktreePermissionPolicyOverride | None:
    if base is None:
        return override
    if override is None:
        return base
    return WorktreePermissionPolicyOverride(
        default=override.default if override.default is not None else base.default,
        rules=base.rules + override.rules,
    )


def parse_permission_policy_override(
    value: Any,
    *,
    config_root: Path | None,
    field_name: str,
    source: str,
) -> AgentPermissionPolicyOverride:
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    _reject_unknown_keys(
        payload,
        allowed_keys={"tools", "filesystem", "network", "worktree"},
        field_name=field_name,
        source=source,
    )

    return AgentPermissionPolicyOverride(
        tools=_parse_tool_policy_override(
            payload.get("tools"),
            field_name=f"{field_name}.tools",
            source=source,
        ),
        filesystem=_parse_filesystem_policy_override(
            payload.get("filesystem"),
            config_root=config_root,
            field_name=f"{field_name}.filesystem",
            source=source,
        ),
        network=_parse_network_policy_override(
            payload.get("network"),
            field_name=f"{field_name}.network",
            source=source,
        ),
        worktree=_parse_worktree_policy_override(
            payload.get("worktree"),
            field_name=f"{field_name}.worktree",
            source=source,
        ),
    )


def _parse_tool_policy_override(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> ToolPermissionPolicyOverride | None:
    if value is None:
        return None
    if isinstance(value, str):
        return ToolPermissionPolicyOverride(
            default=_normalize_decision(value, field_name=field_name, source=source)
        )
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    _reject_unknown_keys(
        payload,
        allowed_keys={"default", "rules"},
        field_name=field_name,
        source=source,
    )
    rules: list[ToolPermissionRule] = []
    for index, raw_rule in enumerate(
        _coerce_rule_list(payload.get("rules"), field_name=f"{field_name}.rules", source=source)
    ):
        rule_payload = _coerce_mapping(
            raw_rule,
            field_name=f"{field_name}.rules[{index}]",
            source=source,
        )
        _reject_unknown_keys(
            rule_payload,
            allowed_keys={"tool", "decision"},
            field_name=f"{field_name}.rules[{index}]",
            source=source,
        )
        rules.append(
            ToolPermissionRule(
                tool=_normalize_non_empty_string(
                    rule_payload.get("tool"),
                    field_name=f"{field_name}.rules[{index}].tool",
                    source=source,
                ),
                decision=_normalize_decision(
                    rule_payload.get("decision"),
                    field_name=f"{field_name}.rules[{index}].decision",
                    source=source,
                ),
            )
        )
    default = payload.get("default")
    return ToolPermissionPolicyOverride(
        default=(
            _normalize_decision(default, field_name=f"{field_name}.default", source=source)
            if default is not None
            else None
        ),
        rules=tuple(rules),
    )


def _parse_filesystem_policy_override(
    value: Any,
    *,
    config_root: Path | None,
    field_name: str,
    source: str,
) -> FilesystemPermissionPolicyOverride | None:
    if value is None:
        return None
    if isinstance(value, str):
        return FilesystemPermissionPolicyOverride(
            default=_normalize_decision(value, field_name=field_name, source=source)
        )
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    _reject_unknown_keys(
        payload,
        allowed_keys={"default", "rules"},
        field_name=field_name,
        source=source,
    )
    rules: list[FilesystemPermissionRule] = []
    for index, raw_rule in enumerate(
        _coerce_rule_list(payload.get("rules"), field_name=f"{field_name}.rules", source=source)
    ):
        rule_payload = _coerce_mapping(
            raw_rule,
            field_name=f"{field_name}.rules[{index}]",
            source=source,
        )
        _reject_unknown_keys(
            rule_payload,
            allowed_keys={"path", "decision", "access"},
            field_name=f"{field_name}.rules[{index}]",
            source=source,
        )
        path_value = _normalize_non_empty_string(
            rule_payload.get("path"),
            field_name=f"{field_name}.rules[{index}].path",
            source=source,
        )
        rules.append(
            FilesystemPermissionRule(
                path=_resolve_policy_path(path_value, config_root=config_root),
                decision=_normalize_decision(
                    rule_payload.get("decision"),
                    field_name=f"{field_name}.rules[{index}].decision",
                    source=source,
                ),
                access=_coerce_access_list(
                    rule_payload.get("access"),
                    field_name=f"{field_name}.rules[{index}].access",
                    source=source,
                ),
            )
        )
    default = payload.get("default")
    return FilesystemPermissionPolicyOverride(
        default=(
            _normalize_decision(default, field_name=f"{field_name}.default", source=source)
            if default is not None
            else None
        ),
        rules=tuple(rules),
    )


def _parse_network_policy_override(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> NetworkPermissionPolicyOverride | None:
    if value is None:
        return None
    if isinstance(value, str):
        return NetworkPermissionPolicyOverride(
            default=_normalize_decision(value, field_name=field_name, source=source)
        )
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    _reject_unknown_keys(
        payload,
        allowed_keys={"default", "rules"},
        field_name=field_name,
        source=source,
    )
    rules: list[NetworkPermissionRule] = []
    for index, raw_rule in enumerate(
        _coerce_rule_list(payload.get("rules"), field_name=f"{field_name}.rules", source=source)
    ):
        rule_payload = _coerce_mapping(
            raw_rule,
            field_name=f"{field_name}.rules[{index}]",
            source=source,
        )
        _reject_unknown_keys(
            rule_payload,
            allowed_keys={"host", "decision"},
            field_name=f"{field_name}.rules[{index}]",
            source=source,
        )
        rules.append(
            NetworkPermissionRule(
                host=_normalize_non_empty_string(
                    rule_payload.get("host"),
                    field_name=f"{field_name}.rules[{index}].host",
                    source=source,
                ),
                decision=_normalize_decision(
                    rule_payload.get("decision"),
                    field_name=f"{field_name}.rules[{index}].decision",
                    source=source,
                ),
            )
        )
    default = payload.get("default")
    return NetworkPermissionPolicyOverride(
        default=(
            _normalize_decision(default, field_name=f"{field_name}.default", source=source)
            if default is not None
            else None
        ),
        rules=tuple(rules),
    )


def _parse_worktree_policy_override(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> WorktreePermissionPolicyOverride | None:
    if value is None:
        return None
    if isinstance(value, str):
        return WorktreePermissionPolicyOverride(
            default=_normalize_decision(value, field_name=field_name, source=source)
        )
    payload = _coerce_mapping(value, field_name=field_name, source=source)
    _reject_unknown_keys(
        payload,
        allowed_keys={"default", "rules"},
        field_name=field_name,
        source=source,
    )
    rules: list[WorktreePermissionRule] = []
    for index, raw_rule in enumerate(
        _coerce_rule_list(payload.get("rules"), field_name=f"{field_name}.rules", source=source)
    ):
        rule_payload = _coerce_mapping(
            raw_rule,
            field_name=f"{field_name}.rules[{index}]",
            source=source,
        )
        _reject_unknown_keys(
            rule_payload,
            allowed_keys={"action", "decision"},
            field_name=f"{field_name}.rules[{index}]",
            source=source,
        )
        rules.append(
            WorktreePermissionRule(
                action=_normalize_non_empty_string(
                    rule_payload.get("action"),
                    field_name=f"{field_name}.rules[{index}].action",
                    source=source,
                ),
                decision=_normalize_decision(
                    rule_payload.get("decision"),
                    field_name=f"{field_name}.rules[{index}].decision",
                    source=source,
                ),
            )
        )
    default = payload.get("default")
    return WorktreePermissionPolicyOverride(
        default=(
            _normalize_decision(default, field_name=f"{field_name}.default", source=source)
            if default is not None
            else None
        ),
        rules=tuple(rules),
    )
