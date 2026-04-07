from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from string import Template
from typing import Any, Mapping, Sequence

from dormammu.agent.models import AgentRunResult
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

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.dev_dir = config.dev_dir
        self.logs_dir = config.logs_dir
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
        self._sync_operator_state(
            session_path=session_path,
            workflow_path=workflow_path,
            tasks_path=tasks_path,
            timestamp=timestamp,
        )

        return BootstrapArtifacts(
            dashboard=dashboard_path,
            tasks=tasks_path,
            session=session_path,
            workflow_state=workflow_path,
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

    def _ensure_json_file(self, path: Path, defaults: dict[str, Any]) -> None:
        current: dict[str, Any]
        if path.exists():
            current = self._read_json(path)
            merged = _deep_merge(defaults, current)
        else:
            merged = defaults
        self._write_json(path, merged)

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

    def record_latest_run(self, result: AgentRunResult) -> None:
        session_path = self.dev_dir / "session.json"
        workflow_path = self.dev_dir / "workflow_state.json"

        latest_run = result.to_dict()

        session_state = self._read_json(session_path)
        session_state["updated_at"] = result.completed_at
        session_state["latest_run"] = latest_run
        self._write_json(session_path, session_state)

        workflow_state = self._read_json(workflow_path)
        workflow_state["updated_at"] = result.completed_at
        workflow_state["latest_run"] = latest_run
        self._write_json(workflow_path, workflow_state)

    def read_session_state(self) -> dict[str, Any]:
        return self._read_json(self.dev_dir / "session.json")

    def write_session_state(self, payload: Mapping[str, Any]) -> None:
        self._write_json(self.dev_dir / "session.json", dict(payload))

    def read_workflow_state(self) -> dict[str, Any]:
        return self._read_json(self.dev_dir / "workflow_state.json")

    def write_workflow_state(self, payload: Mapping[str, Any]) -> None:
        self._write_json(self.dev_dir / "workflow_state.json", dict(payload))

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
        return report_path

    def write_continuation_prompt(self, text: str) -> Path:
        prompt_path = self.dev_dir / "continuation_prompt.txt"
        prompt_path.write_text(text, encoding="utf-8")
        return prompt_path

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.write_text(
            json.dumps(dict(payload), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
