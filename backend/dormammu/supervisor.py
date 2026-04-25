from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping, Sequence

from dormammu._utils import iso_now as _iso_now
from dormammu.config import AppConfig
from dormammu.results import (
    ResultStatus,
    StageResult,
    latest_stage_results,
    stage_result_is_failure,
    stage_results_have_clean_terminal_evidence,
)
from dormammu.state import StateRepository


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


def _normalize_execution_run(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return {
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "attempts_completed": payload.get("attempts_completed"),
        "retries_used": payload.get("retries_used"),
        "supervisor_verdict": payload.get("supervisor_verdict"),
        "outcome": payload.get("outcome"),
    }


def _execution_latest_run_status(state: Mapping[str, Any]) -> str | None:
    execution = state.get("execution")
    if not isinstance(execution, Mapping):
        return None
    latest_run = execution.get("latest_run")
    if not isinstance(latest_run, Mapping):
        return None
    status = latest_run.get("status")
    return str(status) if status is not None else None


def _execution_latest_run_references(
    state: Mapping[str, Any],
    latest_run_id: str | None,
) -> bool:
    if latest_run_id is None:
        return False
    execution = state.get("execution")
    if not isinstance(execution, Mapping):
        return False
    latest_run = execution.get("latest_run")
    if not isinstance(latest_run, Mapping):
        return False
    candidates = {
        latest_run.get("run_id"),
        latest_run.get("execution_run_id"),
        latest_run.get("latest_run_id"),
    }
    return latest_run_id in {str(item) for item in candidates if item is not None}


def _execution_stage_result_payloads(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    execution = state.get("execution")
    if not isinstance(execution, Mapping):
        return ()
    latest_run = execution.get("latest_run")
    if isinstance(latest_run, Mapping):
        raw_stage_results = latest_run.get("stage_results")
        if isinstance(raw_stage_results, list):
            return tuple(item for item in raw_stage_results if isinstance(item, Mapping))
    stage_results = execution.get("stage_results")
    if isinstance(stage_results, Mapping):
        return tuple(item for item in stage_results.values() if isinstance(item, Mapping))
    return ()


def _stage_result_from_payload(payload: Mapping[str, Any]) -> StageResult | None:
    role = payload.get("role") or payload.get("stage_name") or "stage"
    if not isinstance(role, str) or not role.strip():
        role = "stage"
    stage_name = payload.get("stage_name")
    try:
        return StageResult(
            role=role,
            stage_name=(
                stage_name
                if isinstance(stage_name, str) and stage_name.strip()
                else None
            ),
            status=payload.get("status") or ResultStatus.COMPLETED,
            verdict=payload.get("verdict"),
            summary=payload.get("summary") if isinstance(payload.get("summary"), str) else None,
        )
    except (TypeError, ValueError):
        return None


def _execution_stage_results(state: Mapping[str, Any]) -> tuple[StageResult, ...]:
    return tuple(
        stage
        for payload in _execution_stage_result_payloads(state)
        if (stage := _stage_result_from_payload(payload)) is not None
    )


def _normalize_stage_results_for_compare(
    stage_results: Sequence[StageResult],
) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    for stage in latest_stage_results(stage_results):
        normalized.append(
            {
                "role": stage.role,
                "stage_name": stage.stage_name,
                "status": stage.status.value if stage.status is not None else None,
                "verdict": stage.verdict.value if stage.verdict is not None else None,
                "summary": stage.summary,
            }
        )
    return tuple(normalized)


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


_ACTION_PROMPT_PATTERNS = (
    r"\bimplement\b",
    r"\bfix\b",
    r"\badd\b",
    r"\bupdate\b",
    r"\bchange\b",
    r"\bmodify\b",
    r"\bedit\b",
    r"\bwrite\b",
    r"\bcreate\b",
    r"\bbuild\b",
    r"\brefactor\b",
    r"\brepair\b",
    r"\bimprove\b",
    r"\bremove\b",
    r"\bdelete\b",
    r"\brename\b",
    r"\bwire\b",
    r"\bpatch\b",
)

_QUESTION_LINE_PATTERNS = (
    r"\?$",
    r"\bwhich\b.{0,80}\?$",
    r"\bwhat\b.{0,80}\?$",
    r"\bwhere\b.{0,80}\?$",
    r"\bshould i\b",
    r"\bdo you want\b",
    r"\bcan you\b",
    r"\bplease provide\b",
    r"\bneed (?:more|additional) (?:context|details|information)\b",
    r"\bI need\b.{0,80}\?$",
)

_WORKFLOW_STATUS_LINE_RE = re.compile(
    r"^(?:[-*]\s*)?Status\s*:\s*(?P<status>[A-Za-z_ -]+)\s*$",
    re.IGNORECASE,
)
_WORKFLOW_STAGE_HEADING_RE = re.compile(r"^#{2,6}\s+(?P<title>.+?)\s*$")
_WORKFLOW_DONE_STATUSES = frozenset({"complete", "completed", "done", "passed", "approved"})
_WORKFLOW_PENDING_STATUSES = frozenset(
    {
        "active",
        "blocked",
        "deferred",
        "failed",
        "in progress",
        "in_progress",
        "manual review needed",
        "manual_review_needed",
        "needs work",
        "needs_work",
        "pending",
        "rework",
        "rework required",
        "rework_required",
        "started",
    }
)


def _load_artifact_text(path_value: Any) -> str:
    if not path_value:
        return ""
    path = Path(str(path_value))
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _normalize_text_for_match(value: str) -> str:
    return " ".join(value.split()).strip()


def _extract_task_prompt_text(prompt_text: str) -> str:
    """Prefer the user/task section of a wrapped prompt over injected guidance."""
    markers = (
        "Task prompt:",
        "Original prompt:",
    )
    for marker in markers:
        if marker in prompt_text:
            return prompt_text.split(marker, 1)[1].strip()
    return prompt_text


def _prompt_requires_progress(prompt_text: str, next_task: str | None) -> bool:
    haystacks = [prompt_text]
    if next_task:
        haystacks.append(next_task)
    for item in haystacks:
        normalized = _normalize_text_for_match(item)
        if not normalized:
            continue
        for pattern in _ACTION_PROMPT_PATTERNS:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return True
    return False


def _find_question_lines(*texts: str) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for raw_line in text.splitlines():
            normalized = _normalize_text_for_match(raw_line)
            if len(normalized) < 6:
                continue
            if normalized in seen:
                continue
            if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in _QUESTION_LINE_PATTERNS):
                matches.append(normalized)
                seen.add(normalized)
    return matches


def _prompt_requests_commit(prompt_text: str) -> bool:
    normalized = _normalize_text_for_match(prompt_text)
    if not normalized:
        return False
    commit_patterns = (
        r"\bcommit\b",
        r"\bstage\b.{0,40}\bcommit\b",
        r"\bprepare\b.{0,40}\bcommit\b",
        r"\bmake\b.{0,40}\bcommit\b",
        r"\bcreate\b.{0,40}\bcommit\b",
        r"\bpush\b",
        r"\bopen\b.{0,40}\bpr\b",
        r"\bpull request\b",
        r"\bmerge\b",
        r"\bcheck in\b",
        r"\bsubmit\b",
        r"\bcommit preparation\b",
        r"\bcommit prep\b",
        r"\bPR\b",
    )
    return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in commit_patterns)


def _parse_workflow_phase_statuses(text: str) -> tuple[list[str], list[str]]:
    pending: list[str] = []
    done: list[str] = []
    status_pending: list[str] = []
    status_done: list[str] = []
    current_stage: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = _WORKFLOW_STAGE_HEADING_RE.match(line)
        if heading:
            current_stage = heading.group("title").strip()
            continue

        status_match = _WORKFLOW_STATUS_LINE_RE.match(line)
        if status_match:
            raw_status = status_match.group("status").strip().casefold()
            normalized_status = raw_status.replace("-", " ").replace("_", " ")
            stage_label = current_stage or "workflow stage"
            if raw_status in _WORKFLOW_DONE_STATUSES or normalized_status in _WORKFLOW_DONE_STATUSES:
                status_done.append(stage_label)
            elif raw_status in _WORKFLOW_PENDING_STATUSES or normalized_status in _WORKFLOW_PENDING_STATUSES:
                status_pending.append(f"{stage_label} ({raw_status})")
            continue

        if line.startswith(("- ", "* ")):
            line = line[2:].lstrip()
        if line.startswith("[ ] "):
            pending.append(line[4:].strip())
        elif line.startswith("[O] ") or line.startswith("[X] ") or line.startswith("[x] "):
            done.append(line[4:].strip())
    if not pending and not done:
        return status_pending, status_done
    return pending, done


def _is_meaningful_path(path: str) -> bool:
    """Return True when a file path represents a meaningful code change.

    Filters out dormammu's own state files and logs so that supervisor checks
    based on worktree diffs are not confused by bookkeeping writes.
    """
    return (
        bool(path)
        and path != "DORMAMMU.log"
        and not path.startswith(".dev/")
        and not path.endswith("supervisor_report.md")
        and not path.endswith("continuation_prompt.txt")
    )


def _meaningful_committed_files(file_paths: Sequence[str]) -> list[str]:
    """Filter bare paths emitted by ``git log --name-only`` (no status prefix)."""
    return [entry.strip() for entry in file_paths if _is_meaningful_path(entry.strip())]


def _meaningful_changed_files(changed_files: Sequence[str]) -> list[str]:
    """Filter git-status lines (with 3-char XY prefix) to meaningful paths."""
    meaningful: list[str] = []
    for entry in changed_files:
        candidate = entry[3:].strip() if len(entry) > 3 else entry.strip()
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1].strip()
        if _is_meaningful_path(candidate):
            meaningful.append(candidate)
    return meaningful


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
    recommended_next_phase: str | None = None
    report_path: Path | None = None
    decision_basis: Mapping[str, Any] | None = None

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
            "recommended_next_phase": self.recommended_next_phase,
            "report_path": str(self.report_path) if self.report_path else None,
            "decision_basis": dict(self.decision_basis or {}),
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
            recommended_next_phase=self.recommended_next_phase,
            report_path=report_path,
            decision_basis=self.decision_basis,
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
            f"- Recommended next phase: {self.recommended_next_phase or 'none'}",
            f"- Decision source: `{(self.decision_basis or {}).get('decision_source', 'unknown')}`",
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
    _WORKTREE_DIFF_CACHE_TTL_SECONDS: float = 5.0

    def __init__(
        self,
        config: AppConfig,
        repository: StateRepository | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or StateRepository(config)
        self._worktree_diff_cache: tuple[list[str], bool, list[str]] | None = None
        self._worktree_diff_cache_time: float = 0.0

    @staticmethod
    def _classify_workflows_completion(
        workflows_path: Path,
    ) -> tuple[bool, bool]:
        """Classify whether WORKFLOWS.md is fully complete or only commit-pending.

        Returns ``(all_complete, pending_commit_only)``.
        """
        if not workflows_path.exists():
            return False, False
        text = workflows_path.read_text(encoding="utf-8")
        pending, done = _parse_workflow_phase_statuses(text)
        if not pending:
            return len(done) > 0, False
        if not done:
            return False, False
        normalized_pending = [entry.casefold() for entry in pending]
        return False, all("commit" in entry for entry in normalized_pending)

    def validate(self, request: SupervisorRequest) -> SupervisorReport:
        self.repository.sync_operator_state()
        session_state = self.repository.read_session_state()
        workflow_state = self.repository.read_workflow_state()
        checks: list[SupervisorCheck] = []

        state_root = Path(str(session_state.get("bootstrap", {}).get("state_root", ".dev")))
        state_dir = self._resolve_state_dir(state_root)
        plan_path = state_dir / "PLAN.md"
        tasks_path = state_dir / "TASKS.md"
        # WORKFLOWS.md is an operator-facing process map mirrored at the repo's
        # .dev/ root.  Prefer the root mirror so that the check reflects what the
        # operator sees and edits, falling back to the session-scoped copy when
        # the mirror is absent (e.g. fresh session that hasn't synced yet).
        workflows_root_mirror = self.config.base_dev_dir / "WORKFLOWS.md"
        workflows_session_path = state_dir / "WORKFLOWS.md"
        workflows_path = (
            workflows_root_mirror
            if workflows_root_mirror.exists()
            else workflows_session_path
        )
        bootstrap = workflow_state.get("bootstrap", {})
        commit_prompt_candidates: list[str] = []
        if isinstance(bootstrap, Mapping):
            prompt_summary = bootstrap.get("prompt_summary")
            if isinstance(prompt_summary, str) and prompt_summary.strip():
                commit_prompt_candidates.append(prompt_summary)
            goal_text = bootstrap.get("goal")
            if isinstance(goal_text, str) and goal_text.strip():
                commit_prompt_candidates.append(goal_text)
            prompt_artifact_text = _load_artifact_text(bootstrap.get("prompt_path"))
            if not prompt_artifact_text:
                prompt_artifact_text = _load_artifact_text(bootstrap.get("global_prompt_path"))
            if prompt_artifact_text:
                commit_prompt_candidates.append(_extract_task_prompt_text(prompt_artifact_text))
        prompt_requests_commit = any(
            _prompt_requests_commit(candidate)
            for candidate in commit_prompt_candidates
            if candidate.strip()
        )
        current_phase = workflow_state.get("workflow", {}).get("active_phase")
        allow_commit_pending = current_phase == "commit" and not prompt_requests_commit
        workflows_fully_complete, workflows_pending_commit_only = self._classify_workflows_completion(
            workflows_path
        )
        workflows_all_complete = workflows_fully_complete or (
            allow_commit_pending and workflows_pending_commit_only
        )
        dev_paths = [
            state_dir / "DASHBOARD.md",
            plan_path,
            tasks_path,
            state_dir / "session.json",
            state_dir / "workflow_state.json",
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

        tasks_complete_ok = True
        task_completion_details: list[str] = []
        if isinstance(session_task_sync, Mapping):
            total_tasks = int(session_task_sync.get("total_tasks", 0) or 0)
            completed_tasks = int(session_task_sync.get("completed_tasks", 0) or 0)
            next_pending_task = session_task_sync.get("next_pending_task")
            tasks_complete_ok = total_tasks == 0 or bool(session_task_sync.get("all_completed"))
            if not tasks_complete_ok:
                task_completion_details.append(
                    f"completed {completed_tasks} of {total_tasks} prompt-derived task queue item(s)"
                )
                if isinstance(next_pending_task, str) and next_pending_task.strip():
                    task_completion_details.append(f"next pending task: {next_pending_task}")
        if (
            not workflows_all_complete
            and workflows_pending_commit_only
            and tasks_complete_ok
            and not prompt_requests_commit
        ):
            workflows_all_complete = True
        checks.append(
            SupervisorCheck(
                name="plan-completion",
                ok=tasks_complete_ok,
                summary=(
                    "All prompt-derived task queue items are complete."
                    if tasks_complete_ok
                    else "Prompt-derived task queue items are still incomplete."
                ),
                details=task_completion_details,
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

        session_execution_run = None
        workflow_execution_run = None
        if isinstance(session_state.get("execution"), Mapping):
            session_execution_run = session_state["execution"].get("latest_run")
        if isinstance(workflow_state.get("execution"), Mapping):
            workflow_execution_run = workflow_state["execution"].get("latest_run")
        execution_run_present = (
            isinstance(session_execution_run, Mapping)
            and isinstance(workflow_execution_run, Mapping)
        )
        execution_run_ok = True
        execution_run_details: list[str] = []
        if execution_run_present:
            execution_run_ok = _normalize_execution_run(session_execution_run) == _normalize_execution_run(
                workflow_execution_run
            )
            if not execution_run_ok:
                execution_run_details = [
                    f"session.execution.latest_run={_normalize_execution_run(session_execution_run)}",
                    f"workflow.execution.latest_run={_normalize_execution_run(workflow_execution_run)}",
                ]
        checks.append(
            SupervisorCheck(
                name="execution-state",
                ok=execution_run_ok,
                summary=(
                    "Explicit execution facts are aligned across session and workflow state."
                    if execution_run_present and execution_run_ok
                    else (
                        "Explicit execution facts are not recorded for this run yet."
                        if not execution_run_present
                        else "Explicit execution facts diverged across session and workflow state."
                    )
                ),
                details=execution_run_details,
            )
        )

        latest_run_id: str | None = None
        if isinstance(workflow_run, Mapping):
            raw_latest_run_id = workflow_run.get("run_id")
            latest_run_id = str(raw_latest_run_id) if raw_latest_run_id is not None else None
        session_structured_stages = _execution_stage_results(session_state)
        workflow_structured_stages = _execution_stage_results(workflow_state)
        raw_structured_stage_evidence_present = bool(
            session_structured_stages or workflow_structured_stages
        )
        structured_stage_evidence_current = (
            raw_structured_stage_evidence_present
            and _execution_latest_run_references(session_state, latest_run_id)
            and _execution_latest_run_references(workflow_state, latest_run_id)
        )
        structured_stage_evidence_present = (
            raw_structured_stage_evidence_present and structured_stage_evidence_current
        )
        structured_stage_evidence_match = (
            _normalize_stage_results_for_compare(session_structured_stages)
            == _normalize_stage_results_for_compare(workflow_structured_stages)
        )
        structured_stages = (
            (workflow_structured_stages or session_structured_stages)
            if structured_stage_evidence_current
            else ()
        )
        latest_structured_stages = latest_stage_results(structured_stages)
        structured_stage_evidence_failed = any(
            stage_result_is_failure(stage) for stage in latest_structured_stages
        )
        latest_execution_run_completed = (
            _execution_latest_run_status(session_state) == ResultStatus.COMPLETED.value
            and _execution_latest_run_status(workflow_state) == ResultStatus.COMPLETED.value
        )
        structured_stage_evidence_clean = (
            structured_stage_evidence_present
            and structured_stage_evidence_match
            and latest_execution_run_completed
            and stage_results_have_clean_terminal_evidence(structured_stages)
        )
        structured_stage_evidence_ok = (
            not structured_stage_evidence_present or structured_stage_evidence_clean
        )
        structured_stage_details: list[str] = []
        if structured_stage_evidence_present:
            structured_stage_details.append(
                "latest stages: "
                + ", ".join(
                    f"{stage.key}={stage.status.value if stage.status else 'unknown'}"
                    f"/{stage.verdict.value if stage.verdict else 'n/a'}"
                    for stage in latest_structured_stages
                )
            )
            if not structured_stage_evidence_match:
                structured_stage_details.append(
                    "Session and workflow stage result projections differ."
                )
            if not latest_execution_run_completed:
                structured_stage_details.append(
                    "Explicit latest execution run is not completed in both state files."
                )
        elif raw_structured_stage_evidence_present:
            structured_stage_details.append(
                "Explicit StageResult projection belongs to an earlier run; using fallback evidence."
            )
        else:
            structured_stage_details.append(
                "No explicit StageResult projection exists; falling back to legacy run artifacts and operator state."
            )
        checks.append(
            SupervisorCheck(
                name="structured-stage-evidence",
                ok=structured_stage_evidence_ok,
                summary=(
                    "Explicit StageResult evidence proves a clean terminal run."
                    if structured_stage_evidence_clean
                    else (
                        "Explicit StageResult evidence is negative or incomplete."
                        if structured_stage_evidence_present
                        else "Explicit StageResult evidence is absent; using fallback evidence."
                    )
                ),
                details=structured_stage_details,
            )
        )

        artifact_ok = False
        artifact_details: list[str] = []
        exit_code_ok = False
        if latest_run_ok and isinstance(workflow_run, Mapping):
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

        prompt_text = ""
        if isinstance(workflow_run, Mapping):
            prompt_text = _load_artifact_text(workflow_run.get("artifacts", {}).get("prompt"))
        if not prompt_text:
            prompt_text = _load_artifact_text(workflow_state.get("bootstrap", {}).get("prompt_path"))
        next_pending_task = None
        if isinstance(session_task_sync, Mapping):
            next_pending_task = session_task_sync.get("next_pending_task")
        prompt_requires_progress = _prompt_requires_progress(
            prompt_text,
            str(next_pending_task) if isinstance(next_pending_task, str) else None,
        )
        stdout_text = ""
        stderr_text = ""
        run_started_at: str | None = None
        run_completed_at: str | None = None
        if isinstance(workflow_run, Mapping):
            artifacts = workflow_run.get("artifacts", {})
            if isinstance(artifacts, Mapping):
                stdout_text = _load_artifact_text(artifacts.get("stdout"))
                stderr_text = _load_artifact_text(artifacts.get("stderr"))
            run_started_at = workflow_run.get("started_at")
            run_completed_at = workflow_run.get("completed_at")
        question_lines = _find_question_lines(stdout_text, stderr_text)
        committed_files = (
            self._collect_committed_files_since(run_started_at, run_completed_at)
            if run_started_at
            else []
        )
        progress_evidence = (
            bool(_meaningful_changed_files(changed_files))
            or bool(_meaningful_committed_files(committed_files))
            or (bool(required_paths) and not missing_required_paths)
        )
        prompt_alignment_details = [
            (
                "Prompt appears to require repository or deliverable progress."
                if prompt_requires_progress
                else "Prompt appears compatible with a read-only or reporting-only run."
            ),
            (
                "Meaningful progress evidence detected."
                if progress_evidence
                else "No meaningful progress evidence detected beyond runtime artifacts."
            ),
        ]
        if question_lines:
            prompt_alignment_details.extend(
                f"Latest run output includes an unresolved question: {line}"
                for line in question_lines[:3]
            )
        prompt_alignment_ok = (not prompt_requires_progress) or progress_evidence
        prompt_alignment_summary = "Latest run outcome matches the prompt's expected completion shape."
        if prompt_requires_progress and not progress_evidence:
            prompt_alignment_summary = (
                "Prompt appears to require implementation progress, but the latest run did not produce "
                "meaningful completion evidence."
            )
            if question_lines:
                prompt_alignment_summary = (
                    "Prompt appears to require implementation progress, but the latest run ended with a "
                    "clarifying question before producing meaningful completion evidence."
                )
        checks.append(
            SupervisorCheck(
                name="prompt-outcome-alignment",
                ok=prompt_alignment_ok,
                summary=prompt_alignment_summary,
                details=prompt_alignment_details,
            )
        )

        # WORKFLOWS.md completion check — an independent signal derived directly
        # from the operator-facing process map.  When all phases are marked [O]
        # this acts as a strong completion signal even if task-sync state has
        # not yet been flushed into session.json.
        checks.append(
            SupervisorCheck(
                name="workflows-completion",
                ok=workflows_all_complete,
                summary=(
                    "WORKFLOWS.md phases are all marked complete."
                    if workflows_fully_complete
                    else "WORKFLOWS.md is complete enough for approval with only Commit pending."
                    if workflows_all_complete
                    else "WORKFLOWS.md has pending [ ] phase items or is absent."
                ),
                details=(
                    [
                        str(workflows_path),
                        (
                            "Pending commit is allowed only for manual runs that have already "
                            "advanced to the commit phase without an explicit commit request."
                        ),
                    ]
                    if not workflows_all_complete
                    else []
                ),
            )
        )

        final_verification_details: list[str] = []
        if (
            not structured_stage_evidence_clean
            and not tasks_complete_ok
            and not workflows_all_complete
        ):
            # Accept WORKFLOWS.md as an alternative completion signal when the
            # task-sync counters have not yet been updated.
            final_verification_details.append("Prompt-derived PLAN work is not complete yet.")
        if not latest_run_ok:
            final_verification_details.append("Latest run metadata is missing or mismatched.")
        if not (artifact_ok and exit_code_ok):
            final_verification_details.append("Latest run artifacts or exit status do not prove a clean run.")
        if missing_required_paths:
            final_verification_details.append("Required output paths are still missing.")
        # Only require prompt-outcome-alignment when the plan/workflow is not yet
        # complete.  Once all checklist items are done, trust the checklist over
        # this heuristic to prevent false rework loops caused by .dev/-only changes.
        plan_or_workflows_done = tasks_complete_ok or workflows_all_complete
        if (
            not structured_stage_evidence_clean
            and not prompt_alignment_ok
            and not plan_or_workflows_done
        ):
            final_verification_details.append("Prompt outcome did not match the expected completion shape.")
        final_verification_ok = not final_verification_details
        checks.append(
            SupervisorCheck(
                name="final-operation-verification",
                ok=final_verification_ok,
                summary=(
                    "Final operation verification passed."
                    if final_verification_ok
                    else "Final operation verification failed and the implementation should be revisited."
                ),
                details=(
                    final_verification_details
                    if final_verification_details
                    else ["Latest run evidence, required outputs, and prompt outcome all passed the final gate."]
                ),
            )
        )

        verdict, escalation, summary, decision_source = self._resolve_outcome(
            checks=checks,
            latest_run_present=latest_run_present,
            artifact_ok=artifact_ok,
            git_ok=git_ok,
            structured_stage_evidence_present=structured_stage_evidence_present,
            structured_stage_evidence_clean=structured_stage_evidence_clean,
            structured_stage_evidence_failed=structured_stage_evidence_failed,
            workflows_all_complete=workflows_all_complete,
            tasks_complete_ok=tasks_complete_ok,
            has_unresolved_questions=bool(question_lines),
            prompt_requests_commit=prompt_requests_commit,
        )
        decision_basis = {
            "decision_source": decision_source,
            "primary_evidence": (
                "structured_stage_results"
                if structured_stage_evidence_present
                else "operator_state_fallback"
            ),
            "structured_stage_evidence": {
                "present": structured_stage_evidence_present,
                "clean": structured_stage_evidence_clean,
                "failed": structured_stage_evidence_failed,
                "session_workflow_match": structured_stage_evidence_match,
                "latest_run_completed": latest_execution_run_completed,
            },
            "fallback_evidence": {
                "tasks_complete": tasks_complete_ok,
                "workflows_complete": workflows_all_complete,
                "latest_run_artifacts_clean": artifact_ok and exit_code_ok,
                "required_paths_ok": not missing_required_paths,
                "prompt_outcome_alignment_ok": prompt_alignment_ok,
                "has_unresolved_questions": bool(question_lines),
            },
        }
        recommended_next_phase = self._recommend_next_phase(checks=checks, verdict=verdict)
        return SupervisorReport(
            generated_at=_iso_now(),
            verdict=verdict,
            escalation=escalation,
            summary=summary,
            checks=tuple(checks),
            latest_run_id=latest_run_id,
            changed_files=tuple(changed_files),
            required_paths=tuple(required_paths),
            recommended_next_phase=recommended_next_phase,
            decision_basis=decision_basis,
        )

    def _collect_committed_files_since(self, started_at: str, completed_at: str | None = None) -> list[str]:
        """Return file paths from git commits made during the agent run window.

        Only commits whose committer date falls between ``started_at`` and
        ``completed_at`` (inclusive) are examined.  This avoids counting repository
        bootstrap commits or earlier work as agent progress.
        """
        try:
            cmd = [
                "git", "-C", str(self.config.repo_root),
                "log", f"--after={started_at}",
                "--name-only", "--format=",
            ]
            if completed_at:
                cmd.append(f"--before={completed_at}")
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        return [line.strip() for line in completed.stdout.splitlines() if line.strip()]

    def _collect_worktree_diff(self) -> tuple[list[str], bool, list[str]]:
        """Return git worktree diff, using a short TTL cache to avoid redundant I/O.

        Within a single ``validate()`` call — or rapid successive calls — the
        ``git status`` result is cached for up to ``_WORKTREE_DIFF_CACHE_TTL_SECONDS``
        seconds so that tight retry loops don't hammer the file system needlessly.
        """
        now = time.monotonic()
        if (
            self._worktree_diff_cache is not None
            and now - self._worktree_diff_cache_time < self._WORKTREE_DIFF_CACHE_TTL_SECONDS
        ):
            return self._worktree_diff_cache

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
            result: tuple[list[str], bool, list[str]] = ([], False, details)
        else:
            changed_files = [line.rstrip() for line in completed.stdout.splitlines() if line.strip()]
            details = [f"{len(changed_files)} changed path(s) detected."] if changed_files else ["Worktree is clean."]
            result = (changed_files, True, details)

        self._worktree_diff_cache = result
        self._worktree_diff_cache_time = time.monotonic()
        return result

    def _resolve_outcome(
        self,
        *,
        checks: Sequence[SupervisorCheck],
        latest_run_present: bool,
        artifact_ok: bool,
        git_ok: bool,
        structured_stage_evidence_present: bool = False,
        structured_stage_evidence_clean: bool = False,
        structured_stage_evidence_failed: bool = False,
        workflows_all_complete: bool = False,
        tasks_complete_ok: bool = False,
        has_unresolved_questions: bool = False,
        prompt_requests_commit: bool = False,
    ) -> tuple[str, str, str, str]:
        checks_by_name = {check.name: check for check in checks}
        if (
            not checks_by_name["bootstrap-files"].ok
            or not latest_run_present
            or (
                not checks_by_name["latest-run-state"].ok
                and artifact_ok is False
            )
        ):
            return (
                "blocked",
                "blocked",
                "Critical .dev state or latest-run artifacts are missing, so safe continuation is blocked.",
                "critical_state",
            )
        if not git_ok:
            return (
                "manual_review_needed",
                "manual_review_needed",
                "Git diff evidence could not be collected deterministically.",
                "git_diff",
            )

        if structured_stage_evidence_failed:
            return (
                "rework_required",
                "rework_required",
                "Explicit StageResult evidence contains a failed or negative terminal verdict.",
                "structured_stage_results",
            )

        artifacts_clean = checks_by_name["latest-run-artifacts"].ok
        paths_ok = checks_by_name["required-paths"].ok
        if structured_stage_evidence_clean and artifacts_clean and paths_ok:
            return (
                "approved",
                "approved",
                "All required work is complete — explicit StageResult evidence proves a clean terminal run.",
                "structured_stage_results",
            )

        # Early approval path: when the operator-facing process map (WORKFLOWS.md)
        # shows every phase complete, OR when the task-sync queue is fully done,
        # AND the latest run exited cleanly with all required outputs present,
        # AND the agent did not end with an unresolved question.
        #
        # Bypassing prompt-outcome-alignment here prevents false rework loops when
        # all of the agent's work in the current iteration is confined to .dev/
        # state files (no non-.dev/ file changes → prompt-alignment would fail
        # even though everything is genuinely done).
        #
        # We keep the unresolved-questions guard: if the agent asked a clarifying
        # question instead of completing work, we must NOT approve even when the
        # plan appears complete, because the plan may have been marked prematurely.
        plan_or_workflows_done = workflows_all_complete or (
            tasks_complete_ok and not prompt_requests_commit
        )
        if (
            not structured_stage_evidence_present
            and plan_or_workflows_done
            and artifacts_clean
            and paths_ok
            and not has_unresolved_questions
        ):
            return (
                "approved",
                "approved",
                "All required work is complete — WORKFLOWS.md/PLAN.md fully checked off and artifacts are clean.",
                "operator_state_fallback",
            )

        failing_checks = [check for check in checks if not check.ok]
        if failing_checks:
            return (
                "rework_required",
                "rework_required",
                failing_checks[0].summary,
                failing_checks[0].name,
            )
        return (
            "approved",
            "approved",
            "All deterministic supervisor checks passed.",
            "deterministic_checks",
        )

    def _recommend_next_phase(
        self,
        *,
        checks: Sequence[SupervisorCheck],
        verdict: str,
    ) -> str | None:
        if verdict == "approved":
            return "commit"
        if verdict in {"blocked", "manual_review_needed"}:
            return None

        phase_by_check = {
            "bootstrap-files": "plan",
            "task-sync": "plan",
            "plan-completion": "develop",
            "workflows-completion": "develop",
            "phase-pointer": "plan",
            "roadmap-focus": "plan",
            "latest-run-state": "test_and_review",
            "latest-run-artifacts": "develop",
            "required-paths": "develop",
            "worktree-diff": "develop",
            "prompt-outcome-alignment": "develop",
            "final-operation-verification": "develop",
        }
        for check in checks:
            if not check.ok:
                return phase_by_check.get(check.name, "plan")
        return "plan"

    def _resolve_state_dir(self, state_root: Path) -> Path:
        if state_root.is_absolute():
            return state_root
        candidates = (
            self.config.base_dev_dir / state_root,
            self.config.sessions_dir.parent / state_root,
            self.config.repo_root / state_root,
        )
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.exists():
                return resolved
        return candidates[0].resolve()
