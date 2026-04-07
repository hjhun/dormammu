from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from string import Template
from typing import Any, Mapping, Sequence

from dormammu.config import AppConfig


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


def _bullet_lines(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


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

        self._ensure_template_file(
            dashboard_path,
            "dashboard.md.tmpl",
            {
                "goal": goal or "Bootstrap dormammu in the current repository.",
                "active_delivery_slice": "Bootstrap state initialization",
                "active_phase": "plan",
                "last_completed_phase": "none",
                "supervisor_verdict": "approved",
                "escalation_status": "approved",
                "resume_point": "Return to Plan if setup is interrupted",
                "next_action": _bullet_lines(
                    [
                        "Confirm the active scope for the repository.",
                        "Review the generated .dev bootstrap files.",
                        "Proceed into supervised planning.",
                    ]
                ),
                "notes": _bullet_lines(
                    [
                        "This file is the operator-facing dashboard.",
                        "workflow_state.json remains machine truth.",
                    ]
                ),
            },
        )
        self._ensure_template_file(
            tasks_path,
            "tasks.md.tmpl",
            {
                "task_items": "\n".join(
                    [
                        "- [ ] Confirm the current user goal",
                        "- [ ] Review the generated `.dev` bootstrap files",
                        "- [ ] Start the planning phase",
                    ]
                ),
                "resume_checkpoint": (
                    "Resume from the first unchecked task unless validation "
                    "requires a return to earlier planning work."
                ),
            },
        )

        session_defaults = self._default_session_state(timestamp, roadmap_phase_ids)
        workflow_defaults = self._default_workflow_state(timestamp, roadmap_phase_ids)

        self._ensure_json_file(session_path, session_defaults)
        self._ensure_json_file(workflow_path, workflow_defaults)

        return BootstrapArtifacts(
            dashboard=dashboard_path,
            tasks=tasks_path,
            session=session_path,
            workflow_state=workflow_path,
            logs_dir=self.logs_dir,
        )

    def _default_session_state(
        self,
        timestamp: str,
        roadmap_phase_ids: Sequence[str],
    ) -> dict[str, Any]:
        return {
            "session_id": f"{self.config.app_name}-bootstrap",
            "created_at": timestamp,
            "updated_at": timestamp,
            "run_type": "bootstrap",
            "status": "active",
            "active_phase": "plan",
            "active_roadmap_phase_ids": list(roadmap_phase_ids),
            "resume_token": "plan:bootstrap",
            "last_safe_checkpoint": {
                "phase": "plan",
                "timestamp": timestamp,
                "description": "Bootstrap files were initialized.",
            },
            "next_action": "Review the generated .dev files and continue planning.",
            "notes": [
                "Resume from planning unless supervisor evidence requires an earlier phase.",
                "Interpret a retry limit of -1 as infinite repetition once loop support exists.",
            ],
        }

    def _default_workflow_state(
        self,
        timestamp: str,
        roadmap_phase_ids: Sequence[str],
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "initialized_at": timestamp,
            "updated_at": timestamp,
            "mode": "supervised",
            "source_of_truth": {
                "goal": [
                    ".dev/PROJECT.md",
                    ".dev/ROADMAP.md",
                    "AGENTS.md",
                ],
                "machine_state": ".dev/workflow_state.json",
                "operator_state": [
                    ".dev/DASHBOARD.md",
                    ".dev/TASKS.md",
                ],
            },
            "workflow": {
                "active_phase": "plan",
                "last_completed_phase": "none",
                "allowed_sequence": [
                    "plan",
                    "design",
                    "develop",
                    "build_and_deploy",
                    "test_and_review",
                    "commit",
                ],
                "resume_from_phase": "plan",
            },
            "roadmap": {
                "active_phase_ids": list(roadmap_phase_ids),
                "priority_order": [
                    "phase_1",
                    "phase_2",
                    "phase_3",
                    "phase_4",
                    "phase_6",
                    "phase_5",
                    "phase_7",
                ],
            },
            "supervisor": {
                "skill": "supervising-agent-workflows",
                "verdict": "approved",
                "escalation": "approved",
                "reason": "Bootstrap state was initialized successfully.",
            },
            "session": {
                "path": ".dev/session.json",
                "status": "active",
            },
            "artifacts": {
                "dashboard": ".dev/DASHBOARD.md",
                "tasks": ".dev/TASKS.md",
                "logs_dir": ".dev/logs",
            },
            "next_action": "Review the generated bootstrap state and continue planning.",
            "blockers": [],
            "phase_history": [],
            "notes": [
                "Treat this file as machine truth and keep Markdown synchronized.",
                "A failed-work retry limit must be user-configurable, and -1 must mean infinite repetition.",
            ],
        }

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
            current = json.loads(path.read_text(encoding="utf-8"))
            merged = _deep_merge(defaults, current)
        else:
            merged = defaults
        text = json.dumps(merged, indent=2, ensure_ascii=True) + "\n"
        path.write_text(text, encoding="utf-8")
