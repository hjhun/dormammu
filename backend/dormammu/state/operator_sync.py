"""Root-index and operator-mirror synchronisation for .dev/ state.

This module owns the mechanics of keeping the root ``.dev/session.json`` and
``.dev/workflow_state.json`` files in sync with the active session's copies,
and of mirroring operator-facing Markdown files (DASHBOARD.md, PLAN.md,
TASKS.md, WORKFLOWS.md) between the root and the session directory.

It is intentionally free of bootstrap-generation and session-lifecycle concerns.
"""
from __future__ import annotations

import contextlib
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator, Mapping, Sequence

try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False

from dormammu._utils import iso_now as _iso_now
from dormammu.state.models import ManagedWorktreeState
from dormammu.state.persistence import ensure_json_file, read_json, write_json
from dormammu.state.tasks import parse_tasks_document

if TYPE_CHECKING:
    from dormammu.config import AppConfig


ROOT_OPERATOR_MIRROR_FILENAMES = (
    "DASHBOARD.md",
    "PLAN.md",
    "TASKS.md",
    "WORKFLOWS.md",
)


def _runtime_skill_summary(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    latest = payload.get("latest")
    if not isinstance(latest, Mapping):
        return None
    summary = latest.get("summary")
    profile = latest.get("profile")
    if not isinstance(summary, Mapping) or not isinstance(profile, Mapping):
        return None
    result = {
        "active_role": payload.get("active_role"),
        "profile_name": profile.get("name"),
        "profile_source": profile.get("source"),
    }
    for key in (
        "selected_count",
        "visible_count",
        "hidden_count",
        "preloaded_count",
        "missing_preload_count",
        "shadowed_count",
        "custom_visible_count",
        "interesting_for_operator",
    ):
        result[key] = summary.get(key)
    return result


class OperatorSync:
    """Synchronise root-index JSON and operator-facing Markdown mirrors.

    Parameters
    ----------
    config:
        Runtime application config.
    base_dev_dir:
        The root ``.dev/`` directory (not a session subdirectory).
    """

    def __init__(self, config: AppConfig, base_dev_dir: Path) -> None:
        self.config = config
        self.base_dev_dir = base_dev_dir

    # ------------------------------------------------------------------
    # File lock
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def root_index_lock(self) -> Generator[None, None, None]:
        """Acquire an exclusive file lock on the root .dev/ index files.

        Prevents concurrent writes from multiple dormammu sessions racing on
        ``.dev/session.json`` and ``.dev/workflow_state.json``.  Falls back to
        a no-op context on platforms that lack ``fcntl`` (e.g. Windows).
        """
        self.base_dev_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.base_dev_dir / ".dev_lock"
        with lock_path.open("a", encoding="utf-8") as lock_file:
            if _HAS_FCNTL:
                _fcntl.flock(lock_file, _fcntl.LOCK_EX)
            try:
                yield
            finally:
                if _HAS_FCNTL:
                    _fcntl.flock(lock_file, _fcntl.LOCK_UN)

    # ------------------------------------------------------------------
    # Root index write
    # ------------------------------------------------------------------

    def write_root_index_for_session(
        self,
        *,
        session_dev_dir: Path,
        session_id: str,
        state_root: str,
        timestamp: str,
        list_sessions_fn: Any,
    ) -> None:
        """Atomically update the root index under a file lock."""
        with self.root_index_lock():
            self._write_root_index_locked(
                session_dev_dir=session_dev_dir,
                session_id=session_id,
                state_root=state_root,
                timestamp=timestamp,
                list_sessions_fn=list_sessions_fn,
            )

    def _write_root_index_locked(
        self,
        *,
        session_dev_dir: Path,
        session_id: str,
        state_root: str,
        timestamp: str,
        list_sessions_fn: Any,
    ) -> None:
        session_state = read_json(session_dev_dir / "session.json")
        workflow_state = read_json(session_dev_dir / "workflow_state.json")
        session_worktrees = ManagedWorktreeState.from_dict(session_state.get("worktrees"))
        workflow_worktrees = ManagedWorktreeState.from_dict(workflow_state.get("worktrees"))

        session_defaults: dict[str, Any] = {
            "active_session_id": session_id,
            "default_session_id": session_id,
            "selected_at": timestamp,
            "updated_at": timestamp,
            "state_schema_version": session_state.get("state_schema_version"),
            "current_session": {
                "session_id": session_id,
                "state_root": state_root,
                "session_path": f"{state_root}/session.json",
                "workflow_path": f"{state_root}/workflow_state.json",
                "dashboard_path": f"{state_root}/DASHBOARD.md",
                "plan_path": f"{state_root}/PLAN.md",
                "tasks_path": f"{state_root}/TASKS.md",
                "logs_dir": f"{state_root}/logs",
                "goal": session_state.get("bootstrap", {}).get("goal"),
                "updated_at": session_state.get("updated_at"),
                "active_phase": session_state.get("active_phase"),
                "active_roadmap_phase_ids": session_state.get("active_roadmap_phase_ids", []),
                "active_worktree_id": session_worktrees.active_worktree_id,
                "managed_worktree_count": session_worktrees.managed_count,
                "runtime_skills": _runtime_skill_summary(session_state.get("runtime_skills")),
            },
        }
        workflow_defaults: dict[str, Any] = {
            "version": workflow_state.get("version", 1),
            "state_schema_version": workflow_state.get("state_schema_version"),
            "updated_at": timestamp,
            "mode": workflow_state.get("mode", "supervised"),
            "active_session_id": session_id,
            "default_session_id": session_id,
            "source_of_truth": {
                "goal": workflow_state.get("source_of_truth", {}).get("goal", []),
                "machine_state": ".dev/workflow_state.json",
                "operator_state": [],
                "session_machine_state": f"{state_root}/workflow_state.json",
                "session_operator_state": [
                    f"{state_root}/DASHBOARD.md",
                    f"{state_root}/PLAN.md",
                    f"{state_root}/TASKS.md",
                ],
            },
            "session_index": {
                "active_session_id": session_id,
                "sessions_dir": ".dev/sessions",
            },
            "current_session": {
                "session_id": session_id,
                "state_root": state_root,
                "workflow_path": f"{state_root}/workflow_state.json",
                "session_path": f"{state_root}/session.json",
                "tasks_path": f"{state_root}/TASKS.md",
                "goal": workflow_state.get("bootstrap", {}).get("goal"),
                "updated_at": workflow_state.get("updated_at"),
                "active_worktree_id": workflow_worktrees.active_worktree_id,
                "managed_worktree_count": workflow_worktrees.managed_count,
                "runtime_skills": _runtime_skill_summary(workflow_state.get("runtime_skills")),
            },
            "sessions": list_sessions_fn(),
        }

        ensure_json_file(self.base_dev_dir / "session.json", session_defaults)
        root_session = read_json(self.base_dev_dir / "session.json")
        root_session["state_schema_version"] = session_defaults["state_schema_version"]
        root_session["active_session_id"] = session_id
        root_session["default_session_id"] = session_id
        root_session["selected_at"] = timestamp
        root_session["updated_at"] = timestamp
        root_session["current_session"] = session_defaults["current_session"]
        write_json(self.base_dev_dir / "session.json", root_session)

        ensure_json_file(self.base_dev_dir / "workflow_state.json", workflow_defaults)
        root_workflow = read_json(self.base_dev_dir / "workflow_state.json")
        root_workflow["state_schema_version"] = workflow_defaults["state_schema_version"]
        root_workflow["updated_at"] = timestamp
        root_workflow["active_session_id"] = session_id
        root_workflow["default_session_id"] = session_id
        root_workflow["source_of_truth"] = workflow_defaults["source_of_truth"]
        root_workflow["session_index"] = workflow_defaults["session_index"]
        root_workflow["current_session"] = workflow_defaults["current_session"]
        root_workflow["sessions"] = list_sessions_fn()
        for key in ("bootstrap", "intake", "workflow_policy", "roadmap"):
            value = workflow_state.get(key)
            if isinstance(value, Mapping):
                root_workflow[key] = dict(value)
            elif key in root_workflow:
                root_workflow.pop(key, None)
        write_json(self.base_dev_dir / "workflow_state.json", root_workflow)

        self.sync_root_operator_mirrors(
            session_dev_dir=session_dev_dir,
            active_session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Mirror sync
    # ------------------------------------------------------------------

    def _read_active_session_id(self) -> str | None:
        """Read the active session ID from the root index file."""
        from dormammu.state.session_manager import SessionManager

        return SessionManager.current_session_id(self.base_dev_dir / "session.json")

    def sync_root_operator_mirrors(
        self,
        *,
        session_dev_dir: Path,
        active_session_id: str,
    ) -> None:
        """Copy operator Markdown files from session dir to root ``.dev/``."""
        if self._read_active_session_id() != active_session_id:
            return
        self.base_dev_dir.mkdir(parents=True, exist_ok=True)
        for filename in ROOT_OPERATOR_MIRROR_FILENAMES:
            source = session_dev_dir / filename
            target = self.base_dev_dir / filename
            if source.exists():
                shutil.copy2(source, target)
            elif target.exists():
                target.unlink()

    def sync_active_root_operator_mirrors_into_session(
        self,
        *,
        session_dev_dir: Path,
        active_session_id: str,
    ) -> None:
        """Copy newer root operator Markdown files into the active session dir."""
        if self._read_active_session_id() != active_session_id:
            return
        for filename in ROOT_OPERATOR_MIRROR_FILENAMES:
            root_path = self.base_dev_dir / filename
            session_path = session_dev_dir / filename
            if not root_path.exists():
                continue
            if not session_path.exists():
                shutil.copy2(root_path, session_path)
                continue
            root_stat = root_path.stat()
            session_stat = session_path.stat()
            if root_stat.st_mtime_ns <= session_stat.st_mtime_ns:
                continue
            root_text = root_path.read_text(encoding="utf-8")
            session_text = session_path.read_text(encoding="utf-8")
            if root_text != session_text:
                shutil.copy2(root_path, session_path)

    # ------------------------------------------------------------------
    # Operator task sync
    # ------------------------------------------------------------------

    def refresh_active_roadmap_phase_ids(
        self,
        *,
        session_path: Path,
        workflow_path: Path,
        roadmap_phase_ids: Sequence[str],
        timestamp: str,
    ) -> None:
        """Persist the active roadmap phase IDs into both state files."""
        normalized_phase_ids = list(roadmap_phase_ids)

        session_state = read_json(session_path)
        session_state["updated_at"] = timestamp
        session_state["active_roadmap_phase_ids"] = normalized_phase_ids
        session_loop = session_state.get("loop")
        if isinstance(session_loop, dict):
            request_payload = session_loop.get("request")
            if isinstance(request_payload, dict):
                request_payload["expected_roadmap_phase_id"] = (
                    normalized_phase_ids[0] if normalized_phase_ids else None
                )
        write_json(session_path, session_state)

        workflow_state = read_json(workflow_path)
        workflow_state["updated_at"] = timestamp
        workflow_state.setdefault("roadmap", {})
        workflow_state["roadmap"]["active_phase_ids"] = normalized_phase_ids
        workflow_loop = workflow_state.get("loop")
        if isinstance(workflow_loop, dict):
            request_payload = workflow_loop.get("request")
            if isinstance(request_payload, dict):
                request_payload["expected_roadmap_phase_id"] = (
                    normalized_phase_ids[0] if normalized_phase_ids else None
                )
        write_json(workflow_path, workflow_state)

    def sync_operator_state(
        self,
        *,
        session_path: Path,
        workflow_path: Path,
        operator_task_path: Path,
        timestamp: str,
        dev_dir: Path,
        display_state_path_fn: Any,
    ) -> None:
        """Parse operator task document and write task-sync state into JSON."""
        resolved_path = self.resolve_operator_sync_source(
            preferred_path=operator_task_path,
            dev_dir=dev_dir,
        )
        operator_text = (
            resolved_path.read_text(encoding="utf-8") if resolved_path.exists() else ""
        )
        operator_mtime = resolved_path.stat().st_mtime if resolved_path.exists() else None

        if operator_mtime is not None and session_path.exists():
            try:
                stored = read_json(session_path)
                stored_mtime = stored.get("operator_state_mtime")
                if stored_mtime is not None and abs(operator_mtime - float(stored_mtime)) > 1.0:
                    print(
                        f"[dormammu] Warning: {resolved_path.name} was modified externally "
                        f"(stored mtime={stored_mtime:.3f}, current={operator_mtime:.3f}). "
                        "Manual edits will be preserved by re-reading the file.",
                        file=sys.stderr,
                    )
            except Exception:
                pass

        parsed_tasks = parse_tasks_document(
            operator_text,
            source=display_state_path_fn(resolved_path),
        )
        task_sync = parsed_tasks.current_workflow.to_dict(synced_at=timestamp)

        session_state = read_json(session_path)
        session_state["updated_at"] = timestamp
        session_state["task_sync"] = task_sync
        if operator_mtime is not None:
            session_state["operator_state_mtime"] = operator_mtime
        write_json(session_path, session_state)

        workflow_state = read_json(workflow_path)
        workflow_state["updated_at"] = timestamp
        workflow_state.setdefault("operator_sync", {})
        workflow_state["operator_sync"]["tasks"] = task_sync
        write_json(workflow_path, workflow_state)

    @staticmethod
    def resolve_operator_sync_source(
        *,
        preferred_path: Path,
        dev_dir: Path,
    ) -> Path:
        """Choose the best operator checklist source for task-sync state.

        Prefers the checklist file with the fewest pending ``- [ ]`` items
        (most progress) to avoid the supervisor seeing stale data when the
        agent has been updating PLAN.md rather than TASKS.md.
        """
        candidates: list[Path] = []
        seen: set[Path] = set()
        for path in (preferred_path, dev_dir / "PLAN.md", dev_dir / "TASKS.md"):
            resolved = path.resolve()
            if resolved in seen or not path.exists():
                continue
            seen.add(resolved)
            candidates.append(path)

        if not candidates:
            return preferred_path
        if len(candidates) == 1:
            return candidates[0]

        def _pending_count(path: Path) -> int:
            try:
                return path.read_text(encoding="utf-8").count("- [ ] ")
            except OSError:
                return 999

        best = min(
            candidates,
            key=lambda p: (_pending_count(p), -p.stat().st_mtime_ns, p.name != "TASKS.md"),
        )
        return best if best.exists() else preferred_path
