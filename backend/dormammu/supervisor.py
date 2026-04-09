from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from dormammu.config import AppConfig
from dormammu.state import StateRepository


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _normalize_task_sync(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return {
        "source": payload.get("source"),
        "resume_checkpoint": payload.get("resume_checkpoint"),
        "total_tasks": payload.get("total_tasks"),
        "completed_tasks": payload.get("completed_tasks"),
        "pending_tasks": payload.get("pending_tasks"),
        "all_completed": payload.get("all_completed"),
        "next_pending_task": payload.get("next_pending_task"),
        "items": payload.get("items"),
    }


def _normalize_latest_run(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return {
        "run_id": payload.get("run_id"),
        "prompt_mode": payload.get("prompt_mode"),
        "command": payload.get("command"),
        "exit_code": payload.get("exit_code"),
        "artifacts": payload.get("artifacts"),
    }


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


@dataclass(frozen=True, slots=True)
class SupervisorCheck:
    name: str
    ok: bool
    summary: str
    details: Sequence[str] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "details": list(self.details),
        }


@dataclass(frozen=True, slots=True)
class SupervisorRequest:
    required_paths: Sequence[str] = ()
    require_worktree_changes: bool = False
    expected_roadmap_phase_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_paths": list(self.required_paths),
            "require_worktree_changes": self.require_worktree_changes,
            "expected_roadmap_phase_id": self.expected_roadmap_phase_id,
        }


@dataclass(frozen=True, slots=True)
class SupervisorReport:
    generated_at: str
    verdict: str
    escalation: str
    summary: str
    checks: Sequence[SupervisorCheck]
    latest_run_id: str | None
    changed_files: Sequence[str]
    required_paths: Sequence[str]
    report_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "verdict": self.verdict,
            "escalation": self.escalation,
            "summary": self.summary,
            "checks": [check.to_dict() for check in self.checks],
            "latest_run_id": self.latest_run_id,
            "changed_files": list(self.changed_files),
            "required_paths": list(self.required_paths),
            "report_path": str(self.report_path) if self.report_path else None,
        }

    def with_report_path(self, report_path: Path) -> SupervisorReport:
        return SupervisorReport(
            generated_at=self.generated_at,
            verdict=self.verdict,
            escalation=self.escalation,
            summary=self.summary,
            checks=self.checks,
            latest_run_id=self.latest_run_id,
            changed_files=self.changed_files,
            required_paths=self.required_paths,
            report_path=report_path,
        )

    def to_markdown(self) -> str:
        lines = [
            "# Supervisor Report",
            "",
            f"- Generated at: {self.generated_at}",
            f"- Verdict: `{self.verdict}`",
            f"- Escalation: `{self.escalation}`",
            f"- Summary: {self.summary}",
            f"- Latest run id: {self.latest_run_id or 'none'}",
            "",
            "## Checks",
            "",
        ]
        for check in self.checks:
            marker = "PASS" if check.ok else "FAIL"
            lines.append(f"- [{marker}] {check.name}: {check.summary}")
            for detail in check.details:
                lines.append(f"  - {detail}")

        lines.extend(["", "## Required Paths", ""])
        if self.required_paths:
            for required_path in self.required_paths:
                lines.append(f"- {required_path}")
        else:
            lines.append("- none")

        lines.extend(["", "## Worktree Diff", ""])
        if self.changed_files:
            for changed_file in self.changed_files:
                lines.append(f"- {changed_file}")
        else:
            lines.append("- clean")
        lines.append("")
        return "\n".join(lines)


class Supervisor:
    def __init__(
        self,
        config: AppConfig,
        repository: StateRepository | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or StateRepository(config)

    def validate(self, request: SupervisorRequest) -> SupervisorReport:
        self.repository.sync_operator_state()
        session_state = self.repository.read_session_state()
        workflow_state = self.repository.read_workflow_state()
        checks: list[SupervisorCheck] = []

        state_root = Path(str(session_state.get("bootstrap", {}).get("state_root", ".dev")))
        plan_path = self.config.repo_root / state_root / "PLAN.md"
        legacy_tasks_path = self.config.repo_root / state_root / "TASKS.md"
        dev_paths = [
            self.config.repo_root / state_root / "DASHBOARD.md",
            plan_path if plan_path.exists() or not legacy_tasks_path.exists() else legacy_tasks_path,
            self.config.repo_root / state_root / "session.json",
            self.config.repo_root / state_root / "workflow_state.json",
        ]
        missing_dev_paths = [str(path) for path in dev_paths if not path.exists()]
        checks.append(
            SupervisorCheck(
                name="bootstrap-files",
                ok=not missing_dev_paths,
                summary="Bootstrap .dev files are present." if not missing_dev_paths else "Missing required .dev files.",
                details=missing_dev_paths,
            )
        )

        session_task_sync = session_state.get("task_sync")
        workflow_task_sync = workflow_state.get("operator_sync", {}).get("tasks")
        task_sync_match = _normalize_task_sync(session_task_sync) == _normalize_task_sync(workflow_task_sync)
        checks.append(
            SupervisorCheck(
                name="task-sync",
                ok=task_sync_match,
                summary="Session and workflow task summaries match." if task_sync_match else "Session and workflow task summaries diverged.",
            )
        )

        session_phase = session_state.get("active_phase")
        workflow_phase = workflow_state.get("workflow", {}).get("active_phase")
        phase_match = session_phase == workflow_phase
        checks.append(
            SupervisorCheck(
                name="phase-pointer",
                ok=phase_match,
                summary="Session and workflow active phases match." if phase_match else "Session and workflow active phases differ.",
                details=[f"session={session_phase}", f"workflow={workflow_phase}"],
            )
        )

        roadmap_ok = True
        roadmap_details: list[str] = []
        if request.expected_roadmap_phase_id is not None:
            active_phase_ids = workflow_state.get("roadmap", {}).get("active_phase_ids", [])
            roadmap_ok = request.expected_roadmap_phase_id in active_phase_ids
            if not roadmap_ok:
                roadmap_details.append(
                    f"expected {request.expected_roadmap_phase_id} in active roadmap phases {active_phase_ids}"
                )
        checks.append(
            SupervisorCheck(
                name="roadmap-focus",
                ok=roadmap_ok,
                summary="Expected roadmap phase is active." if roadmap_ok else "Workflow state is focused on a different roadmap phase.",
                details=roadmap_details,
            )
        )

        session_run = session_state.get("latest_run")
        workflow_run = workflow_state.get("latest_run")
        latest_run_match = _normalize_latest_run(session_run) == _normalize_latest_run(workflow_run)
        latest_run_present = session_run is not None and workflow_run is not None
        latest_run_ok = latest_run_present and latest_run_match
        checks.append(
            SupervisorCheck(
                name="latest-run-state",
                ok=latest_run_ok,
                summary="Latest run metadata exists in both state files." if latest_run_ok else "Latest run metadata is missing or mismatched across state files.",
            )
        )

        artifact_ok = False
        artifact_details: list[str] = []
        exit_code_ok = False
        latest_run_id: str | None = None
        if latest_run_ok and isinstance(workflow_run, Mapping):
            latest_run_id = str(workflow_run.get("run_id"))
            artifacts = workflow_run.get("artifacts", {})
            expected_artifacts = {
                "prompt": artifacts.get("prompt"),
                "stdout": artifacts.get("stdout"),
                "stderr": artifacts.get("stderr"),
                "metadata": artifacts.get("metadata"),
            }
            artifact_ok = True
            for artifact_name, artifact_value in expected_artifacts.items():
                if not artifact_value:
                    artifact_ok = False
                    artifact_details.append(f"missing {artifact_name} path in latest_run")
                    continue
                artifact_path = Path(str(artifact_value))
                if not artifact_path.exists():
                    artifact_ok = False
                    artifact_details.append(f"missing artifact file: {artifact_path}")
            metadata_path_value = expected_artifacts.get("metadata")
            if metadata_path_value:
                metadata_path = Path(str(metadata_path_value))
                if metadata_path.exists():
                    metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if metadata_payload.get("run_id") != latest_run_id:
                        artifact_ok = False
                        artifact_details.append(
                            f"metadata run_id {metadata_payload.get('run_id')} did not match {latest_run_id}"
                        )
            exit_code_ok = workflow_run.get("exit_code") == 0
            if not exit_code_ok:
                artifact_details.append(f"latest run exit code was {workflow_run.get('exit_code')}")

        checks.append(
            SupervisorCheck(
                name="latest-run-artifacts",
                ok=artifact_ok and exit_code_ok,
                summary=(
                    "Latest run artifacts exist and the run exited cleanly."
                    if artifact_ok and exit_code_ok
                    else "Latest run artifacts are incomplete or the run failed."
                ),
                details=artifact_details,
            )
        )

        required_paths = [str(_resolve_path(self.config.repo_root, value)) for value in request.required_paths]
        missing_required_paths = [path for path in required_paths if not Path(path).exists()]
        checks.append(
            SupervisorCheck(
                name="required-paths",
                ok=not missing_required_paths,
                summary="All required output paths exist." if not missing_required_paths else "Required output paths are still missing.",
                details=missing_required_paths,
            )
        )

        changed_files, git_ok, git_details = self._collect_worktree_diff()
        diff_ok = git_ok and (bool(changed_files) if request.require_worktree_changes else True)
        if request.require_worktree_changes and git_ok and not changed_files:
            git_details = ["The worktree is clean but changes were required."]
        checks.append(
            SupervisorCheck(
                name="worktree-diff",
                ok=diff_ok,
                summary=(
                    "Collected git worktree diff successfully."
                    if diff_ok
                    else "Unable to confirm the required worktree diff state."
                ),
                details=git_details,
            )
        )

        verdict, escalation, summary = self._resolve_outcome(
            checks=checks,
            latest_run_present=latest_run_present,
            artifact_ok=artifact_ok,
            git_ok=git_ok,
        )
        return SupervisorReport(
            generated_at=_iso_now(),
            verdict=verdict,
            escalation=escalation,
            summary=summary,
            checks=tuple(checks),
            latest_run_id=latest_run_id,
            changed_files=tuple(changed_files),
            required_paths=tuple(required_paths),
        )

    def _collect_worktree_diff(self) -> tuple[list[str], bool, list[str]]:
        completed = subprocess.run(
            ["git", "-C", str(self.config.repo_root), "status", "--short", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            details = [line for line in completed.stderr.splitlines() if line.strip()]
            if not details:
                details = [f"git status exited with code {completed.returncode}"]
            return [], False, details
        changed_files = [line.rstrip() for line in completed.stdout.splitlines() if line.strip()]
        details = [f"{len(changed_files)} changed path(s) detected."] if changed_files else ["Worktree is clean."]
        return changed_files, True, details

    def _resolve_outcome(
        self,
        *,
        checks: Sequence[SupervisorCheck],
        latest_run_present: bool,
        artifact_ok: bool,
        git_ok: bool,
    ) -> tuple[str, str, str]:
        if not checks[0].ok or not latest_run_present or (checks[4].ok is False and artifact_ok is False):
            return (
                "blocked",
                "blocked",
                "Critical .dev state or latest-run artifacts are missing, so safe continuation is blocked.",
            )
        if not git_ok:
            return (
                "manual_review_needed",
                "manual_review_needed",
                "Git diff evidence could not be collected deterministically.",
            )
        failing_checks = [check for check in checks if not check.ok]
        if failing_checks:
            return (
                "rework_required",
                "rework_required",
                failing_checks[0].summary,
            )
        return (
            "approved",
            "approved",
            "All deterministic supervisor checks passed.",
        )
