from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Sequence


STATE_SCHEMA_VERSION = 7

PHASE_LABELS = {
    "phase_1": "Phase 1. Core Foundation and Repository Bootstrap",
    "phase_2": "Phase 2. `.dev` State Model and Template Generation",
    "phase_3": "Phase 3. Agent CLI Adapter and Single-Run Execution",
    "phase_4": "Phase 4. Supervisor Validation, Continuation Loop, and Resume",
    "phase_5": "Phase 5. CLI Operator Experience and Progress Visibility",
    "phase_6": "Phase 6. Installer, Commands, and Environment Diagnostics",
    "phase_7": "Phase 7. Hardening, Multi-Session, and Productization",
}


@dataclass(frozen=True, slots=True)
class RepoGuidance:
    rule_files: Sequence[str]
    workflow_files: Sequence[str]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "rule_files": list(self.rule_files),
            "workflow_files": list(self.workflow_files),
        }


def _as_posix(path: Path) -> str:
    return path.as_posix()


def discover_repo_guidance(
    repo_root: Path,
    *,
    rule_paths: Sequence[Path] = (),
) -> RepoGuidance:
    if rule_paths:
        rule_files = [
            _as_posix(candidate.relative_to(repo_root))
            if candidate.is_absolute() and repo_root in candidate.parents
            else _as_posix(candidate)
            for candidate in rule_paths
        ]
    else:
        rule_candidates = [
            Path("AGENTS.md"),
            Path("agents/AGENTS.md"),
            Path(".dev/PROJECT.md"),
            Path(".dev/ROADMAP.md"),
        ]
        rule_files = [
            _as_posix(candidate)
            for candidate in rule_candidates
            if (repo_root / candidate).exists()
        ]

    workflows_dir = repo_root / ".github" / "workflows"
    workflow_files: list[str] = []
    if workflows_dir.exists():
        for candidate in sorted(workflows_dir.iterdir()):
            if candidate.is_file() and candidate.suffix in {".yml", ".yaml"}:
                workflow_files.append(_as_posix(candidate.relative_to(repo_root)))

    return RepoGuidance(
        rule_files=tuple(rule_files),
        workflow_files=tuple(workflow_files),
    )


def _bullet_lines(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _task_lines(items: Sequence[str]) -> str:
    return "\n".join(f"- [ ] {item}" for item in items)


def _active_roadmap_focus(roadmap_phase_ids: Sequence[str]) -> list[str]:
    if not roadmap_phase_ids:
        return [PHASE_LABELS["phase_2"]]
    return [PHASE_LABELS.get(phase_id, phase_id) for phase_id in roadmap_phase_ids]


def _state_path(state_root: str, filename: str) -> str:
    return f"{state_root}/{filename}" if state_root else filename


def _guidance_note_lines(repo_guidance: RepoGuidance | None) -> list[str]:
    notes: list[str] = []
    if repo_guidance is None:
        return notes
    if repo_guidance.rule_files:
        notes.append(
            "Repository rules to follow: " + ", ".join(repo_guidance.rule_files)
        )
    if repo_guidance.workflow_files:
        notes.append(
            "Relevant repository workflows: " + ", ".join(repo_guidance.workflow_files)
        )
    return notes


def _guidance_review_task(repo_guidance: RepoGuidance | None) -> str:
    if repo_guidance is None or (
        not repo_guidance.rule_files and not repo_guidance.workflow_files
    ):
        return "Review the repository guidance that applies to the current goal"

    targets = [*repo_guidance.rule_files, *repo_guidance.workflow_files]
    return "Review repository guidance from " + ", ".join(targets)


def summarize_prompt_goal(prompt_text: str | None, *, fallback: str) -> str:
    if prompt_text is None:
        return fallback

    for raw_line in prompt_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "```":
            continue
        normalized = re.sub(r"^#+\s*", "", stripped)
        normalized = re.sub(r"^[-*+]\s+", "", normalized)
        normalized = re.sub(r"^\d+[.)]\s+", "", normalized)
        normalized = " ".join(normalized.split())
        if not normalized:
            continue
        if len(normalized) > 120:
            return normalized[:117].rstrip() + "..."
        return normalized
    return fallback


def normalize_prompt_text(prompt_text: str | None) -> str:
    if prompt_text is None:
        return ""
    return "\n".join(line.rstrip() for line in prompt_text.strip().splitlines()).strip()


def prompt_fingerprint(prompt_text: str | None) -> str | None:
    normalized = normalize_prompt_text(prompt_text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _prompt_requirement_lines(prompt_text: str | None) -> list[str]:
    if prompt_text is None:
        return []

    items: list[str] = []
    seen: set[str] = set()
    for raw_line in prompt_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "```":
            continue

        normalized = re.sub(r"^#+\s*", "", stripped)
        normalized = re.sub(r"^[-*+]\s+", "", normalized)
        normalized = re.sub(r"^\d+[.)]\s+", "", normalized)
        normalized = " ".join(normalized.split())
        normalized = normalized.strip(" -")
        if len(normalized) < 8:
            continue

        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(normalized.rstrip("."))
        if len(items) == 4:
            break
    return items


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
class PlanTemplateContext:
    task_items: Sequence[str]
    resume_checkpoint: str

    def render_values(self) -> dict[str, str]:
        return {
            "task_items": _task_lines(self.task_items),
            "resume_checkpoint": self.resume_checkpoint,
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
    prompt_text: str | None = None,
    repo_guidance: RepoGuidance | None = None,
) -> DashboardTemplateContext:
    roadmap_focus = _active_roadmap_focus(roadmap_phase_ids)
    guidance_notes = _guidance_note_lines(repo_guidance)
    prompt_summary = summarize_prompt_goal(prompt_text, fallback=goal)
    return DashboardTemplateContext(
        goal=goal,
        active_delivery_slice=(
            f"{roadmap_focus[0]} prompt-driven setup for {prompt_summary}"
            if roadmap_focus
            else f"Prompt-driven setup for {prompt_summary}"
        ),
        active_phase="plan",
        last_completed_phase="none",
        supervisor_verdict="approved",
        escalation_status="approved",
        resume_point="Return to Plan and resume from the first unchecked PLAN item if setup is interrupted",
        next_action=[
            f"Review the prompt-derived goal and success criteria for {goal}.",
            _guidance_review_task(repo_guidance),
            "Generate DASHBOARD.md and PLAN.md from the active prompt before implementation continues.",
        ],
        notes=[
            "This file should show the actual progress of the active scope.",
            "workflow_state.json remains machine truth.",
            "PLAN.md should list prompt-derived development items in phase order.",
            *guidance_notes,
        ],
        active_roadmap_focus=roadmap_focus,
        risks_and_watchpoints=[
            "Do not overwrite existing operator-authored Markdown.",
            "Keep JSON merges additive so interrupted runs stay resumable.",
            "Keep session-scoped state isolated when multiple workflows run in parallel.",
        ],
    )


def default_plan_context(
    *,
    goal: str,
    prompt_text: str | None = None,
    repo_guidance: RepoGuidance | None = None,
) -> PlanTemplateContext:
    prompt_requirements = _prompt_requirement_lines(prompt_text)
    if prompt_requirements:
        task_items = [
            f"Phase {index}. {item}"
            for index, item in enumerate(prompt_requirements, start=1)
        ]
    else:
        task_items = [
            f"Phase 1. Confirm the goal and success criteria for {goal}",
            f"Phase 2. {_guidance_review_task(repo_guidance)}",
            f"Phase 3. Plan the smallest resumable slice for {goal}",
        ]

    if not any(
        any(keyword in item.casefold() for keyword in ("validate", "test", "review", "sync"))
        for item in task_items
    ):
        task_items.append(
            f"Phase {len(task_items) + 1}. Validate the slice and keep `.dev` state synchronized before completion"
        )

    return PlanTemplateContext(
        task_items=task_items,
        resume_checkpoint=(
            "Resume from the first unchecked PLAN item unless validation requires "
            "a return to earlier planning work."
        ),
    )


def default_session_state(
    *,
    timestamp: str,
    app_name: str,
    roadmap_phase_ids: Sequence[str],
    goal: str,
    state_root: str,
    prompt_text: str | None = None,
    repo_guidance: RepoGuidance | None = None,
    session_id: str | None = None,
    run_type: str = "bootstrap",
) -> dict[str, Any]:
    prompt_summary = summarize_prompt_goal(prompt_text, fallback=goal)
    return {
        "session_id": session_id or f"{app_name}-bootstrap",
        "created_at": timestamp,
        "updated_at": timestamp,
        "run_type": run_type,
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
        "bootstrap": {
            "goal": goal,
            "captured_at": timestamp,
            "state_root": state_root,
            "prompt_summary": prompt_summary,
            "prompt_fingerprint": prompt_fingerprint(prompt_text),
            "repo_guidance": (
                repo_guidance.to_dict()
                if repo_guidance is not None
                else {"rule_files": [], "workflow_files": []}
            ),
        },
        "task_sync": OperatorTaskSyncState(
            source=_state_path(state_root, "TASKS.md"),
            resume_checkpoint=None,
            items=(),
        ).to_dict(synced_at=timestamp),
        "next_action": "Review the generated workflow files and continue planning.",
        "notes": [
            "Resume from planning unless supervisor evidence requires an earlier phase.",
            "Interpret a retry limit of -1 as infinite repetition once loop support exists.",
        ],
        "loop": {
            "status": "idle",
        },
        "supervisor_report": {
            "path": _state_path(state_root, "supervisor_report.md"),
            "status": "not_run",
        },
        "latest_continuation_prompt": None,
    }


def default_intake_state(prompt_text: str | None) -> dict[str, Any]:
    """Return the default ``intake`` block for workflow state.

    Performs request classification when *prompt_text* is provided; otherwise
    falls back to ``direct_response`` with a note that no prompt was given.
    """
    from dormammu.intake import classify_request  # local import avoids circulars

    if prompt_text:
        classification = classify_request(prompt_text)
        return classification.to_dict()
    return {
        "request_class": "direct_response",
        "confidence": 0.5,
        "rationale": "No prompt provided at bootstrap; defaulting to direct_response.",
        "has_interface_risk": False,
        "requires_test_strategy": False,
    }


def default_workflow_policy_state(request_class: str) -> dict[str, Any]:
    """Return the ``workflow_policy`` block for workflow state.

    Resolves which pipeline phases are required vs. eligible to skip based on
    the intake request class.  The result is stored in workflow_state.json so
    that downstream stages (planner, supervisor) can branch without re-deriving
    the policy.
    """
    from dormammu.workflow_policy import (  # local import avoids circulars
        default_workflow_policy_state as _policy_state,
    )

    valid = ("direct_response", "light_edit", "full_workflow")
    if request_class not in valid:
        request_class = "direct_response"
    return _policy_state(request_class)  # type: ignore[arg-type]


def default_workflow_state(
    *,
    timestamp: str,
    roadmap_phase_ids: Sequence[str],
    goal: str,
    state_root: str,
    prompt_text: str | None = None,
    repo_guidance: RepoGuidance | None = None,
) -> dict[str, Any]:
    prompt_summary = summarize_prompt_goal(prompt_text, fallback=goal)
    intake_state = default_intake_state(prompt_text)
    source_goal_files = list(
        dict.fromkeys(
            [
                ".dev/PROJECT.md",
                ".dev/ROADMAP.md",
                *(
                    list(repo_guidance.rule_files)
                    if repo_guidance is not None
                    else ["AGENTS.md", "agents/AGENTS.md"]
                ),
            ]
        )
    )
    return {
        "version": 1,
        "state_schema_version": STATE_SCHEMA_VERSION,
        "initialized_at": timestamp,
        "updated_at": timestamp,
        "mode": "supervised",
        "source_of_truth": {
            "goal": source_goal_files,
            "machine_state": _state_path(state_root, "workflow_state.json"),
            "operator_state": [
                _state_path(state_root, "DASHBOARD.md"),
                _state_path(state_root, "PLAN.md"),
                _state_path(state_root, "TASKS.md"),
            ],
        },
        "state_schema": {
            "dashboard_template": "templates/dev/dashboard.md.tmpl",
            "plan_template": "templates/dev/plan.md.tmpl",
            "task_markers": {
                "pending": "[ ]",
                "completed": "[O]",
            },
            "task_sync_source": _state_path(state_root, "TASKS.md"),
        },
        "workflow": {
            "active_phase": "plan",
            "last_completed_phase": "none",
            "allowed_sequence": [
                "plan",
                "design",
                "develop",
                "test_authoring",
                "build_and_deploy",
                "test_and_review",
                "final_verification",
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
                "phase_5",
                "phase_6",
                "phase_7",
            ],
        },
        "supervisor": {
            "skill": "supervising-agent",
            "verdict": "approved",
            "escalation": "approved",
            "reason": "Bootstrap state was initialized successfully.",
        },
        "bootstrap": {
            "goal": goal,
            "captured_at": timestamp,
            "state_root": state_root,
            "prompt_summary": prompt_summary,
            "prompt_fingerprint": prompt_fingerprint(prompt_text),
            "repo_guidance": (
                repo_guidance.to_dict()
                if repo_guidance is not None
                else {"rule_files": [], "workflow_files": []}
            ),
        },
        "session": {
            "path": _state_path(state_root, "session.json"),
            "status": "active",
        },
        "artifacts": {
            "dashboard": _state_path(state_root, "DASHBOARD.md"),
            "plan": _state_path(state_root, "PLAN.md"),
            "tasks": _state_path(state_root, "TASKS.md"),
            "logs_dir": _state_path(state_root, "logs"),
        },
        "operator_sync": {
            "tasks": OperatorTaskSyncState(
                source=_state_path(state_root, "TASKS.md"),
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
            "path": _state_path(state_root, "supervisor_report.md"),
            "status": "not_run",
        },
        "latest_continuation_prompt": None,
        "intake": intake_state,
        "workflow_policy": default_workflow_policy_state(
            intake_state.get("request_class", "direct_response")
        ),
    }
