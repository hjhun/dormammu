from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


STATE_SCHEMA_VERSION = 3

PHASE_LABELS = {
    "phase_1": "Phase 1. Core Foundation and Repository Bootstrap",
    "phase_2": "Phase 2. `.dev` State Model and Template Generation",
    "phase_3": "Phase 3. Agent CLI Adapter and Single-Run Execution",
    "phase_4": "Phase 4. Supervisor Validation, Continuation Loop, and Resume",
    "phase_5": "Phase 5. Local Web UI and Progress Visibility",
    "phase_6": "Phase 6. Installer, Commands, and Environment Diagnostics",
    "phase_7": "Phase 7. Hardening, Multi-Session, and Productization",
}


def _bullet_lines(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _task_lines(items: Sequence[str]) -> str:
    return "\n".join(f"- [ ] {item}" for item in items)


def _active_roadmap_focus(roadmap_phase_ids: Sequence[str]) -> list[str]:
    if not roadmap_phase_ids:
        return [PHASE_LABELS["phase_2"]]
    return [PHASE_LABELS.get(phase_id, phase_id) for phase_id in roadmap_phase_ids]


@dataclass(frozen=True, slots=True)
class DashboardTemplateContext:
    goal: str
    active_delivery_slice: str
    active_phase: str
    last_completed_phase: str
    supervisor_verdict: str
    escalation_status: str
    resume_point: str
    next_action: Sequence[str]
    notes: Sequence[str]
    active_roadmap_focus: Sequence[str]
    risks_and_watchpoints: Sequence[str]

    def render_values(self) -> dict[str, str]:
        return {
            "goal": self.goal,
            "active_delivery_slice": self.active_delivery_slice,
            "active_phase": self.active_phase,
            "last_completed_phase": self.last_completed_phase,
            "supervisor_verdict": self.supervisor_verdict,
            "escalation_status": self.escalation_status,
            "resume_point": self.resume_point,
            "next_action": _bullet_lines(self.next_action),
            "notes": _bullet_lines(self.notes),
            "active_roadmap_focus": _bullet_lines(self.active_roadmap_focus),
            "risks_and_watchpoints": _bullet_lines(self.risks_and_watchpoints),
        }


@dataclass(frozen=True, slots=True)
class TasksTemplateContext:
    task_items: Sequence[str]
    resume_checkpoint: str
    completion_rule: str

    def render_values(self) -> dict[str, str]:
        return {
            "task_items": _task_lines(self.task_items),
            "resume_checkpoint": self.resume_checkpoint,
            "completion_rule": self.completion_rule,
        }


@dataclass(frozen=True, slots=True)
class TaskSyncItem:
    text: str
    completed: bool

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "completed": self.completed}


@dataclass(frozen=True, slots=True)
class OperatorTaskSyncState:
    source: str
    resume_checkpoint: str | None
    items: Sequence[TaskSyncItem]

    @property
    def total_tasks(self) -> int:
        return len(self.items)

    @property
    def completed_tasks(self) -> int:
        return sum(1 for item in self.items if item.completed)

    @property
    def pending_tasks(self) -> int:
        return self.total_tasks - self.completed_tasks

    @property
    def all_completed(self) -> bool:
        return self.total_tasks > 0 and self.pending_tasks == 0

    @property
    def next_pending_task(self) -> str | None:
        for item in self.items:
            if not item.completed:
                return item.text
        return None

    def to_dict(self, *, synced_at: str) -> dict[str, Any]:
        return {
            "source": self.source,
            "resume_checkpoint": self.resume_checkpoint,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "pending_tasks": self.pending_tasks,
            "all_completed": self.all_completed,
            "next_pending_task": self.next_pending_task,
            "items": [item.to_dict() for item in self.items],
            "synced_at": synced_at,
        }


def default_dashboard_context(
    *,
    goal: str,
    roadmap_phase_ids: Sequence[str],
) -> DashboardTemplateContext:
    return DashboardTemplateContext(
        goal=goal,
        active_delivery_slice="ROADMAP Phase 2 `.dev` state model and template generation",
        active_phase="plan",
        last_completed_phase="none",
        supervisor_verdict="approved",
        escalation_status="approved",
        resume_point="Return to Plan if setup is interrupted",
        next_action=[
            "Confirm the active Phase 2 scope for `.dev` state management.",
            "Review the generated `.dev` bootstrap files and task checklist.",
            "Proceed into supervised planning and design for the current slice.",
        ],
        notes=[
            "This file is the operator-facing dashboard.",
            "workflow_state.json remains machine truth.",
            "TASKS.md checkbox state is synchronized into machine-readable state.",
        ],
        active_roadmap_focus=_active_roadmap_focus(roadmap_phase_ids),
        risks_and_watchpoints=[
            "Do not overwrite existing operator-authored Markdown.",
            "Keep JSON merges additive so interrupted runs stay resumable.",
        ],
    )


def default_tasks_context() -> TasksTemplateContext:
    return TasksTemplateContext(
        task_items=[
            "Confirm the current user goal",
            "Review the generated `.dev` bootstrap files",
            "Start the planning phase",
        ],
        resume_checkpoint=(
            "Resume from the first unchecked task unless validation requires "
            "a return to earlier planning work."
        ),
        completion_rule=(
            "Do not mark a task complete until the implementation, "
            "DASHBOARD.md, and workflow_state.json agree."
        ),
    )


def default_session_state(
    *,
    timestamp: str,
    app_name: str,
    roadmap_phase_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "session_id": f"{app_name}-bootstrap",
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_type": "bootstrap",
        "status": "active",
        "state_schema_version": STATE_SCHEMA_VERSION,
        "active_phase": "plan",
        "active_roadmap_phase_ids": list(roadmap_phase_ids),
        "resume_token": "plan:bootstrap",
        "last_safe_checkpoint": {
            "phase": "plan",
            "timestamp": timestamp,
            "description": "Bootstrap files were initialized.",
        },
        "task_sync": OperatorTaskSyncState(
            source=".dev/TASKS.md",
            resume_checkpoint=None,
            items=(),
        ).to_dict(synced_at=timestamp),
        "next_action": "Review the generated .dev files and continue planning.",
        "notes": [
            "Resume from planning unless supervisor evidence requires an earlier phase.",
            "Interpret a retry limit of -1 as infinite repetition once loop support exists.",
        ],
        "loop": {
            "status": "idle",
        },
        "supervisor_report": {
            "path": ".dev/supervisor_report.md",
            "status": "not_run",
        },
        "latest_continuation_prompt": None,
    }


def default_workflow_state(
    *,
    timestamp: str,
    roadmap_phase_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "version": 1,
        "state_schema_version": STATE_SCHEMA_VERSION,
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
        "state_schema": {
            "dashboard_template": "templates/dev/dashboard.md.tmpl",
            "tasks_template": "templates/dev/tasks.md.tmpl",
            "task_markers": {
                "pending": "[ ]",
                "completed": "[O]",
            },
            "task_sync_source": ".dev/TASKS.md",
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
        "operator_sync": {
            "tasks": OperatorTaskSyncState(
                source=".dev/TASKS.md",
                resume_checkpoint=None,
                items=(),
            ).to_dict(synced_at=timestamp),
        },
        "next_action": "Review the generated bootstrap state and continue planning.",
        "blockers": [],
        "phase_history": [],
        "notes": [
            "Treat this file as machine truth and keep Markdown synchronized.",
            "A failed-work retry limit must be user-configurable, and -1 must mean infinite repetition.",
        ],
        "loop": {
            "status": "idle",
        },
        "supervisor_report": {
            "path": ".dev/supervisor_report.md",
            "status": "not_run",
        },
        "latest_continuation_prompt": None,
    }
