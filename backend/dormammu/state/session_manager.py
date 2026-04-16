"""Session identity, listing, migration, and snapshot operations.

This module owns everything related to *which* session is active, how session
IDs are generated, how old sessions are listed, and how a legacy flat-root
``.dev/`` layout is migrated into the session-subdirectory model.

It is intentionally free of bootstrap-generation and operator-sync concerns.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from dormammu._utils import iso_now as _iso_now
from dormammu.config import AppConfig
from dormammu.state.persistence import read_json, write_json


_CORE_STATE_FILENAMES = (
    "DASHBOARD.md",
    "PLAN.md",
    "session.json",
    "workflow_state.json",
)
_OPTIONAL_STATE_FILENAMES = (
    "supervisor_report.md",
    "continuation_prompt.txt",
)


class SessionManager:
    """Manage session identity, enumeration, and lifecycle snapshots.

    Parameters
    ----------
    config:
        Runtime application config — used for ``app_name`` and path resolution.
    base_dev_dir:
        The root ``.dev/`` directory (not a session subdirectory).
    sessions_dir:
        The ``.dev/sessions/`` directory that holds per-session subdirectories.
    """

    def __init__(
        self,
        config: AppConfig,
        base_dev_dir: Path,
        sessions_dir: Path,
    ) -> None:
        self.config = config
        self.base_dev_dir = base_dev_dir
        self.sessions_dir = sessions_dir

    # ------------------------------------------------------------------
    # Session ID helpers
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_session_id(value: str) -> str:
        """Return a filesystem-safe session ID from *value*."""
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
        if not normalized:
            raise ValueError("session_id must contain at least one safe filename character.")
        return normalized

    def generated_session_id(self, timestamp: str) -> str:
        """Generate a unique session ID based on *timestamp*."""
        compact = (
            timestamp.replace("-", "").replace(":", "").replace("+", "-").replace("T", "-")
        )
        base = f"{self.config.app_name}-{compact}"
        candidate = base
        sequence = 1
        while (self.sessions_dir / candidate).exists():
            candidate = f"{base}-{sequence:02d}"
            sequence += 1
        return candidate

    @staticmethod
    def current_session_id(session_path: Path) -> str | None:
        """Read the active session ID recorded inside *session_path*."""
        if not session_path.exists():
            return None
        try:
            payload = read_json(session_path)
        except json.JSONDecodeError:
            return None
        session_id = payload.get("session_id") or payload.get("active_session_id")
        return str(session_id) if session_id else None

    def read_active_session_id(self) -> str | None:
        """Return the active session ID recorded in the root ``.dev/session.json``."""
        return self.current_session_id(self.base_dev_dir / "session.json")

    # ------------------------------------------------------------------
    # Session listing
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return a sorted list of all known sessions with summary metadata."""
        active_session_id = self.read_active_session_id()
        if not self.sessions_dir.exists():
            return []

        sessions: list[dict[str, Any]] = []
        for session_dir in sorted(self.sessions_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            session_path = session_dir / "session.json"
            if not session_path.exists():
                continue

            session_state = read_json(session_path)
            workflow_path = session_dir / "workflow_state.json"
            workflow_state = read_json(workflow_path) if workflow_path.exists() else {}
            bootstrap = session_state.get("bootstrap") or {}
            raw_goal = bootstrap.get("goal") or session_state.get("goal") or ""
            goal_summary = (raw_goal[:120] + "...") if len(raw_goal) > 120 else raw_goal
            loop_state = session_state.get("loop") or workflow_state.get("loop") or {}
            supervisor_verdict = loop_state.get("latest_supervisor_verdict")
            attempts_completed = loop_state.get("attempts_completed")
            session_id = session_state.get("session_id")
            sessions.append(
                {
                    "session_id": session_id,
                    "snapshot_dir": str(session_dir),
                    "created_at": session_state.get("created_at"),
                    "updated_at": session_state.get("updated_at"),
                    "goal": goal_summary,
                    "is_active": session_id == active_session_id,
                    "supervisor_verdict": supervisor_verdict,
                    "attempts_completed": attempts_completed,
                }
            )

        return sorted(
            sessions,
            key=lambda s: (s.get("updated_at") or s.get("created_at") or ""),
            reverse=False,
        )

    # ------------------------------------------------------------------
    # Legacy migration and snapshots
    # ------------------------------------------------------------------

    def has_legacy_root_snapshot(self) -> bool:
        """Return True if the root ``.dev/`` still contains un-migrated state files."""
        return any(
            (self.base_dev_dir / filename).exists()
            for filename in (*_CORE_STATE_FILENAMES, "TASKS.md")
        )

    @staticmethod
    def copy_state_snapshot(source_dir: Path, target_dir: Path) -> None:
        """Copy core and optional state files from *source_dir* to *target_dir*."""
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in (*_CORE_STATE_FILENAMES, *_OPTIONAL_STATE_FILENAMES):
            source = source_dir / filename
            target = target_dir / filename
            if source.exists():
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            elif target.exists():
                target.unlink()

        source_tasks_path = source_dir / "TASKS.md"
        target_tasks_path = target_dir / "TASKS.md"
        if source_tasks_path.exists():
            target_tasks_path.write_text(
                source_tasks_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        elif target_tasks_path.exists():
            target_tasks_path.unlink()

        legacy_tasks_path = source_dir / "TASKS.md"
        target_plan_path = target_dir / "PLAN.md"
        if legacy_tasks_path.exists() and not target_plan_path.exists():
            target_plan_path.write_text(
                legacy_tasks_path.read_text(encoding="utf-8"), encoding="utf-8"
            )

    def migrate_legacy_root_snapshot(self, *, timestamp: str | None = None) -> str | None:
        """Move a flat-root ``.dev/`` layout into a session subdirectory.

        Returns the session ID that was migrated (or already existed), or
        ``None`` when no migration was needed.
        """
        from dormammu.state.models import STATE_SCHEMA_VERSION

        legacy_session_id = self.read_active_session_id()
        if legacy_session_id is not None and (self.sessions_dir / legacy_session_id).exists():
            return legacy_session_id
        if not self.has_legacy_root_snapshot():
            return None

        session_id = legacy_session_id or self.generated_session_id(timestamp or _iso_now())
        target_dir = self.sessions_dir / session_id
        self.copy_state_snapshot(self.base_dev_dir, target_dir)
        legacy_logs_dir = self.base_dev_dir / "logs"
        target_logs_dir = target_dir / "logs"
        if legacy_logs_dir.exists() and not target_logs_dir.exists():
            shutil.copytree(legacy_logs_dir, target_logs_dir)

        session_path = target_dir / "session.json"
        if session_path.exists():
            session_state = read_json(session_path)
            session_state["session_id"] = session_id
            session_state.setdefault("state_schema_version", STATE_SCHEMA_VERSION)
            write_json(session_path, session_state)
        return session_id

    def read_legacy_root_session_payload(self) -> dict[str, Any] | None:
        """Return the root session.json payload if it predates the session model.

        Returns ``None`` when the root session file is already an index
        (contains ``active_session_id``) or does not exist.
        """
        session_path = self.base_dev_dir / "session.json"
        if not session_path.exists():
            return None
        payload = read_json(session_path)
        if "active_session_id" in payload:
            return None
        if "session_id" not in payload:
            return None
        return payload
