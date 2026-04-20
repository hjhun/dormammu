from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
import re
import subprocess
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

if TYPE_CHECKING:
    from dormammu.config import AppConfig


_WORKTREE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
_GIT_COMMAND_NAME = "git"


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


class WorktreeServiceError(RuntimeError):
    """Base error for managed worktree lifecycle failures."""


class WorktreeRepositoryError(WorktreeServiceError):
    """Raised when the source repository cannot support managed worktrees."""


class WorktreeCollisionError(WorktreeServiceError):
    """Raised when the deterministic worktree path collides with unmanaged state."""


class WorktreeGitCommandError(WorktreeServiceError):
    """Raised when a git command needed by the worktree service fails."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        command_text = " ".join(command)
        details: list[str] = [f"{command_text} failed with exit code {returncode}."]
        stdout_text = stdout.strip()
        stderr_text = stderr.strip()
        if stderr_text:
            details.append(stderr_text)
        elif stdout_text:
            details.append(stdout_text)
        super().__init__(" ".join(details))
        self.command = tuple(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


@dataclass(frozen=True, slots=True)
class _GitWorktreeEntry:
    path: Path
    head: str | None = None
    branch: str | None = None
    detached: bool = False
    prunable_reason: str | None = None


GitRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_git_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
    )


class WorktreeService:
    """Foundation for managed worktree planning and runtime target resolution."""

    def __init__(
        self,
        config: WorktreeServiceConfig,
        *,
        git_runner: GitRunner | None = None,
    ) -> None:
        self.config = config
        self._git_runner = git_runner or _default_git_runner

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

    def find_worktree(
        self,
        *,
        source_repo_root: Path,
        owner: WorktreeOwner,
        worktree_id: str | None = None,
        label: str | None = None,
    ) -> ManagedWorktree | None:
        planned_worktree = self.plan_worktree(
            source_repo_root=source_repo_root,
            owner=owner,
            worktree_id=worktree_id,
            label=label,
            status=WorktreeLifecycleStatus.ACTIVE,
        )
        source_repo_root = self._validate_source_repo_root(planned_worktree.source_repo_root)
        self._ensure_managed_worktree_path(planned_worktree.isolated_path)
        entry = self._find_registered_worktree_entry(
            source_repo_root=source_repo_root,
            isolated_path=planned_worktree.isolated_path,
        )
        if entry is None or not self._is_reusable_worktree_entry(entry):
            return None
        return replace(planned_worktree, isolated_path=entry.path, status=WorktreeLifecycleStatus.ACTIVE)

    def ensure_worktree(
        self,
        *,
        source_repo_root: Path,
        owner: WorktreeOwner,
        worktree_id: str | None = None,
        label: str | None = None,
    ) -> ManagedWorktree:
        planned_worktree = self.plan_worktree(
            source_repo_root=source_repo_root,
            owner=owner,
            worktree_id=worktree_id,
            label=label,
        )
        source_repo_root = self._validate_source_repo_root(planned_worktree.source_repo_root)
        self._ensure_managed_worktree_path(planned_worktree.isolated_path)
        existing_entry = self._find_registered_worktree_entry(
            source_repo_root=source_repo_root,
            isolated_path=planned_worktree.isolated_path,
        )
        if existing_entry is not None:
            if self._is_reusable_worktree_entry(existing_entry):
                return replace(
                    planned_worktree,
                    isolated_path=existing_entry.path,
                    status=WorktreeLifecycleStatus.ACTIVE,
                )
            self._prune_worktrees(source_repo_root)
            existing_entry = self._find_registered_worktree_entry(
                source_repo_root=source_repo_root,
                isolated_path=planned_worktree.isolated_path,
            )
            if existing_entry is not None:
                raise WorktreeServiceError(
                    "Managed worktree registration is stale and could not be pruned cleanly: "
                    f"{planned_worktree.isolated_path}"
                )
        if planned_worktree.isolated_path.exists():
            raise WorktreeCollisionError(
                "Managed worktree path already exists but is not registered with git: "
                f"{planned_worktree.isolated_path}"
            )
        self.config.root_dir.mkdir(parents=True, exist_ok=True)
        self._run_git(
            source_repo_root,
            "worktree",
            "add",
            "--detach",
            str(planned_worktree.isolated_path),
            "HEAD",
        )
        if not planned_worktree.isolated_path.exists():
            raise WorktreeServiceError(
                "git reported success creating the managed worktree, but the path was not created: "
                f"{planned_worktree.isolated_path}"
            )
        self._assert_registered_managed_worktree(
            replace(planned_worktree, status=WorktreeLifecycleStatus.ACTIVE),
            source_repo_root=source_repo_root,
        )
        return replace(planned_worktree, status=WorktreeLifecycleStatus.ACTIVE)

    def reset_worktree(self, worktree: ManagedWorktree) -> ManagedWorktree:
        source_repo_root = self._validate_source_repo_root(worktree.source_repo_root)
        self._assert_registered_managed_worktree(worktree, source_repo_root=source_repo_root)
        self._run_git(worktree.isolated_path, "reset", "--hard", "HEAD")
        self._run_git(worktree.isolated_path, "clean", "-ffd", "-x")
        return replace(worktree, status=WorktreeLifecycleStatus.ACTIVE)

    def remove_worktree(self, worktree: ManagedWorktree) -> ManagedWorktree:
        source_repo_root = self._validate_source_repo_root(worktree.source_repo_root)
        self._ensure_managed_worktree_path(worktree.isolated_path)
        existing = self._find_registered_worktree_entry(
            source_repo_root=source_repo_root,
            isolated_path=worktree.isolated_path,
        )
        if existing is None:
            if worktree.isolated_path.exists():
                raise WorktreeCollisionError(
                    "Managed worktree path exists but is not registered with git: "
                    f"{worktree.isolated_path}"
                )
            return replace(worktree, status=WorktreeLifecycleStatus.REMOVED)
        if not self._is_reusable_worktree_entry(existing):
            self._prune_worktrees(source_repo_root)
            existing = self._find_registered_worktree_entry(
                source_repo_root=source_repo_root,
                isolated_path=worktree.isolated_path,
            )
            if existing is None:
                return replace(worktree, status=WorktreeLifecycleStatus.REMOVED)
            raise WorktreeServiceError(
                "Managed worktree registration is stale and could not be pruned cleanly: "
                f"{worktree.isolated_path}"
            )
        self._run_git(source_repo_root, "worktree", "remove", "--force", str(existing.path))
        self._prune_worktrees(source_repo_root)
        if existing.path.exists():
            raise WorktreeServiceError(
                "git reported success removing the managed worktree, but the path still exists: "
                f"{existing.path}"
            )
        return replace(worktree, isolated_path=existing.path, status=WorktreeLifecycleStatus.REMOVED)

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

    def _validate_source_repo_root(self, source_repo_root: Path) -> Path:
        resolved_root = _normalize_absolute_path(source_repo_root, field_name="source_repo_root")
        if not resolved_root.exists():
            raise WorktreeRepositoryError(f"source_repo_root does not exist: {resolved_root}")
        if not resolved_root.is_dir():
            raise WorktreeRepositoryError(f"source_repo_root must be a directory: {resolved_root}")
        try:
            repo_top_level = self._run_git(resolved_root, "rev-parse", "--show-toplevel").stdout.strip()
        except WorktreeGitCommandError as exc:
            raise WorktreeRepositoryError(
                "Managed worktree lifecycle requires a usable git repository root. "
                f"Unable to inspect {resolved_root}: {exc}"
            ) from exc
        if not repo_top_level:
            raise WorktreeRepositoryError(f"Unable to resolve the git repository root for {resolved_root}")
        normalized_top_level = Path(repo_top_level).resolve()
        if normalized_top_level != resolved_root:
            raise WorktreeRepositoryError(
                "Managed worktree creation requires the main repository root, "
                f"but received {resolved_root} (git toplevel: {normalized_top_level})."
            )
        is_bare = self._run_git(resolved_root, "rev-parse", "--is-bare-repository").stdout.strip()
        if is_bare == "true":
            raise WorktreeRepositoryError(
                f"Managed worktrees require a non-bare source repository: {resolved_root}"
            )
        return resolved_root

    def _ensure_managed_worktree_path(self, path: Path) -> Path:
        resolved_path = _normalize_absolute_path(path, field_name="isolated_path")
        try:
            resolved_path.relative_to(self.config.root_dir)
        except ValueError as exc:
            raise WorktreeRepositoryError(
                "Managed worktree paths must stay under the configured worktree root "
                f"{self.config.root_dir}: {resolved_path}"
            ) from exc
        return resolved_path

    def _assert_registered_managed_worktree(
        self,
        worktree: ManagedWorktree,
        *,
        source_repo_root: Path,
    ) -> _GitWorktreeEntry:
        self._ensure_managed_worktree_path(worktree.isolated_path)
        entry = self._find_registered_worktree_entry(
            source_repo_root=source_repo_root,
            isolated_path=worktree.isolated_path,
        )
        if entry is None:
            raise WorktreeRepositoryError(
                "Managed worktree is not currently registered with the source repository: "
                f"{worktree.isolated_path}"
            )
        if not self._is_reusable_worktree_entry(entry):
            raise WorktreeRepositoryError(
                "Managed worktree is registered with git but is not currently usable. "
                f"Recreate or remove it first: {worktree.isolated_path}"
            )
        return entry

    def _find_registered_worktree_entry(
        self,
        *,
        source_repo_root: Path,
        isolated_path: Path,
    ) -> _GitWorktreeEntry | None:
        resolved_path = _normalize_absolute_path(isolated_path, field_name="isolated_path")
        for entry in self._list_worktree_entries(source_repo_root):
            if entry.path == resolved_path:
                return entry
        return None

    def _list_worktree_entries(self, source_repo_root: Path) -> list[_GitWorktreeEntry]:
        completed = self._run_git(source_repo_root, "worktree", "list", "--porcelain")
        return self._parse_worktree_list(completed.stdout)

    def _parse_worktree_list(self, stdout: str) -> list[_GitWorktreeEntry]:
        entries: list[_GitWorktreeEntry] = []
        current: dict[str, Any] = {}
        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                if current:
                    entries.append(self._build_worktree_entry(current))
                    current = {}
                continue
            key, _, value = line.partition(" ")
            if key == "worktree":
                current["path"] = Path(value).resolve()
            elif key == "HEAD":
                current["head"] = value or None
            elif key == "branch":
                current["branch"] = value or None
            elif key == "detached":
                current["detached"] = True
            elif key == "prunable":
                current["prunable_reason"] = value or "git marked the worktree as prunable"
        if current:
            entries.append(self._build_worktree_entry(current))
        return entries

    def _build_worktree_entry(self, payload: Mapping[str, Any]) -> _GitWorktreeEntry:
        path = payload.get("path")
        if not isinstance(path, Path):
            raise WorktreeServiceError("git worktree list returned an entry without a worktree path.")
        return _GitWorktreeEntry(
            path=path,
            head=payload.get("head"),
            branch=payload.get("branch"),
            detached=bool(payload.get("detached", False)),
            prunable_reason=payload.get("prunable_reason"),
        )

    def _is_reusable_worktree_entry(self, entry: _GitWorktreeEntry) -> bool:
        return entry.prunable_reason is None and entry.path.exists()

    def _prune_worktrees(self, source_repo_root: Path) -> None:
        self._run_git(source_repo_root, "worktree", "prune", "--expire", "now")

    def _run_git(
        self,
        repo_root: Path,
        *git_args: str,
    ) -> subprocess.CompletedProcess[str]:
        command = (_GIT_COMMAND_NAME, "-C", str(repo_root), *git_args)
        try:
            completed = self._git_runner(command)
        except FileNotFoundError as exc:
            raise WorktreeServiceError(
                "git executable was not found while managing worktrees. "
                "Install git and ensure it is available on PATH."
            ) from exc
        if completed.returncode != 0:
            raise WorktreeGitCommandError(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        return completed


__all__ = [
    "ManagedWorktree",
    "WorktreeExecutionTarget",
    "WorktreeCollisionError",
    "WorktreeGitCommandError",
    "WorktreeLifecycleStatus",
    "WorktreeOwner",
    "WorktreeRepositoryError",
    "WorktreeService",
    "WorktreeServiceConfig",
    "WorktreeServiceError",
]
