from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from string import Template
from typing import Any, Mapping, Sequence

from dormammu.agent.models import AgentRunResult, AgentRunStarted
from dormammu.config import AppConfig
from dormammu.state.models import (
    default_dashboard_context,
    default_session_state,
    default_tasks_context,
    default_workflow_state,
)
from dormammu.state.tasks import parse_tasks_document


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _deep_merge(defaults: dict[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in current.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True, slots=True)
class BootstrapArtifacts:
    dashboard: Path
    tasks: Path
    session: Path
    workflow_state: Path
    logs_dir: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "dashboard": str(self.dashboard),
            "tasks": str(self.tasks),
            "session": str(self.session),
            "workflow_state": str(self.workflow_state),
            "logs_dir": str(self.logs_dir),
        }


class StateRepository:
    """Create and maintain the bootstrap `.dev/` state files."""

    CORE_STATE_FILENAMES = (
        "DASHBOARD.md",
        "TASKS.md",
        "session.json",
        "workflow_state.json",
    )
    OPTIONAL_STATE_FILENAMES = (
        "supervisor_report.md",
        "continuation_prompt.txt",
    )

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.dev_dir = config.dev_dir
        self.logs_dir = config.logs_dir
        self.sessions_dir = self.dev_dir / "sessions"
        self.templates_dir = config.templates_dir / "dev"

    def ensure_bootstrap_state(
        self,
        *,
        goal: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
    ) -> BootstrapArtifacts:
        timestamp = _iso_now()
        roadmap_phase_ids = list(active_roadmap_phase_ids or ["phase_1"])

        self.dev_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        dashboard_path = self.dev_dir / "DASHBOARD.md"
        tasks_path = self.dev_dir / "TASKS.md"
        session_path = self.dev_dir / "session.json"
        workflow_path = self.dev_dir / "workflow_state.json"

        dashboard_context = default_dashboard_context(
            goal=goal or "Bootstrap dormammu in the current repository.",
            roadmap_phase_ids=roadmap_phase_ids,
        )
        tasks_context = default_tasks_context()

        self._ensure_template_file(
            dashboard_path,
            "dashboard.md.tmpl",
            dashboard_context.render_values(),
        )
        self._ensure_template_file(
            tasks_path,
            "tasks.md.tmpl",
            tasks_context.render_values(),
        )

        session_defaults = default_session_state(
            timestamp=timestamp,
            app_name=self.config.app_name,
            roadmap_phase_ids=roadmap_phase_ids,
        )
        workflow_defaults = default_workflow_state(
            timestamp=timestamp,
            roadmap_phase_ids=roadmap_phase_ids,
        )

        self._ensure_json_file(session_path, session_defaults)
        self._ensure_json_file(workflow_path, workflow_defaults)
        self._refresh_active_roadmap_phase_ids(
            session_path=session_path,
            workflow_path=workflow_path,
            roadmap_phase_ids=roadmap_phase_ids,
            timestamp=timestamp,
        )
        self._sync_operator_state(
            session_path=session_path,
            workflow_path=workflow_path,
            tasks_path=tasks_path,
            timestamp=timestamp,
        )
        self._mirror_active_session_snapshot()

        return BootstrapArtifacts(
            dashboard=dashboard_path,
            tasks=tasks_path,
            session=session_path,
            workflow_state=workflow_path,
            logs_dir=self.logs_dir,
        )

    def start_new_session(
        self,
        *,
        goal: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
        session_id: str | None = None,
    ) -> BootstrapArtifacts:
        timestamp = _iso_now()
        roadmap_phase_ids = list(active_roadmap_phase_ids or ["phase_1"])

        self.dev_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._mirror_active_session_snapshot()

        dashboard_path = self.dev_dir / "DASHBOARD.md"
        tasks_path = self.dev_dir / "TASKS.md"
        session_path = self.dev_dir / "session.json"
        workflow_path = self.dev_dir / "workflow_state.json"

        next_session_id = self._normalize_session_id(
            session_id or self._generated_session_id(timestamp)
        )
        dashboard_context = default_dashboard_context(
            goal=goal or "Bootstrap dormammu in the current repository.",
            roadmap_phase_ids=roadmap_phase_ids,
        )
        tasks_context = default_tasks_context()
        self._write_template_file(
            dashboard_path,
            "dashboard.md.tmpl",
            dashboard_context.render_values(),
        )
        self._write_template_file(
            tasks_path,
            "tasks.md.tmpl",
            tasks_context.render_values(),
        )

        session_defaults = default_session_state(
            timestamp=timestamp,
            app_name=self.config.app_name,
            roadmap_phase_ids=roadmap_phase_ids,
            session_id=next_session_id,
            run_type="session",
        )
        workflow_defaults = default_workflow_state(
            timestamp=timestamp,
            roadmap_phase_ids=roadmap_phase_ids,
        )
        self._write_json(session_path, session_defaults)
        self._write_json(workflow_path, workflow_defaults)

        for extra_name in ("supervisor_report.md", "continuation_prompt.txt"):
            extra_path = self.dev_dir / extra_name
            if extra_path.exists():
                extra_path.unlink()

        self._sync_operator_state(
            session_path=session_path,
            workflow_path=workflow_path,
            tasks_path=tasks_path,
            timestamp=timestamp,
        )
        self._mirror_active_session_snapshot()
        return BootstrapArtifacts(
            dashboard=dashboard_path,
            tasks=tasks_path,
            session=session_path,
            workflow_state=workflow_path,
            logs_dir=self.logs_dir,
        )

    def restore_session(self, session_id: str) -> BootstrapArtifacts:
        normalized_session_id = self._normalize_session_id(session_id)
        target_dir = self.sessions_dir / normalized_session_id
        if not target_dir.exists():
            raise RuntimeError(f"Saved session was not found: {normalized_session_id}")
        for filename in self.CORE_STATE_FILENAMES:
            if not (target_dir / filename).exists():
                raise RuntimeError(
                    f"Saved session {normalized_session_id} is missing required file: {filename}"
                )

        self.dev_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._mirror_active_session_snapshot()

        for filename in (*self.CORE_STATE_FILENAMES, *self.OPTIONAL_STATE_FILENAMES):
            source = target_dir / filename
            target = self.dev_dir / filename
            if source.exists():
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            elif target.exists():
                target.unlink()

        self._mirror_active_session_snapshot()
        return BootstrapArtifacts(
            dashboard=self.dev_dir / "DASHBOARD.md",
            tasks=self.dev_dir / "TASKS.md",
            session=self.dev_dir / "session.json",
            workflow_state=self.dev_dir / "workflow_state.json",
            logs_dir=self.logs_dir,
        )

    def _ensure_template_file(
        self,
        path: Path,
        template_name: str,
        values: Mapping[str, str],
    ) -> None:
        if path.exists():
            return
        template = Template((self.templates_dir / template_name).read_text(encoding="utf-8"))
        path.write_text(template.safe_substitute(values), encoding="utf-8")

    def _write_template_file(
        self,
        path: Path,
        template_name: str,
        values: Mapping[str, str],
    ) -> None:
        template = Template((self.templates_dir / template_name).read_text(encoding="utf-8"))
        path.write_text(template.safe_substitute(values), encoding="utf-8")

    def _ensure_json_file(self, path: Path, defaults: dict[str, Any]) -> None:
        current: dict[str, Any]
        if path.exists():
            current = self._read_json(path)
            merged = _deep_merge(defaults, current)
        else:
            merged = defaults
        self._write_json(path, merged)

    def _refresh_active_roadmap_phase_ids(
        self,
        *,
        session_path: Path,
        workflow_path: Path,
        roadmap_phase_ids: Sequence[str],
        timestamp: str,
    ) -> None:
        session_state = self._read_json(session_path)
        session_state["updated_at"] = timestamp
        session_state["active_roadmap_phase_ids"] = list(roadmap_phase_ids)
        self._write_json(session_path, session_state)

        workflow_state = self._read_json(workflow_path)
        workflow_state["updated_at"] = timestamp
        workflow_state.setdefault("roadmap", {})
        workflow_state["roadmap"]["active_phase_ids"] = list(roadmap_phase_ids)
        self._write_json(workflow_path, workflow_state)

    def _sync_operator_state(
        self,
        *,
        session_path: Path,
        workflow_path: Path,
        tasks_path: Path,
        timestamp: str,
    ) -> None:
        parsed_tasks = parse_tasks_document(tasks_path.read_text(encoding="utf-8"))
        task_sync = parsed_tasks.current_workflow.to_dict(synced_at=timestamp)

        session_state = self._read_json(session_path)
        session_state["updated_at"] = timestamp
        session_state["task_sync"] = task_sync
        self._write_json(session_path, session_state)

        workflow_state = self._read_json(workflow_path)
        workflow_state["updated_at"] = timestamp
        workflow_state.setdefault("operator_sync", {})
        workflow_state["operator_sync"]["tasks"] = task_sync
        self._write_json(workflow_path, workflow_state)
        self._mirror_active_session_snapshot()

    def record_latest_run(self, result: AgentRunResult) -> None:
        session_path = self.dev_dir / "session.json"
        workflow_path = self.dev_dir / "workflow_state.json"

        latest_run = result.to_dict()

        session_state = self._read_json(session_path)
        session_state["updated_at"] = result.completed_at
        session_state["current_run"] = None
        session_state["latest_run"] = latest_run
        self._write_json(session_path, session_state)

        workflow_state = self._read_json(workflow_path)
        workflow_state["updated_at"] = result.completed_at
        workflow_state["current_run"] = None
        workflow_state["latest_run"] = latest_run
        self._write_json(workflow_path, workflow_state)
        self._mirror_active_session_snapshot()

    def record_current_run(self, started: AgentRunStarted) -> None:
        session_path = self.dev_dir / "session.json"
        workflow_path = self.dev_dir / "workflow_state.json"

        current_run = started.to_dict()

        session_state = self._read_json(session_path)
        session_state["updated_at"] = started.started_at
        session_state["current_run"] = current_run
        self._write_json(session_path, session_state)

        workflow_state = self._read_json(workflow_path)
        workflow_state["updated_at"] = started.started_at
        workflow_state["current_run"] = current_run
        self._write_json(workflow_path, workflow_state)
        self._mirror_active_session_snapshot()

    def read_session_state(self) -> dict[str, Any]:
        return self._read_json(self.dev_dir / "session.json")

    def write_session_state(self, payload: Mapping[str, Any]) -> None:
        self._write_json(self.dev_dir / "session.json", dict(payload))
        self._mirror_active_session_snapshot()

    def read_workflow_state(self) -> dict[str, Any]:
        return self._read_json(self.dev_dir / "workflow_state.json")

    def write_workflow_state(self, payload: Mapping[str, Any]) -> None:
        self._write_json(self.dev_dir / "workflow_state.json", dict(payload))
        self._mirror_active_session_snapshot()

    def sync_operator_state(self, *, timestamp: str | None = None) -> None:
        sync_time = timestamp or _iso_now()
        self._sync_operator_state(
            session_path=self.dev_dir / "session.json",
            workflow_path=self.dev_dir / "workflow_state.json",
            tasks_path=self.dev_dir / "TASKS.md",
            timestamp=sync_time,
        )

    def write_supervisor_report(self, markdown: str) -> Path:
        report_path = self.dev_dir / "supervisor_report.md"
        report_path.write_text(markdown, encoding="utf-8")
        self._mirror_active_session_snapshot()
        return report_path

    def write_continuation_prompt(self, text: str) -> Path:
        prompt_path = self.dev_dir / "continuation_prompt.txt"
        prompt_path.write_text(text, encoding="utf-8")
        self._mirror_active_session_snapshot()
        return prompt_path

    def list_sessions(self) -> list[dict[str, Any]]:
        active_session_id = self._current_session_id()
        if not self.sessions_dir.exists():
            return []

        sessions: list[dict[str, Any]] = []
        for session_dir in sorted(self.sessions_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            session_path = session_dir / "session.json"
            if not session_path.exists():
                continue

            session_state = self._read_json(session_path)
            workflow_path = session_dir / "workflow_state.json"
            workflow_state = self._read_json(workflow_path) if workflow_path.exists() else {}
            sessions.append(
                {
                    "session_id": session_state.get("session_id"),
                    "snapshot_dir": str(session_dir),
                    "created_at": session_state.get("created_at"),
                    "updated_at": session_state.get("updated_at"),
                    "status": session_state.get("status"),
                    "run_type": session_state.get("run_type"),
                    "active_phase": session_state.get("active_phase"),
                    "active_roadmap_phase_ids": session_state.get(
                        "active_roadmap_phase_ids",
                        [],
                    ),
                    "next_action": session_state.get("next_action"),
                    "is_active": session_state.get("session_id") == active_session_id,
                    "workflow_last_completed_phase": workflow_state.get("workflow", {}).get(
                        "last_completed_phase"
                    ),
                }
            )
        sessions.sort(
            key=lambda item: (
                str(item.get("updated_at") or ""),
                str(item.get("created_at") or ""),
            ),
            reverse=True,
        )
        return sessions

    def _generated_session_id(self, timestamp: str) -> str:
        compact = timestamp.replace("-", "").replace(":", "").replace("+", "-").replace("T", "-")
        return f"{self.config.app_name}-{compact}"

    def _normalize_session_id(self, value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
        if not normalized:
            raise ValueError("session_id must contain at least one safe filename character.")
        return normalized

    def _current_session_id(self) -> str | None:
        session_path = self.dev_dir / "session.json"
        if not session_path.exists():
            return None
        try:
            payload = self._read_json(session_path)
        except json.JSONDecodeError:
            return None
        session_id = payload.get("session_id")
        return str(session_id) if session_id else None

    def _mirror_active_session_snapshot(self) -> None:
        session_id = self._current_session_id()
        if session_id is None:
            return

        target_dir = self.sessions_dir / session_id
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in (*self.CORE_STATE_FILENAMES, *self.OPTIONAL_STATE_FILENAMES):
            source = self.dev_dir / filename
            target = target_dir / filename
            if source.exists():
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            elif target.exists():
                target.unlink()

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.write_text(
            json.dumps(dict(payload), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
