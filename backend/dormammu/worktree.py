from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from dormammu.config import AppConfig


_WORKTREE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def _normalize_identifier(value: str, *, field_name: str) -> str:
    normalized = _WORKTREE_ID_PATTERN.sub("-", value.strip()).strip("-._").lower()
    if not normalized:
        raise ValueError(f"{field_name} must contain at least one alphanumeric character.")
    return normalized


def _normalize_optional_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string when provided.")
    return normalized


def _normalize_absolute_path(value: Path, *, field_name: str) -> Path:
    expanded = value.expanduser()
    if not expanded.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path.")
    return expanded.resolve()


def _normalize_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean.")
    return value


class WorktreeLifecycleStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    DIRTY = "dirty"
    RESETTING = "resetting"
    REMOVED = "removed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorktreeServiceConfig:
    root_dir: Path
    enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "enabled",
            _normalize_bool(self.enabled, field_name="enabled"),
        )
        object.__setattr__(
            self,
            "root_dir",
            _normalize_absolute_path(self.root_dir, field_name="root_dir"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "root_dir": str(self.root_dir),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorktreeServiceConfig:
        root_dir = payload.get("root_dir")
        if not isinstance(root_dir, str) or not root_dir.strip():
            raise ValueError("root_dir is required to load worktree service config.")
        enabled = _normalize_bool(payload.get("enabled", False), field_name="enabled")
        return cls(
            enabled=enabled,
            root_dir=Path(root_dir),
        )


@dataclass(frozen=True, slots=True)
class WorktreeOwner:
    session_id: str | None = None
    run_id: str | None = None
    agent_role: str | None = None

    def __post_init__(self) -> None:
        session_id = _normalize_optional_text(self.session_id, field_name="session_id")
        run_id = _normalize_optional_text(self.run_id, field_name="run_id")
        agent_role = _normalize_optional_text(self.agent_role, field_name="agent_role")
        if session_id is None and run_id is None:
            raise ValueError("Worktree owner metadata requires at least session_id or run_id.")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "agent_role", agent_role)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "agent_role": self.agent_role,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorktreeOwner:
        return cls(
            session_id=payload.get("session_id"),
            run_id=payload.get("run_id"),
            agent_role=payload.get("agent_role"),
        )


@dataclass(frozen=True, slots=True)
class ManagedWorktree:
    worktree_id: str
    source_repo_root: Path
    isolated_path: Path
    owner: WorktreeOwner
    status: WorktreeLifecycleStatus = WorktreeLifecycleStatus.PLANNED

    def __post_init__(self) -> None:
        worktree_id = _normalize_identifier(self.worktree_id, field_name="worktree_id")
        source_repo_root = _normalize_absolute_path(
            self.source_repo_root,
            field_name="source_repo_root",
        )
        isolated_path = _normalize_absolute_path(
            self.isolated_path,
            field_name="isolated_path",
        )
        if source_repo_root == isolated_path:
            raise ValueError("isolated_path must differ from source_repo_root.")
        object.__setattr__(self, "worktree_id", worktree_id)
        object.__setattr__(self, "source_repo_root", source_repo_root)
        object.__setattr__(self, "isolated_path", isolated_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worktree_id": self.worktree_id,
            "source_repo_root": str(self.source_repo_root),
            "isolated_path": str(self.isolated_path),
            "owner": self.owner.to_dict(),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ManagedWorktree:
        owner = payload.get("owner")
        if not isinstance(owner, Mapping):
            raise ValueError("owner is required to load a managed worktree.")
        return cls(
            worktree_id=str(payload["worktree_id"]),
            source_repo_root=Path(str(payload["source_repo_root"])),
            isolated_path=Path(str(payload["isolated_path"])),
            owner=WorktreeOwner.from_dict(owner),
            status=WorktreeLifecycleStatus(str(payload.get("status", WorktreeLifecycleStatus.PLANNED.value))),
        )


@dataclass(frozen=True, slots=True)
class WorktreeExecutionTarget:
    repo_root: Path
    workdir: Path
    worktree: ManagedWorktree | None = None
    isolation_active: bool = False

    def __post_init__(self) -> None:
        repo_root = _normalize_absolute_path(self.repo_root, field_name="repo_root")
        workdir = _normalize_absolute_path(self.workdir, field_name="workdir")
        object.__setattr__(self, "repo_root", repo_root)
        object.__setattr__(self, "workdir", workdir)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_root": str(self.repo_root),
            "workdir": str(self.workdir),
            "worktree": self.worktree.to_dict() if self.worktree is not None else None,
            "isolation_active": self.isolation_active,
        }


class WorktreeService:
    """Foundation for managed worktree planning and runtime target resolution."""

    def __init__(self, config: WorktreeServiceConfig) -> None:
        self.config = config

    @classmethod
    def from_app_config(cls, config: AppConfig) -> WorktreeService:
        return cls(config.worktree)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def normalize_worktree_id(self, value: str) -> str:
        return _normalize_identifier(value, field_name="worktree_id")

    def suggest_worktree_id(
        self,
        owner: WorktreeOwner,
        *,
        label: str | None = None,
    ) -> str:
        pieces = [
            owner.session_id or "sessionless",
            owner.run_id or owner.agent_role or "runtime",
            label or "worktree",
        ]
        return self.normalize_worktree_id("-".join(pieces))

    def worktree_path(self, worktree_id: str) -> Path:
        return (self.config.root_dir / self.normalize_worktree_id(worktree_id)).resolve()

    def plan_worktree(
        self,
        *,
        source_repo_root: Path,
        owner: WorktreeOwner,
        worktree_id: str | None = None,
        isolated_path: Path | None = None,
        label: str | None = None,
        status: WorktreeLifecycleStatus = WorktreeLifecycleStatus.PLANNED,
    ) -> ManagedWorktree:
        resolved_id = worktree_id or self.suggest_worktree_id(owner, label=label)
        return ManagedWorktree(
            worktree_id=resolved_id,
            source_repo_root=source_repo_root,
            isolated_path=isolated_path or self.worktree_path(resolved_id),
            owner=owner,
            status=status,
        )

    def resolve_execution_target(
        self,
        *,
        repo_root: Path,
        fallback_workdir: Path | None = None,
        isolation_requested: bool = False,
        owner: WorktreeOwner | None = None,
        worktree_id: str | None = None,
        label: str | None = None,
    ) -> WorktreeExecutionTarget:
        source_repo_root = _normalize_absolute_path(repo_root, field_name="repo_root")
        default_workdir = (
            _normalize_absolute_path(fallback_workdir, field_name="fallback_workdir")
            if fallback_workdir is not None
            else source_repo_root
        )
        if not isolation_requested or not self.enabled:
            return WorktreeExecutionTarget(
                repo_root=source_repo_root,
                workdir=default_workdir,
                worktree=None,
                isolation_active=False,
            )
        if owner is None:
            raise ValueError("owner is required when managed worktree isolation is requested.")
        planned_worktree = self.plan_worktree(
            source_repo_root=source_repo_root,
            owner=owner,
            worktree_id=worktree_id,
            label=label,
        )
        return WorktreeExecutionTarget(
            repo_root=planned_worktree.isolated_path,
            workdir=planned_worktree.isolated_path,
            worktree=planned_worktree,
            isolation_active=True,
        )


__all__ = [
    "ManagedWorktree",
    "WorktreeExecutionTarget",
    "WorktreeLifecycleStatus",
    "WorktreeOwner",
    "WorktreeService",
    "WorktreeServiceConfig",
]
