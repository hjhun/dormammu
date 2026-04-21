from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence
from uuid import uuid4

from dormammu._utils import iso_now as _iso_now

if TYPE_CHECKING:
    from dormammu.state.repository import StateRepository


class LifecycleEventType(str, Enum):
    RUN_REQUESTED = "run.requested"
    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    STAGE_QUEUED = "stage.queued"
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    STAGE_FAILED = "stage.failed"
    STAGE_RETRIED = "stage.retried"
    EVALUATOR_CHECKPOINT_DECISION = "evaluator.checkpoint_decision"
    SUPERVISOR_HANDOFF = "supervisor.handoff"
    HOOK_EXECUTION_STARTED = "hook.execution_started"
    HOOK_EXECUTION_FINISHED = "hook.execution_finished"
    PERMISSION_GATE = "permission.gate"
    WORKTREE_PREPARED = "worktree.prepared"
    WORKTREE_RELEASED = "worktree.released"
    ARTIFACT_PERSISTED = "artifact.persisted"


class SupportsToDict(Protocol):
    def to_dict(self) -> dict[str, Any]:
        ...


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if is_dataclass(value):
        return {
            field_def.name: _serialize_value(getattr(value, field_def.name))
            for field_def in fields(value)
        }
    return value


def _normalize_token(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized or fallback


def build_lifecycle_run_id(
    scope: str,
    *,
    session_id: str | None = None,
    label: str | None = None,
) -> str:
    parts = [_normalize_token(scope, fallback="run")]
    if session_id:
        parts.append(_normalize_token(session_id, fallback="session"))
    if label:
        parts.append(_normalize_token(label, fallback="label"))
    parts.append(uuid4().hex[:12])
    return ":".join(parts)


def build_lifecycle_event_id() -> str:
    return f"evt:{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    kind: str
    path: str
    label: str | None = None
    content_type: str | None = None

    @classmethod
    def from_path(
        cls,
        *,
        kind: str,
        path: Path | str,
        label: str | None = None,
        content_type: str | None = None,
    ) -> ArtifactRef:
        return cls(
            kind=kind,
            path=str(path),
            label=label,
            content_type=content_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class EventIdentity:
    event_id: str
    event_type: LifecycleEventType
    run_id: str
    session_id: str | None
    timestamp: str
    role: str | None = None
    stage: str | None = None
    status: str | None = None

    @classmethod
    def create(
        cls,
        *,
        event_type: LifecycleEventType,
        run_id: str,
        session_id: str | None,
        role: str | None = None,
        stage: str | None = None,
        status: str | None = None,
        timestamp: str | None = None,
    ) -> EventIdentity:
        return cls(
            event_id=build_lifecycle_event_id(),
            event_type=event_type,
            run_id=run_id,
            session_id=session_id,
            timestamp=timestamp or _iso_now(),
            role=role,
            stage=stage,
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class RunEventPayload:
    source: str
    entrypoint: str
    trigger: str | None = None
    prompt_summary: str | None = None
    attempts_completed: int | None = None
    retries_used: int | None = None
    supervisor_verdict: str | None = None
    outcome: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class StageEventPayload:
    attempt: int | None = None
    verdict: str | None = None
    reason: str | None = None
    next_attempt: int | None = None
    source_stage: str | None = None
    target_stage: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class EvaluatorCheckpointPayload:
    checkpoint_kind: str
    decision: str
    rationale: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class SupervisorHandoffPayload:
    from_role: str
    to_role: str
    reason: str | None = None
    attempt: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class HookExecutionPayload:
    hook_event: str
    selected_hooks: tuple[str, ...] = ()
    executed_hooks: tuple[str, ...] = ()
    blocking_hook: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class PermissionGatePayload:
    gate_name: str
    decision: str
    reason: str | None = None
    requested_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class WorktreeEventPayload:
    worktree_id: str
    source_repo_root: str
    isolated_path: str
    owner_role: str | None = None
    owner_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class ArtifactPersistedPayload:
    artifact_kind: str
    operation: str = "persisted"
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    identity: EventIdentity
    payload: SupportsToDict
    artifact_refs: tuple[ArtifactRef, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity.to_dict(),
            "payload": self.payload.to_dict(),
            "artifact_refs": [artifact.to_dict() for artifact in self.artifact_refs],
            "metadata": _serialize_value(dict(self.metadata)),
        }


@dataclass(slots=True)
class LifecycleRecorder:
    repository: StateRepository | None
    run_id: str
    session_id: str | None = None
    default_metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def for_execution(
        cls,
        repository: StateRepository | None,
        *,
        scope: str,
        session_id: str | None,
        label: str | None = None,
        default_metadata: Mapping[str, Any] | None = None,
    ) -> LifecycleRecorder:
        return cls(
            repository=repository,
            run_id=build_lifecycle_run_id(scope, session_id=session_id, label=label),
            session_id=session_id,
            default_metadata=dict(default_metadata or {}),
        )

    def emit(
        self,
        *,
        event_type: LifecycleEventType,
        payload: SupportsToDict,
        status: str | None = None,
        role: str | None = None,
        stage: str | None = None,
        artifact_refs: Sequence[ArtifactRef] = (),
        metadata: Mapping[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> LifecycleEvent:
        merged_metadata = dict(self.default_metadata)
        if metadata:
            merged_metadata.update(dict(metadata))
        event = LifecycleEvent(
            identity=EventIdentity.create(
                event_type=event_type,
                run_id=self.run_id,
                session_id=self.session_id,
                role=role,
                stage=stage,
                status=status,
                timestamp=timestamp,
            ),
            payload=payload,
            artifact_refs=tuple(artifact_refs),
            metadata=merged_metadata,
        )
        if self.repository is not None:
            try:
                self.repository.record_lifecycle_event(event)
            except Exception:
                # Lifecycle persistence is additive observability; it must not
                # break the underlying loop, pipeline, or daemon behavior.
                pass
        return event
