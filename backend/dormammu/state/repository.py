from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from string import Template
from typing import Any, Mapping, Sequence

from dormammu.agent.models import AgentRunResult, AgentRunStarted
from dormammu.config import AppConfig
from dormammu.guidance import resolve_guidance_files
from dormammu.state.models import (
    default_dashboard_context,
    default_plan_context,
    default_session_state,
    default_workflow_state,
    discover_repo_guidance,
    prompt_fingerprint,
    summarize_prompt_goal,
)
from dormammu.state.tasks import parse_tasks_document


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _deep_merge(defaults: dict[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in current.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True, slots=True)
class BootstrapArtifacts:
    dashboard: Path
    plan: Path
    session: Path
    workflow_state: Path
    logs_dir: Path
    prompt: Path | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "dashboard": str(self.dashboard),
            "plan": str(self.plan),
            "tasks": str(self.plan),
            "session": str(self.session),
            "workflow_state": str(self.workflow_state),
            "logs_dir": str(self.logs_dir),
        }
        if self.prompt is not None:
            payload["prompt"] = str(self.prompt)
        return payload


class StateRepository:
    """Create and maintain the bootstrap `.dev/` state files."""

    CORE_STATE_FILENAMES = (
        "DASHBOARD.md",
        "PLAN.md",
        "session.json",
        "workflow_state.json",
    )
    OPTIONAL_STATE_FILENAMES = (
        "supervisor_report.md",
        "continuation_prompt.txt",
    )

    def __init__(self, config: AppConfig, session_id: str | None = None) -> None:
        self.config = config
        self.base_dev_dir = config.base_dev_dir
        self.templates_dir = config.templates_dir / "dev"
        self.sessions_dir = self.base_dev_dir / "sessions"
        self.session_id = self._normalize_session_id(session_id) if session_id else None
        self.dev_dir = (
            self.sessions_dir / self.session_id
            if self.session_id is not None
            else config.dev_dir
        )
        self.logs_dir = self.dev_dir / "logs"

    def for_session(self, session_id: str) -> StateRepository:
        return StateRepository(self.config, session_id=session_id)

    def state_file(self, name: str) -> Path:
        return self.dev_dir / name

    def ensure_bootstrap_state(
        self,
        *,
        goal: str | None = None,
        prompt_text: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
    ) -> BootstrapArtifacts:
        if self.session_id is None:
            return self._ensure_root_bootstrap_state(
                goal=goal,
                prompt_text=prompt_text,
                active_roadmap_phase_ids=active_roadmap_phase_ids,
            )

        return self._ensure_session_bootstrap_state(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=active_roadmap_phase_ids,
        )

    def _ensure_root_bootstrap_state(
        self,
        *,
        goal: str | None = None,
        prompt_text: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
    ) -> BootstrapArtifacts:
        timestamp = _iso_now()
        self.base_dev_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        legacy_session_payload = self._read_legacy_root_session_payload()
        active_session_id = self._read_active_session_id()
        if active_session_id is None:
            active_session_id = self._migrate_legacy_root_snapshot(timestamp=timestamp)
        if active_session_id is None:
            active_session_id = self._generated_session_id(timestamp)

        session_repository = self.for_session(active_session_id)
        artifacts = session_repository._ensure_session_bootstrap_state(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=active_roadmap_phase_ids,
        )
        if legacy_session_payload is not None:
            migrated_session = session_repository._read_json(session_repository.state_file("session.json"))
            merged_session = _deep_merge(migrated_session, legacy_session_payload)
            merged_session["session_id"] = active_session_id
            session_repository._write_json(session_repository.state_file("session.json"), merged_session)
        self._write_root_index_for_session(
            session_repository=session_repository,
            timestamp=timestamp,
        )
        return artifacts

    def _ensure_session_bootstrap_state(
        self,
        *,
        goal: str | None = None,
        prompt_text: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
    ) -> BootstrapArtifacts:
        timestamp = _iso_now()
        roadmap_phase_ids = list(active_roadmap_phase_ids or ["phase_1"])
        guidance = discover_repo_guidance(
            self.config.repo_root,
            rule_paths=resolve_guidance_files(self.config),
        )
        session_id = self._current_session_id(self.dev_dir / "session.json") or self.session_id
        resolved_goal = (
            goal
            or self._existing_goal()
            or summarize_prompt_goal(
                prompt_text,
                fallback="Bootstrap dormammu in the current repository.",
            )
        )

        self.dev_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        dashboard_path = self.state_file("DASHBOARD.md")
        plan_path = self.state_file("PLAN.md")
        session_path = self.state_file("session.json")
        workflow_path = self.state_file("workflow_state.json")
        state_root = self._state_root_display()
        self._ensure_plan_file(plan_path)

        if self._should_regenerate_operator_state(
            prompt_text=prompt_text,
            dashboard_path=dashboard_path,
            plan_path=plan_path,
        ):
            self._reset_bootstrap_state(
                goal=resolved_goal,
                prompt_text=prompt_text,
                roadmap_phase_ids=roadmap_phase_ids,
                session_id=session_id or self._generated_session_id(timestamp),
                timestamp=timestamp,
            )
            self._sync_root_index(timestamp=timestamp)
            return self._artifacts()

        dashboard_context = default_dashboard_context(
            goal=resolved_goal,
            roadmap_phase_ids=roadmap_phase_ids,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )
        plan_context = default_plan_context(
            goal=resolved_goal,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )

        self._ensure_template_file(
            dashboard_path,
            "dashboard.md.tmpl",
            dashboard_context.render_values(),
        )
        self._ensure_template_file(plan_path, "plan.md.tmpl", plan_context.render_values())

        session_defaults = default_session_state(
            timestamp=timestamp,
            app_name=self.config.app_name,
            roadmap_phase_ids=roadmap_phase_ids,
            goal=resolved_goal,
            state_root=state_root,
            prompt_text=prompt_text,
            repo_guidance=guidance,
            session_id=session_id,
        )
        workflow_defaults = default_workflow_state(
            timestamp=timestamp,
            roadmap_phase_ids=roadmap_phase_ids,
            goal=resolved_goal,
            state_root=state_root,
            prompt_text=prompt_text,
            repo_guidance=guidance,
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
            plan_path=plan_path,
            timestamp=timestamp,
        )
        self._sync_root_index(timestamp=timestamp)
        return self._artifacts()

    def _should_regenerate_operator_state(
        self,
        *,
        prompt_text: str | None,
        dashboard_path: Path,
        plan_path: Path,
    ) -> bool:
        if not dashboard_path.exists() or not plan_path.exists():
            return False
        incoming_fingerprint = prompt_fingerprint(prompt_text)
        if incoming_fingerprint is None:
            return False
        stored_fingerprint = self._stored_prompt_fingerprint()
        if stored_fingerprint is None:
            return False
        return stored_fingerprint != incoming_fingerprint

    def _stored_prompt_fingerprint(self) -> str | None:
        for candidate in (
            self.state_file("session.json"),
            self.state_file("workflow_state.json"),
        ):
            if not candidate.exists():
                continue
            try:
                payload = self._read_json(candidate)
            except json.JSONDecodeError:
                continue
            bootstrap = payload.get("bootstrap")
            if not isinstance(bootstrap, Mapping):
                continue
            fingerprint = bootstrap.get("prompt_fingerprint")
            if isinstance(fingerprint, str) and fingerprint.strip():
                return fingerprint
            for key in ("prompt_path", "global_prompt_path"):
                prompt_path_value = bootstrap.get(key)
                if not isinstance(prompt_path_value, str) or not prompt_path_value.strip():
                    continue
                prompt_path = Path(prompt_path_value)
                if not prompt_path.is_absolute():
                    prompt_path = self.config.repo_root / prompt_path
                if prompt_path.exists():
                    return prompt_fingerprint(prompt_path.read_text(encoding="utf-8"))
        return None

    def start_new_session(
        self,
        *,
        goal: str | None = None,
        prompt_text: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
        session_id: str | None = None,
    ) -> BootstrapArtifacts:
        if self.session_id is not None:
            raise RuntimeError("start_new_session must be called from the active repository.")

        timestamp = _iso_now()
        roadmap_phase_ids = list(active_roadmap_phase_ids or ["phase_1"])
        next_session_id = self._normalize_session_id(
            session_id or self._generated_session_id(timestamp)
        )

        self.base_dev_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_root_snapshot(timestamp=timestamp)

        session_repository = self.for_session(next_session_id)
        session_repository._reset_bootstrap_state(
            goal=goal or "Bootstrap dormammu in the current repository.",
            prompt_text=prompt_text,
            roadmap_phase_ids=roadmap_phase_ids,
            session_id=next_session_id,
            timestamp=timestamp,
        )
        self._write_root_index_for_session(
            session_repository=session_repository,
            timestamp=timestamp,
        )
        return self._artifacts_for_dir(session_repository.dev_dir)

    def restore_session(self, session_id: str) -> BootstrapArtifacts:
        normalized_session_id = self._normalize_session_id(session_id)
        target_dir = self.sessions_dir / normalized_session_id
        if not target_dir.exists():
            raise RuntimeError(f"Saved session was not found: {normalized_session_id}")
        self.for_session(normalized_session_id)._ensure_plan_file(target_dir / "PLAN.md")
        required_files = (
            "DASHBOARD.md",
            "PLAN.md",
            "session.json",
            "workflow_state.json",
        )
        for filename in required_files:
            if not (target_dir / filename).exists():
                raise RuntimeError(
                    f"Saved session {normalized_session_id} is missing required file: {filename}"
                )

        self.base_dev_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_root_snapshot()
        self._write_root_index_for_session(
            session_repository=self.for_session(normalized_session_id),
            timestamp=_iso_now(),
        )
        return self._artifacts_for_dir(target_dir)

    def read_session_state(self) -> dict[str, Any]:
        if self.session_id is None:
            return self._active_session_repository().read_session_state()
        return self._read_json(self.state_file("session.json"))

    def write_session_state(self, payload: Mapping[str, Any]) -> None:
        if self.session_id is None:
            self._active_session_repository().write_session_state(payload)
            return
        self._write_json(self.state_file("session.json"), dict(payload))
        self._sync_root_index()

    def read_workflow_state(self) -> dict[str, Any]:
        if self.session_id is None:
            return self._active_session_repository().read_workflow_state()
        return self._read_json(self.state_file("workflow_state.json"))

    def write_workflow_state(self, payload: Mapping[str, Any]) -> None:
        if self.session_id is None:
            self._active_session_repository().write_workflow_state(payload)
            return
        self._write_json(self.state_file("workflow_state.json"), dict(payload))
        self._sync_root_index()

    def sync_operator_state(self, *, timestamp: str | None = None) -> None:
        if self.session_id is None:
            self._active_session_repository().sync_operator_state(timestamp=timestamp)
            return
        sync_time = timestamp or _iso_now()
        self._sync_operator_state(
            session_path=self.state_file("session.json"),
            workflow_path=self.state_file("workflow_state.json"),
            plan_path=self._operator_plan_path(),
            timestamp=sync_time,
        )

    def record_latest_run(self, result: AgentRunResult) -> None:
        if self.session_id is None:
            self._active_session_repository().record_latest_run(result)
            return
        session_path = self.state_file("session.json")
        workflow_path = self.state_file("workflow_state.json")
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
        self._sync_root_index(timestamp=result.completed_at)

    def record_current_run(self, started: AgentRunStarted) -> None:
        if self.session_id is None:
            self._active_session_repository().record_current_run(started)
            return
        session_path = self.state_file("session.json")
        workflow_path = self.state_file("workflow_state.json")
        current_run = started.to_dict()

        session_state = self._read_json(session_path)
        session_state["updated_at"] = started.started_at
        session_state["current_run"] = current_run
        self._write_json(session_path, session_state)

        workflow_state = self._read_json(workflow_path)
        workflow_state["updated_at"] = started.started_at
        workflow_state["current_run"] = current_run
        self._write_json(workflow_path, workflow_state)
        self._sync_root_index(timestamp=started.started_at)

    def write_supervisor_report(self, markdown: str) -> Path:
        if self.session_id is None:
            return self._active_session_repository().write_supervisor_report(markdown)
        report_path = self.state_file("supervisor_report.md")
        report_path.write_text(markdown, encoding="utf-8")
        self._sync_root_index()
        return report_path

    def write_continuation_prompt(self, text: str) -> Path:
        if self.session_id is None:
            return self._active_session_repository().write_continuation_prompt(text)
        prompt_path = self.state_file("continuation_prompt.txt")
        prompt_path.write_text(text, encoding="utf-8")
        self._sync_root_index()
        return prompt_path

    def list_sessions(self) -> list[dict[str, Any]]:
        active_session_id = self._read_active_session_id()
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

    def _existing_goal(self) -> str | None:
        for candidate in (
            self.state_file("workflow_state.json"),
            self.state_file("session.json"),
        ):
            if not candidate.exists():
                continue
            try:
                payload = self._read_json(candidate)
            except json.JSONDecodeError:
                continue
            bootstrap = payload.get("bootstrap")
            if isinstance(bootstrap, Mapping):
                goal = bootstrap.get("goal")
                if isinstance(goal, str) and goal.strip():
                    return goal
        return None

    def _reset_bootstrap_state(
        self,
        *,
        goal: str,
        prompt_text: str | None,
        roadmap_phase_ids: Sequence[str],
        session_id: str,
        timestamp: str,
    ) -> None:
        guidance = discover_repo_guidance(
            self.config.repo_root,
            rule_paths=resolve_guidance_files(self.config),
        )
        self.dev_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        dashboard_path = self.state_file("DASHBOARD.md")
        plan_path = self.state_file("PLAN.md")
        session_path = self.state_file("session.json")
        workflow_path = self.state_file("workflow_state.json")
        state_root = self._state_root_display()

        dashboard_context = default_dashboard_context(
            goal=goal,
            roadmap_phase_ids=roadmap_phase_ids,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )
        plan_context = default_plan_context(
            goal=goal,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )
        self._write_template_file(
            dashboard_path,
            "dashboard.md.tmpl",
            dashboard_context.render_values(),
        )
        self._write_template_file(plan_path, "plan.md.tmpl", plan_context.render_values())

        session_defaults = default_session_state(
            timestamp=timestamp,
            app_name=self.config.app_name,
            roadmap_phase_ids=roadmap_phase_ids,
            goal=goal,
            state_root=state_root,
            prompt_text=prompt_text,
            repo_guidance=guidance,
            session_id=session_id,
            run_type="session",
        )
        workflow_defaults = default_workflow_state(
            timestamp=timestamp,
            roadmap_phase_ids=roadmap_phase_ids,
            goal=goal,
            state_root=state_root,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )
        self._write_json(session_path, session_defaults)
        self._write_json(workflow_path, workflow_defaults)

        for extra_name in self.OPTIONAL_STATE_FILENAMES:
            extra_path = self.state_file(extra_name)
            if extra_path.exists():
                extra_path.unlink()

        self._sync_operator_state(
            session_path=session_path,
            workflow_path=workflow_path,
            plan_path=plan_path,
            timestamp=timestamp,
        )

    def _artifacts(self) -> BootstrapArtifacts:
        return self._artifacts_for_dir(self.dev_dir)

    def _artifacts_for_dir(self, directory: Path) -> BootstrapArtifacts:
        plan_path = directory / "PLAN.md"
        if not plan_path.exists() and (directory / "TASKS.md").exists():
            plan_path.write_text((directory / "TASKS.md").read_text(encoding="utf-8"), encoding="utf-8")
        return BootstrapArtifacts(
            dashboard=directory / "DASHBOARD.md",
            plan=plan_path,
            session=directory / "session.json",
            workflow_state=directory / "workflow_state.json",
            logs_dir=directory / "logs",
            prompt=(directory / "PROMPT.md") if (directory / "PROMPT.md").exists() else None,
        )

    def _ensure_template_file(
        self,
        path: Path,
        template_name: str,
        values: Mapping[str, str],
    ) -> None:
        if path.exists():
            return
        template = Template(self._template_path(template_name).read_text(encoding="utf-8"))
        path.write_text(template.safe_substitute(values), encoding="utf-8")

    def _write_template_file(
        self,
        path: Path,
        template_name: str,
        values: Mapping[str, str],
    ) -> None:
        template = Template(self._template_path(template_name).read_text(encoding="utf-8"))
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
        plan_path: Path,
        timestamp: str,
    ) -> None:
        parsed_tasks = parse_tasks_document(
            plan_path.read_text(encoding="utf-8"),
            source=self._display_state_path(plan_path),
        )
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
        self._sync_root_index(timestamp=timestamp)

    def _generated_session_id(self, timestamp: str) -> str:
        compact = timestamp.replace("-", "").replace(":", "").replace("+", "-").replace("T", "-")
        return f"{self.config.app_name}-{compact}"

    def _normalize_session_id(self, value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
        if not normalized:
            raise ValueError("session_id must contain at least one safe filename character.")
        return normalized

    def _current_session_id(self, session_path: Path) -> str | None:
        if not session_path.exists():
            return None
        try:
            payload = self._read_json(session_path)
        except json.JSONDecodeError:
            return None
        session_id = payload.get("session_id") or payload.get("active_session_id")
        return str(session_id) if session_id else None

    def _read_active_session_id(self) -> str | None:
        return self._current_session_id(self.base_dev_dir / "session.json")

    def _active_session_repository(self) -> StateRepository:
        session_id = self._read_active_session_id()
        if session_id is None:
            raise RuntimeError("No active session is available.")
        return self.for_session(session_id)

    def _sync_root_index(self, *, timestamp: str | None = None) -> None:
        if self.session_id is None:
            return
        active_session_id = self._read_active_session_id()
        if active_session_id != self.session_id:
            return
        self._write_root_index_for_session(
            session_repository=self,
            timestamp=timestamp or _iso_now(),
        )

    def _write_root_index_for_session(
        self,
        *,
        session_repository: StateRepository,
        timestamp: str,
    ) -> None:
        session_state = session_repository._read_json(session_repository.state_file("session.json"))
        workflow_state = session_repository._read_json(
            session_repository.state_file("workflow_state.json")
        )
        session_id = str(session_state["session_id"])
        state_root = session_repository._state_root_display()
        session_defaults = {
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
                "logs_dir": f"{state_root}/logs",
                "goal": session_state.get("bootstrap", {}).get("goal"),
                "updated_at": session_state.get("updated_at"),
                "active_phase": session_state.get("active_phase"),
                "active_roadmap_phase_ids": session_state.get("active_roadmap_phase_ids", []),
            },
        }
        workflow_defaults = {
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
                "goal": workflow_state.get("bootstrap", {}).get("goal"),
                "updated_at": workflow_state.get("updated_at"),
            },
            "sessions": self.list_sessions(),
        }
        self._ensure_json_file(self.base_dev_dir / "session.json", session_defaults)
        root_session = self._read_json(self.base_dev_dir / "session.json")
        root_session["active_session_id"] = session_id
        root_session["default_session_id"] = session_id
        root_session["selected_at"] = timestamp
        root_session["updated_at"] = timestamp
        root_session["current_session"] = session_defaults["current_session"]
        self._write_json(self.base_dev_dir / "session.json", root_session)

        self._ensure_json_file(self.base_dev_dir / "workflow_state.json", workflow_defaults)
        root_workflow = self._read_json(self.base_dev_dir / "workflow_state.json")
        root_workflow["updated_at"] = timestamp
        root_workflow["active_session_id"] = session_id
        root_workflow["default_session_id"] = session_id
        root_workflow["source_of_truth"] = workflow_defaults["source_of_truth"]
        root_workflow["session_index"] = workflow_defaults["session_index"]
        root_workflow["current_session"] = workflow_defaults["current_session"]
        root_workflow["sessions"] = self.list_sessions()
        self._write_json(self.base_dev_dir / "workflow_state.json", root_workflow)

    def _copy_state_snapshot(self, source_dir: Path, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in (*self.CORE_STATE_FILENAMES, *self.OPTIONAL_STATE_FILENAMES):
            source = source_dir / filename
            target = target_dir / filename
            if source.exists():
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            elif target.exists():
                target.unlink()
        legacy_tasks_path = source_dir / "TASKS.md"
        target_plan_path = target_dir / "PLAN.md"
        if legacy_tasks_path.exists() and not target_plan_path.exists():
            target_plan_path.write_text(legacy_tasks_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _state_root_display(self) -> str:
        return self.dev_dir.relative_to(self.config.repo_root).as_posix()

    def _has_legacy_root_snapshot(self) -> bool:
        return any(
            (self.base_dev_dir / filename).exists()
            for filename in (*self.CORE_STATE_FILENAMES, "TASKS.md")
        )

    def _migrate_legacy_root_snapshot(self, *, timestamp: str | None = None) -> str | None:
        legacy_session_id = self._read_active_session_id()
        if legacy_session_id is not None and (self.sessions_dir / legacy_session_id).exists():
            return legacy_session_id
        if not self._has_legacy_root_snapshot():
            return None

        session_id = legacy_session_id or self._generated_session_id(timestamp or _iso_now())
        target_dir = self.sessions_dir / session_id
        self._copy_state_snapshot(self.base_dev_dir, target_dir)
        legacy_logs_dir = self.base_dev_dir / "logs"
        target_logs_dir = target_dir / "logs"
        if legacy_logs_dir.exists() and not target_logs_dir.exists():
            shutil.copytree(legacy_logs_dir, target_logs_dir)

        session_path = target_dir / "session.json"
        if session_path.exists():
            session_state = self._read_json(session_path)
            session_state["session_id"] = session_id
            session_state.setdefault("state_schema_version", 3)
            self._write_json(session_path, session_state)
        return session_id

    def _read_legacy_root_session_payload(self) -> dict[str, Any] | None:
        session_path = self.base_dev_dir / "session.json"
        if not session_path.exists():
            return None
        payload = self._read_json(session_path)
        if "active_session_id" in payload:
            return None
        if "session_id" not in payload:
            return None
        return payload

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.write_text(
            json.dumps(dict(payload), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def persist_input_prompt(
        self,
        *,
        prompt_text: str,
        source_path: Path | None = None,
    ) -> Path:
        if self.session_id is None:
            return self._active_session_repository().persist_input_prompt(
                prompt_text=prompt_text,
                source_path=source_path,
            )

        prompt_path = self.state_file("PROMPT.md")
        if source_path is not None and source_path.exists():
            shutil.copyfile(source_path, prompt_path)
        else:
            prompt_path.write_text(prompt_text, encoding="utf-8")

        mirror_path = self._global_prompt_mirror_path()
        mirror_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path is not None and source_path.exists():
            shutil.copyfile(source_path, mirror_path)
        else:
            mirror_path.write_text(prompt_text, encoding="utf-8")

        timestamp = _iso_now()
        session_state = self._read_json(self.state_file("session.json"))
        session_state["updated_at"] = timestamp
        session_state.setdefault("bootstrap", {})
        session_state["bootstrap"]["prompt_path"] = self._display_state_path(prompt_path)
        session_state["bootstrap"]["global_prompt_path"] = str(mirror_path)
        self._write_json(self.state_file("session.json"), session_state)

        workflow_state = self._read_json(self.state_file("workflow_state.json"))
        workflow_state["updated_at"] = timestamp
        workflow_state.setdefault("bootstrap", {})
        workflow_state["bootstrap"]["prompt_path"] = self._display_state_path(prompt_path)
        workflow_state["bootstrap"]["global_prompt_path"] = str(mirror_path)
        workflow_state.setdefault("artifacts", {})
        workflow_state["artifacts"]["prompt"] = self._display_state_path(prompt_path)
        self._write_json(self.state_file("workflow_state.json"), workflow_state)
        self._sync_root_index(timestamp=timestamp)
        return prompt_path

    def _ensure_plan_file(self, plan_path: Path) -> None:
        if plan_path.exists():
            return
        legacy_tasks_path = self.state_file("TASKS.md")
        if legacy_tasks_path.exists():
            plan_path.write_text(legacy_tasks_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _operator_plan_path(self) -> Path:
        plan_path = self.state_file("PLAN.md")
        self._ensure_plan_file(plan_path)
        if plan_path.exists():
            return plan_path
        return self.state_file("TASKS.md")

    def _display_state_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.config.repo_root).as_posix()
        except ValueError:
            return str(path)

    def _template_path(self, template_name: str) -> Path:
        candidate = self.templates_dir / template_name
        if candidate.exists():
            return candidate
        if template_name == "plan.md.tmpl":
            fallback = self.templates_dir / "tasks.md.tmpl"
            if fallback.exists():
                return fallback
        raise FileNotFoundError(f"Template file was not found: {candidate}")

    def _global_prompt_mirror_path(self) -> Path:
        session_state = self._read_json(self.state_file("session.json"))
        session_id = str(session_state.get("session_id") or self.session_id)
        return self.config.global_home_dir / "sessions" / session_id / ".dev" / "PROMPT.md"
