from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping
import re


_NORMALIZE_TOKEN_RE = re.compile(r"[^a-z0-9]+")


class HookEventName(str, Enum):
    PROMPT_INTAKE = "prompt_intake"
    PLAN_START = "plan_start"
    STAGE_START = "stage_start"
    STAGE_COMPLETE = "stage_complete"
    TOOL_EXECUTION = "tool_execution"
    CONFIG_CHANGE = "config_change"
    FINAL_VERIFICATION = "final_verification"
    SESSION_END = "session_end"

    @property
    def public_name(self) -> str:
        return _HOOK_EVENT_PUBLIC_NAMES[self]


class HookExecutionMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"
    BACKGROUND = "background"


class HookExecutorKind(str, Enum):
    BUILTIN = "builtin"
    COMMAND = "command"
    PYTHON = "python"


class HookResultAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    ANNOTATE = "annotate"
    BACKGROUND_STARTED = "background_started"


_HOOK_EVENT_PUBLIC_NAMES: dict[HookEventName, str] = {
    HookEventName.PROMPT_INTAKE: "prompt intake",
    HookEventName.PLAN_START: "plan start",
    HookEventName.STAGE_START: "stage start",
    HookEventName.STAGE_COMPLETE: "stage completion",
    HookEventName.TOOL_EXECUTION: "tool execution",
    HookEventName.CONFIG_CHANGE: "config changes",
    HookEventName.FINAL_VERIFICATION: "final verification",
    HookEventName.SESSION_END: "session end",
}

_HOOK_EVENT_EXTRA_ALIASES: dict[str, HookEventName] = {
    "stage_completion": HookEventName.STAGE_COMPLETE,
    "config_changes": HookEventName.CONFIG_CHANGE,
}

SUPPORTED_HOOK_EVENTS: tuple[HookEventName, ...] = tuple(HookEventName)
SUPPORTED_HOOK_PUBLIC_EVENT_NAMES: tuple[str, ...] = tuple(
    _HOOK_EVENT_PUBLIC_NAMES[event] for event in HookEventName
)
SUPPORTED_HOOK_RESULT_ACTIONS: tuple[str, ...] = tuple(
    action.value for action in HookResultAction
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
        copied[key] = item
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


def _normalize_optional_string(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> str | None:
    if value is None:
        return None
    return _normalize_non_empty_string(value, field_name=field_name, source=source)


def _normalize_timeout_seconds(
    value: Any,
    *,
    field_name: str,
    source: str,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"{field_name} must be a positive integer in {source}")
    return value


def _normalize_execution_mode(
    value: HookExecutionMode | str,
    *,
    field_name: str,
    source: str,
) -> HookExecutionMode:
    if isinstance(value, HookExecutionMode):
        return value
    if not isinstance(value, str):
        raise RuntimeError(
            f"{field_name} must be one of {tuple(mode.value for mode in HookExecutionMode)} in {source}"
        )
    normalized = _normalize_token(value)
    for mode in HookExecutionMode:
        if mode.value == normalized:
            return mode
    raise RuntimeError(
        f"{field_name} must be one of {tuple(mode.value for mode in HookExecutionMode)} in {source}"
    )


def _normalize_executor_kind(
    value: HookExecutorKind | str,
    *,
    field_name: str,
    source: str,
) -> HookExecutorKind:
    if isinstance(value, HookExecutorKind):
        return value
    if not isinstance(value, str):
        raise RuntimeError(
            f"{field_name} must be one of {tuple(kind.value for kind in HookExecutorKind)} in {source}"
        )
    normalized = _normalize_token(value)
    for kind in HookExecutorKind:
        if kind.value == normalized:
            return kind
    raise RuntimeError(
        f"{field_name} must be one of {tuple(kind.value for kind in HookExecutorKind)} in {source}"
    )


def normalize_hook_event_name(
    value: HookEventName | str,
    *,
    field_name: str = "hook.event",
    source: str = "hook event",
) -> HookEventName:
    if isinstance(value, HookEventName):
        return value
    if not isinstance(value, str):
        raise RuntimeError(
            f"{field_name} must be one of {SUPPORTED_HOOK_PUBLIC_EVENT_NAMES} in {source}"
        )

    normalized = _normalize_token(value)

    for event in HookEventName:
        if normalized == event.value:
            return event
        if normalized == _normalize_token(event.public_name):
            return event

    aliased = _HOOK_EVENT_EXTRA_ALIASES.get(normalized)
    if aliased is not None:
        return aliased

    raise RuntimeError(
        f"{field_name} must be one of {SUPPORTED_HOOK_PUBLIC_EVENT_NAMES} in {source}"
    )


def normalize_hook_result_action(
    value: HookResultAction | str,
    *,
    field_name: str = "hook_result.action",
    source: str = "hook result",
) -> HookResultAction:
    if isinstance(value, HookResultAction):
        return value
    if not isinstance(value, str):
        raise RuntimeError(
            f"{field_name} must be one of {SUPPORTED_HOOK_RESULT_ACTIONS} in {source}"
        )

    normalized = _normalize_token(value)
    for action in HookResultAction:
        if action.value == normalized:
            return action

    raise RuntimeError(
        f"{field_name} must be one of {SUPPORTED_HOOK_RESULT_ACTIONS} in {source}"
    )


@dataclass(frozen=True, slots=True)
class HookExecutorRef:
    kind: HookExecutorKind
    ref: str
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "ref": self.ref,
            "settings": dict(self.settings),
        }


@dataclass(frozen=True, slots=True)
class HookDefinition:
    name: str
    event: HookEventName
    target: HookExecutorRef
    execution_mode: HookExecutionMode = HookExecutionMode.SYNC
    timeout_seconds: int | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "event": self.event.value,
            "target": self.target.to_dict(),
            "execution_mode": self.execution_mode.value,
            "timeout_seconds": self.timeout_seconds,
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class HookSubjectRef:
    kind: str
    id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class HookInputPayload:
    event: HookEventName
    emitted_at: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    agent_role: str | None = None
    subject: HookSubjectRef | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "event": self.event.value,
            "emitted_at": self.emitted_at,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "agent_role": self.agent_role,
            "subject": self.subject.to_dict() if self.subject else None,
            "payload": dict(self.payload),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class HookBackgroundJob:
    job_id: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class HookResult:
    action: HookResultAction
    message: str | None = None
    annotations: dict[str, Any] = field(default_factory=dict)
    background_job: HookBackgroundJob | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action is HookResultAction.BACKGROUND_STARTED and self.background_job is None:
            raise RuntimeError(
                "hook_result.background_job is required when action is background_started"
            )
        if self.action is not HookResultAction.BACKGROUND_STARTED and self.background_job is not None:
            raise RuntimeError(
                "hook_result.background_job is only allowed when action is background_started"
            )
        if self.action is HookResultAction.ANNOTATE and not self.annotations:
            raise RuntimeError(
                "hook_result.annotations must be non-empty when action is annotate"
            )

    @property
    def is_blocking(self) -> bool:
        return self.action is HookResultAction.DENY

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "message": self.message,
            "annotations": dict(self.annotations),
            "background_job": self.background_job.to_dict() if self.background_job else None,
            "metadata": dict(self.metadata),
        }


def parse_hook_executor_ref(
    payload: Any,
    *,
    field_name: str = "hook.target",
    source: str,
) -> HookExecutorRef:
    data = _coerce_mapping(payload, field_name=field_name, source=source)
    _reject_unknown_keys(
        data,
        allowed_keys={"kind", "ref", "settings"},
        field_name=field_name,
        source=source,
    )
    return HookExecutorRef(
        kind=_normalize_executor_kind(
            data.get("kind"),
            field_name=f"{field_name}.kind",
            source=source,
        ),
        ref=_normalize_non_empty_string(
            data.get("ref"),
            field_name=f"{field_name}.ref",
            source=source,
        ),
        settings=_coerce_mapping_copy(
            data.get("settings", {}),
            field_name=f"{field_name}.settings",
            source=source,
        ),
    )


def parse_hook_definition_payload(
    payload: Any,
    *,
    field_name: str = "hooks[]",
    source: str,
) -> HookDefinition:
    data = _coerce_mapping(payload, field_name=field_name, source=source)
    _reject_unknown_keys(
        data,
        allowed_keys={"name", "event", "target", "execution_mode", "timeout_seconds", "enabled", "metadata"},
        field_name=field_name,
        source=source,
    )

    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise RuntimeError(f"{field_name}.enabled must be a boolean in {source}")

    return HookDefinition(
        name=_normalize_non_empty_string(
            data.get("name"),
            field_name=f"{field_name}.name",
            source=source,
        ),
        event=normalize_hook_event_name(
            data.get("event"),
            field_name=f"{field_name}.event",
            source=source,
        ),
        target=parse_hook_executor_ref(
            data.get("target"),
            field_name=f"{field_name}.target",
            source=source,
        ),
        execution_mode=_normalize_execution_mode(
            data.get("execution_mode", HookExecutionMode.SYNC.value),
            field_name=f"{field_name}.execution_mode",
            source=source,
        ),
        timeout_seconds=_normalize_timeout_seconds(
            data.get("timeout_seconds"),
            field_name=f"{field_name}.timeout_seconds",
            source=source,
        ),
        enabled=enabled,
        metadata=_coerce_mapping_copy(
            data.get("metadata", {}),
            field_name=f"{field_name}.metadata",
            source=source,
        ),
    )


def parse_hook_definitions(
    payload: Any,
    *,
    field_name: str = "hooks",
    source: str,
) -> tuple[HookDefinition, ...]:
    items = _coerce_list(payload, field_name=field_name, source=source)
    return tuple(
        parse_hook_definition_payload(
            item,
            field_name=f"{field_name}[{index}]",
            source=source,
        )
        for index, item in enumerate(items)
    )


def parse_hook_subject_ref(
    payload: Any,
    *,
    field_name: str = "hook_input.subject",
    source: str,
) -> HookSubjectRef:
    data = _coerce_mapping(payload, field_name=field_name, source=source)
    _reject_unknown_keys(
        data,
        allowed_keys={"kind", "id", "name", "metadata"},
        field_name=field_name,
        source=source,
    )

    return HookSubjectRef(
        kind=_normalize_non_empty_string(
            data.get("kind"),
            field_name=f"{field_name}.kind",
            source=source,
        ),
        id=_normalize_optional_string(
            data.get("id"),
            field_name=f"{field_name}.id",
            source=source,
        ),
        name=_normalize_optional_string(
            data.get("name"),
            field_name=f"{field_name}.name",
            source=source,
        ),
        metadata=_coerce_mapping_copy(
            data.get("metadata", {}),
            field_name=f"{field_name}.metadata",
            source=source,
        ),
    )


def parse_hook_input_payload(
    payload: Any,
    *,
    field_name: str = "hook_input",
    source: str,
) -> HookInputPayload:
    data = _coerce_mapping(payload, field_name=field_name, source=source)
    _reject_unknown_keys(
        data,
        allowed_keys={"event", "emitted_at", "session_id", "run_id", "agent_role", "subject", "payload", "metadata"},
        field_name=field_name,
        source=source,
    )

    raw_subject = data.get("subject")
    subject = (
        parse_hook_subject_ref(
            raw_subject,
            field_name=f"{field_name}.subject",
            source=source,
        )
        if raw_subject is not None
        else None
    )

    return HookInputPayload(
        event=normalize_hook_event_name(
            data.get("event"),
            field_name=f"{field_name}.event",
            source=source,
        ),
        emitted_at=_normalize_optional_string(
            data.get("emitted_at"),
            field_name=f"{field_name}.emitted_at",
            source=source,
        ),
        session_id=_normalize_optional_string(
            data.get("session_id"),
            field_name=f"{field_name}.session_id",
            source=source,
        ),
        run_id=_normalize_optional_string(
            data.get("run_id"),
            field_name=f"{field_name}.run_id",
            source=source,
        ),
        agent_role=_normalize_optional_string(
            data.get("agent_role"),
            field_name=f"{field_name}.agent_role",
            source=source,
        ),
        subject=subject,
        payload=_coerce_mapping_copy(
            data.get("payload", {}),
            field_name=f"{field_name}.payload",
            source=source,
        ),
        metadata=_coerce_mapping_copy(
            data.get("metadata", {}),
            field_name=f"{field_name}.metadata",
            source=source,
        ),
    )


def parse_hook_background_job(
    payload: Any,
    *,
    field_name: str = "hook_result.background_job",
    source: str,
) -> HookBackgroundJob:
    data = _coerce_mapping(payload, field_name=field_name, source=source)
    _reject_unknown_keys(
        data,
        allowed_keys={"job_id", "kind", "metadata"},
        field_name=field_name,
        source=source,
    )
    return HookBackgroundJob(
        job_id=_normalize_non_empty_string(
            data.get("job_id"),
            field_name=f"{field_name}.job_id",
            source=source,
        ),
        kind=_normalize_non_empty_string(
            data.get("kind"),
            field_name=f"{field_name}.kind",
            source=source,
        ),
        metadata=_coerce_mapping_copy(
            data.get("metadata", {}),
            field_name=f"{field_name}.metadata",
            source=source,
        ),
    )


def parse_hook_result_payload(
    payload: Any,
    *,
    field_name: str = "hook_result",
    source: str,
) -> HookResult:
    data = _coerce_mapping(payload, field_name=field_name, source=source)
    _reject_unknown_keys(
        data,
        allowed_keys={"action", "message", "annotations", "background_job", "metadata"},
        field_name=field_name,
        source=source,
    )

    raw_background_job = data.get("background_job")
    background_job = (
        parse_hook_background_job(
            raw_background_job,
            field_name=f"{field_name}.background_job",
            source=source,
        )
        if raw_background_job is not None
        else None
    )

    return HookResult(
        action=normalize_hook_result_action(
            data.get("action"),
            field_name=f"{field_name}.action",
            source=source,
        ),
        message=_normalize_optional_string(
            data.get("message"),
            field_name=f"{field_name}.message",
            source=source,
        ),
        annotations=_coerce_mapping_copy(
            data.get("annotations", {}),
            field_name=f"{field_name}.annotations",
            source=source,
        ),
        background_job=background_job,
        metadata=_coerce_mapping_copy(
            data.get("metadata", {}),
            field_name=f"{field_name}.metadata",
            source=source,
        ),
    )
