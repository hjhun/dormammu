from __future__ import annotations

from pathlib import Path

from dormammu.config import AppConfig
from dormammu.loop_runner import LoopRunRequest, LoopRunResult, LoopRunner
from dormammu.state import StateRepository
from dormammu.supervisor import Supervisor, SupervisorRequest


class RecoveryManager:
    def __init__(
        self,
        config: AppConfig,
        repository: StateRepository | None = None,
        loop_runner: LoopRunner | None = None,
        supervisor: Supervisor | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or StateRepository(config)
        self.supervisor = supervisor or Supervisor(config, repository=self.repository)
        self.loop_runner = loop_runner or LoopRunner(
            config,
            repository=self.repository,
            supervisor=self.supervisor,
        )

    def resume(
        self,
        *,
        max_retries_override: int | None = None,
        session_id: str | None = None,
    ) -> LoopRunResult:
        if session_id is not None:
            self.repository.restore_session(session_id)
        else:
            self.repository.ensure_bootstrap_state()
        workflow_state = self.repository.read_workflow_state()
        loop_state = workflow_state.get("loop")
        if not isinstance(loop_state, dict) or "request" not in loop_state:
            raise RuntimeError("No saved loop state is available to resume.")

        request = LoopRunRequest.from_state_dict(loop_state["request"])
        if max_retries_override is not None:
            request = LoopRunRequest(
                cli_path=request.cli_path,
                prompt_text=request.prompt_text,
                repo_root=request.repo_root,
                workdir=request.workdir,
                input_mode=request.input_mode,
                prompt_flag=request.prompt_flag,
                extra_args=request.extra_args,
                run_label=request.run_label,
                max_retries=max_retries_override,
                required_paths=request.required_paths,
                require_worktree_changes=request.require_worktree_changes,
                expected_roadmap_phase_id=request.expected_roadmap_phase_id,
            )

        report = self.supervisor.validate(
            SupervisorRequest(
                required_paths=request.required_paths,
                require_worktree_changes=request.require_worktree_changes,
                expected_roadmap_phase_id=request.expected_roadmap_phase_id,
            )
        )
        report_path = self.repository.write_supervisor_report(report.to_markdown())
        report = report.with_report_path(report_path)

        if report.verdict in {"blocked", "manual_review_needed"}:
            raise RuntimeError(report.summary)
        if loop_state.get("status") == "completed" and report.verdict == "approved":
            return LoopRunResult(
                status="completed",
                attempts_completed=int(loop_state.get("attempts_completed", 0)),
                retries_used=int(loop_state.get("retries_used", 0)),
                max_retries=request.max_retries,
                latest_run_id=workflow_state.get("latest_run", {}).get("run_id"),
                supervisor_verdict=report.verdict,
                report_path=report_path,
                continuation_prompt_path=None,
            )

        prompt_path = loop_state.get("latest_continuation_prompt_path")
        if prompt_path:
            prompt_text = Path(prompt_path).read_text(encoding="utf-8")
        else:
            latest_run = workflow_state.get("latest_run", {})
            prompt_artifact = latest_run.get("artifacts", {}).get("prompt")
            if not prompt_artifact:
                raise RuntimeError("No saved prompt artifact is available to resume.")
            prompt_text = Path(prompt_artifact).read_text(encoding="utf-8")

        attempts_completed = int(loop_state.get("attempts_completed", 0))
        return self.loop_runner.run(
            request,
            start_attempt=attempts_completed + 1,
            prompt_text=prompt_text,
        )
