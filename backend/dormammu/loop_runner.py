from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import TextIO
from typing import Any, Sequence

from dormammu._utils import iso_now as _iso_now
from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.config import AppConfig
from dormammu.continuation import build_continuation_prompt
from dormammu.state import StateRepository
from dormammu.supervisor import Supervisor, SupervisorReport, SupervisorRequest


@dataclass(frozen=True, slots=True)
class LoopRunRequest:
    cli_path: Path
    prompt_text: str
    repo_root: Path
    workdir: Path | None = None
    input_mode: str = "auto"
    prompt_flag: str | None = None
    extra_args: Sequence[str] = ()
    run_label: str | None = None
    max_retries: int = 0
    required_paths: Sequence[str] = ()
    require_worktree_changes: bool = False
    expected_roadmap_phase_id: str | None = "phase_4"

    @property
    def max_iterations(self) -> int:
        if self.max_retries == -1:
            return -1
        return self.max_retries + 1

    def as_agent_run_request(self, prompt_text: str) -> AgentRunRequest:
        return AgentRunRequest(
            cli_path=self.cli_path,
            prompt_text=prompt_text,
            repo_root=self.repo_root,
            workdir=self.workdir,
            input_mode=self.input_mode,
            prompt_flag=self.prompt_flag,
            extra_args=self.extra_args,
            run_label=self.run_label,
        )

    def to_state_dict(self) -> dict[str, Any]:
        return {
            "cli_path": str(self.cli_path),
            "prompt_text": self.prompt_text,
            "repo_root": str(self.repo_root),
            "workdir": str(self.workdir) if self.workdir else None,
            "input_mode": self.input_mode,
            "prompt_flag": self.prompt_flag,
            "extra_args": list(self.extra_args),
            "run_label": self.run_label,
            "max_retries": self.max_retries,
            "max_iterations": self.max_iterations,
            "required_paths": list(self.required_paths),
            "require_worktree_changes": self.require_worktree_changes,
            "expected_roadmap_phase_id": self.expected_roadmap_phase_id,
        }

    @classmethod
    def from_state_dict(cls, payload: dict[str, Any]) -> LoopRunRequest:
        workdir = payload.get("workdir")
        return cls(
            cli_path=Path(payload["cli_path"]),
            prompt_text=payload["prompt_text"],
            repo_root=Path(payload["repo_root"]),
            workdir=Path(workdir) if workdir else None,
            input_mode=payload.get("input_mode", "auto"),
            prompt_flag=payload.get("prompt_flag"),
            extra_args=tuple(payload.get("extra_args", [])),
            run_label=payload.get("run_label"),
            max_retries=int(payload.get("max_retries", 0)),
            required_paths=tuple(payload.get("required_paths", [])),
            require_worktree_changes=bool(payload.get("require_worktree_changes", False)),
            expected_roadmap_phase_id=payload.get("expected_roadmap_phase_id"),
        )


@dataclass(frozen=True, slots=True)
class LoopRunResult:
    status: str
    attempts_completed: int
    retries_used: int
    max_retries: int
    max_iterations: int
    latest_run_id: str | None
    supervisor_verdict: str
    report_path: Path | None
    continuation_prompt_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempts_completed": self.attempts_completed,
            "retries_used": self.retries_used,
            "max_retries": self.max_retries,
            "max_iterations": self.max_iterations,
            "latest_run_id": self.latest_run_id,
            "supervisor_verdict": self.supervisor_verdict,
            "report_path": str(self.report_path) if self.report_path else None,
            "continuation_prompt_path": (
                str(self.continuation_prompt_path) if self.continuation_prompt_path else None
            ),
        }


class LoopRunner:
    def __init__(
        self,
        config: AppConfig,
        repository: StateRepository | None = None,
        adapter: CliAdapter | None = None,
        supervisor: Supervisor | None = None,
        progress_stream: TextIO | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or StateRepository(config)
        self.progress_stream = progress_stream or sys.stderr
        self.adapter = adapter or CliAdapter(config, live_output_stream=self.progress_stream)
        self.supervisor = supervisor or Supervisor(config, repository=self.repository)

    def run(
        self,
        request: LoopRunRequest,
        *,
        start_attempt: int = 1,
        prompt_text: str | None = None,
    ) -> LoopRunResult:
        if request.max_retries < -1:
            raise ValueError("max_retries must be -1 or greater.")

        roadmap_phase_ids = [request.expected_roadmap_phase_id] if request.expected_roadmap_phase_id else None
        self.repository.ensure_bootstrap_state(
            prompt_text=request.prompt_text,
            active_roadmap_phase_ids=roadmap_phase_ids,
        )
        runtime_repository = self.repository
        runtime_adapter = self.adapter
        runtime_supervisor = self.supervisor
        if self.repository.session_id is None:
            session_state = self.repository.read_session_state()
            session_id = session_state.get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                runtime_repository = StateRepository(self.config, session_id=session_id)
                runtime_config = self.config.with_overrides(
                    dev_dir=runtime_repository.dev_dir,
                    logs_dir=runtime_repository.logs_dir,
                )
                runtime_adapter = CliAdapter(runtime_config, live_output_stream=self.progress_stream)
                runtime_supervisor = Supervisor(self.config, repository=runtime_repository)

        current_prompt = prompt_text if prompt_text is not None else request.prompt_text
        attempt_number = start_attempt
        retries_used = max(start_attempt - 1, 0)
        continuation_prompt_path: Path | None = None
        report_path: Path | None = None

        while True:
            self._persist_loop_state(
                status="running",
                request=request,
                attempts_completed=attempt_number - 1,
                retries_used=retries_used,
                latest_run_id=None,
                report=None,
                report_path=report_path,
                continuation_prompt_path=continuation_prompt_path,
                next_action=f"Run supervised loop attempt {attempt_number} for the active request.",
            )
            self._emit_loop_snapshot(
                repository=runtime_repository,
                request=request,
                attempt_number=attempt_number,
                retries_used=retries_used,
            )

            def _handle_started(started: Any) -> None:
                runtime_repository.record_current_run(started)
                self._emit_command_started(started)
                self._persist_loop_state(
                    status="running",
                    request=request,
                    attempts_completed=attempt_number - 1,
                    retries_used=retries_used,
                    latest_run_id=started.run_id,
                    report=None,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                    next_action=(
                        f"Supervised loop attempt {attempt_number} is running and "
                        "streaming logs to .dev/logs."
                    ),
                )

            result = runtime_adapter.run_once(
                request.as_agent_run_request(current_prompt),
                on_started=_handle_started,
            )
            runtime_repository.record_latest_run(result)

            if result.exit_code == 0 and self._stdout_has_promise_complete(result.stdout_path):
                self._write_progress([
                    "=== dormammu promise ===",
                    f"attempt: {attempt_number}",
                    "Agent emitted <promise>COMPLETE</promise> — treating as self-declared completion.",
                ])
                next_action = "Agent self-declared all work complete via <promise>COMPLETE</promise>."
                self._persist_loop_state(
                    status="completed",
                    request=request,
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    latest_run_id=result.run_id,
                    report=None,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                    next_action=next_action,
                )
                return LoopRunResult(
                    status="completed",
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    max_retries=request.max_retries,
                    max_iterations=request.max_iterations,
                    latest_run_id=result.run_id,
                    supervisor_verdict="promise_complete",
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                )

            if result.exit_code != 0 and result.fallback_trigger is not None:
                self._persist_loop_state(
                    status="blocked",
                    request=request,
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    latest_run_id=result.run_id,
                    report=None,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                    next_action=(
                        "All configured coding-agent CLIs reported token exhaustion. "
                        "Update dormammu.json or wait for quota recovery before resuming."
                    ),
                )
                return LoopRunResult(
                    status="blocked",
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    max_retries=request.max_retries,
                    max_iterations=request.max_iterations,
                    latest_run_id=result.run_id,
                    supervisor_verdict="blocked",
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                )

            report = runtime_supervisor.validate(
                SupervisorRequest(
                    required_paths=request.required_paths,
                    require_worktree_changes=request.require_worktree_changes,
                    expected_roadmap_phase_id=request.expected_roadmap_phase_id,
                )
            )
            report_path = runtime_repository.write_supervisor_report(report.to_markdown())
            report = report.with_report_path(report_path)
            self._emit_supervisor_result(report, attempt_number=attempt_number)

            if report.verdict == "approved":
                next_action = (
                    "All PLAN.md items are marked [O]. Supervisor approved the latest run and the loop can stop."
                )
                self._persist_loop_state(
                    status="completed",
                    request=request,
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    latest_run_id=result.run_id,
                    report=report,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                    next_action=next_action,
                )
                return LoopRunResult(
                    status="completed",
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    max_retries=request.max_retries,
                    max_iterations=request.max_iterations,
                    latest_run_id=result.run_id,
                    supervisor_verdict=report.verdict,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                )

            if report.verdict != "rework_required":
                status = "blocked" if report.verdict == "blocked" else "manual_review_needed"
                self._persist_loop_state(
                    status=status,
                    request=request,
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    latest_run_id=result.run_id,
                    report=report,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                    next_action="Manual intervention is required before the loop can continue safely.",
                )
                self._emit_escalation_banner(status=status, report=report, attempt_number=attempt_number)
                return LoopRunResult(
                    status=status,
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    max_retries=request.max_retries,
                    max_iterations=request.max_iterations,
                    latest_run_id=result.run_id,
                    supervisor_verdict=report.verdict,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                )

            next_task = runtime_repository.read_session_state().get("task_sync", {}).get("next_pending_task")
            workflow_state = runtime_repository.read_workflow_state()
            continuation = build_continuation_prompt(
                latest_run=workflow_state["latest_run"],
                report=report,
                next_task=next_task,
                original_prompt_text=request.prompt_text,
                repo_guidance=workflow_state.get("bootstrap", {}).get("repo_guidance"),
                patterns_text=runtime_repository.read_patterns_text(),
            )
            continuation_prompt_path = runtime_repository.write_continuation_prompt(continuation.text)

            if not self._should_retry(request.max_retries, retries_used):
                next_action = "Retry budget is exhausted before every PLAN.md item reached [O]. Resume later or increase the loop budget."
                self._persist_loop_state(
                    status="failed",
                    request=request,
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    latest_run_id=result.run_id,
                    report=report,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                    next_action=next_action,
                )
                return LoopRunResult(
                    status="failed",
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    max_retries=request.max_retries,
                    max_iterations=request.max_iterations,
                    latest_run_id=result.run_id,
                    supervisor_verdict=report.verdict,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                )

            next_action = (
                f"Retry attempt {attempt_number + 1} is queued because PLAN.md still has unchecked work."
            )
            if report.recommended_next_phase == "develop":
                next_action = (
                    f"Retry attempt {attempt_number + 1} is queued because final verification requires a return to develop."
                )
            elif report.recommended_next_phase:
                next_action = (
                    f"Retry attempt {attempt_number + 1} is queued because the supervisor wants work to resume from {report.recommended_next_phase}."
                )
            if isinstance(next_task, str) and next_task.strip():
                next_action = f"{next_action} Next pending item: {next_task}"
            self._persist_loop_state(
                status="awaiting_retry",
                request=request,
                attempts_completed=attempt_number,
                retries_used=retries_used,
                latest_run_id=result.run_id,
                report=report,
                report_path=report_path,
                continuation_prompt_path=continuation_prompt_path,
                next_action=next_action,
            )
            current_prompt = continuation.text
            attempt_number += 1
            retries_used += 1

    def _emit_escalation_banner(
        self,
        *,
        status: str,
        report: SupervisorReport,
        attempt_number: int,
    ) -> None:
        separator = "!" * 60
        self._write_progress(
            [
                separator,
                f"=== DORMAMMU ESCALATION: {status.upper()} ===",
                separator,
                f"attempt: {attempt_number}",
                f"verdict: {report.verdict}",
                f"summary: {report.summary}",
                f"report: {report.report_path or '.dev/supervisor_report.md'}",
                "Manual intervention is required before this loop can continue.",
                "Run `dormammu resume` after resolving the issue.",
                separator,
            ]
        )

    def _emit_loop_snapshot(
        self,
        *,
        repository: StateRepository,
        request: LoopRunRequest,
        attempt_number: int,
        retries_used: int,
    ) -> None:
        lines = [
            "=== dormammu loop attempt ===",
            f"attempt: {attempt_number}",
            f"retries used: {retries_used}/{request.max_retries if request.max_retries != -1 else 'infinite'}",
            f"max iterations: {request.max_iterations if request.max_iterations != -1 else 'infinite'}",
            f"target project: {request.repo_root.resolve()}",
            f"session: {repository.session_id or 'active-root'}",
            f"cli: {request.cli_path}",
            f"workdir: {(request.workdir or request.repo_root).resolve()}",
        ]
        self._write_progress(lines)
        self._emit_state_snapshot(repository, "DASHBOARD.md")
        self._emit_state_snapshot(repository, "PLAN.md")

    def _emit_command_started(self, started: Any) -> None:
        self._write_progress(
            [
                "=== dormammu command ===",
                f"run id: {started.run_id}",
                f"cli path: {started.cli_path}",
                f"workdir: {started.workdir}",
                f"prompt mode: {started.prompt_mode}",
                f"command: {' '.join(started.command)}",
                f"stdout log: {started.stdout_path}",
                f"stderr log: {started.stderr_path}",
            ]
        )

    def _emit_supervisor_result(self, report: SupervisorReport, *, attempt_number: int) -> None:
        self._write_progress(
            [
                "=== dormammu supervisor ===",
                f"attempt: {attempt_number}",
                f"verdict: {report.verdict}",
                f"escalation: {report.escalation}",
                f"summary: {report.summary}",
                f"report: {report.report_path or '.dev/supervisor_report.md'}",
            ]
        )

    def _emit_state_snapshot(self, repository: StateRepository, name: str) -> None:
        path = repository.state_file(name)
        if not path.exists():
            self._write_progress([f"=== {name} missing ===", str(path)])
            return
        content = path.read_text(encoding="utf-8").rstrip()
        self._write_progress([f"=== {name} ===", content if content else "(empty)"])

    def _write_progress(self, lines: Sequence[str]) -> None:
        if self.progress_stream is None:
            return
        for line in lines:
            print(line, file=self.progress_stream)
        self.progress_stream.flush()

    def _should_retry(self, max_retries: int, retries_used: int) -> bool:
        if max_retries == -1:
            return True
        return retries_used < max_retries

    @staticmethod
    def _stdout_has_promise_complete(stdout_path: Path) -> bool:
        """Return True if the agent stdout contains the self-completion signal."""
        if not stdout_path.exists():
            return False
        try:
            content = stdout_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return "<promise>COMPLETE</promise>" in content

    def _persist_loop_state(
        self,
        *,
        status: str,
        request: LoopRunRequest,
        attempts_completed: int,
        retries_used: int,
        latest_run_id: str | None,
        report: SupervisorReport | None,
        report_path: Path | None,
        continuation_prompt_path: Path | None,
        next_action: str,
    ) -> None:
        timestamp = _iso_now()
        loop_state = {
            "status": status,
            "request": request.to_state_dict(),
            "attempts_completed": attempts_completed,
            "retries_used": retries_used,
            "max_retries": request.max_retries,
            "max_iterations": request.max_iterations,
            "required_paths": list(request.required_paths),
            "require_worktree_changes": request.require_worktree_changes,
            "expected_roadmap_phase_id": request.expected_roadmap_phase_id,
            "latest_run_id": latest_run_id,
            "latest_supervisor_verdict": report.verdict if report else None,
            "latest_supervisor_report_path": str(report_path) if report_path else None,
            "latest_continuation_prompt_path": (
                str(continuation_prompt_path) if continuation_prompt_path else None
            ),
        }

        session_state = self.repository.read_session_state()
        workflow_state = self.repository.read_workflow_state()
        for payload in (session_state, workflow_state):
            payload["updated_at"] = timestamp
            payload["loop"] = loop_state
            payload["supervisor_report"] = {
                "path": str(report_path) if report_path else ".dev/supervisor_report.md",
                "status": report.verdict if report else "not_run",
            }
            payload["latest_continuation_prompt"] = (
                str(continuation_prompt_path) if continuation_prompt_path else None
            )
            payload["next_action"] = next_action

        if report is not None:
            workflow_state.setdefault("supervisor", {})
            workflow_state["supervisor"]["verdict"] = report.verdict
            workflow_state["supervisor"]["escalation"] = report.escalation
            workflow_state["supervisor"]["reason"] = report.summary
            workflow_state.setdefault("workflow", {})
            if report.recommended_next_phase:
                workflow_state["workflow"]["resume_from_phase"] = report.recommended_next_phase

        session_state["last_safe_checkpoint"] = {
            "phase": session_state.get("active_phase", "develop"),
            "timestamp": timestamp,
            "description": f"Loop state persisted with status '{status}'.",
        }

        self.repository.write_session_state(session_state)
        self.repository.write_workflow_state(workflow_state)
