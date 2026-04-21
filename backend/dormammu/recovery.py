from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from dormammu._utils import iso_now as _iso_now
from dormammu.artifacts import ArtifactRef
from dormammu.config import AppConfig
from dormammu.loop_runner import LoopRunRequest, LoopRunResult, LoopRunner
from dormammu.results import (
    ResultStatus,
    RetryMetadata,
    StageResult,
    TimingMetadata,
)
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

    def _persist_completed_revalidation(
        self,
        *,
        request: LoopRunRequest,
        loop_state: dict[str, object],
        report_ref: ArtifactRef,
        supervisor_verdict: str,
        supervisor_escalation: str,
        supervisor_reason: str,
    ) -> None:
        """Persist an approved supervisor revalidation without rerunning the loop."""
        timestamp = _iso_now()
        report_path = report_ref.path
        latest_run_id = self.repository.read_workflow_state().get("latest_run", {}).get("run_id")
        continuation_prompt_path = loop_state.get("latest_continuation_prompt_path")
        updated_loop = {
            "status": "completed",
            "request": request.to_state_dict(),
            "attempts_completed": int(loop_state.get("attempts_completed", 0)),
            "retries_used": int(loop_state.get("retries_used", 0)),
            "max_retries": request.max_retries,
            "max_iterations": request.max_iterations,
            "required_paths": list(request.required_paths),
            "require_worktree_changes": request.require_worktree_changes,
            "expected_roadmap_phase_id": request.expected_roadmap_phase_id,
            "latest_run_id": latest_run_id,
            "latest_supervisor_verdict": supervisor_verdict,
            "latest_supervisor_report_path": str(report_path),
            "latest_continuation_prompt_path": continuation_prompt_path,
            "latest_continuation_prompt_artifact": loop_state.get(
                "latest_continuation_prompt_artifact"
            ),
        }
        next_action = (
            "Saved state already passes supervisor validation. Resume from Commit only if explicitly "
            "requested; otherwise continue with a new prompt."
        )

        session_state = self.repository.read_session_state()
        workflow_state = self.repository.read_workflow_state()
        for payload in (session_state, workflow_state):
            payload["updated_at"] = timestamp
            payload["current_run"] = None
            payload["loop"] = updated_loop
            payload["supervisor_report"] = {
                "path": str(report_path),
                "status": supervisor_verdict,
            }
            payload["latest_continuation_prompt"] = continuation_prompt_path
            payload["next_action"] = next_action

        session_state["last_safe_checkpoint"] = {
            "phase": session_state.get("active_phase", "develop"),
            "timestamp": timestamp,
            "description": "Saved loop state revalidated and persisted with status 'completed'.",
        }
        workflow_state.setdefault("supervisor", {})
        workflow_state["supervisor"]["verdict"] = supervisor_verdict
        workflow_state["supervisor"]["escalation"] = supervisor_escalation
        workflow_state["supervisor"]["reason"] = supervisor_reason
        workflow_state.setdefault("workflow", {})
        if session_state.get("active_phase"):
            workflow_state["workflow"]["resume_from_phase"] = session_state["active_phase"]

        self.repository.write_state_pair(
            session_payload=session_state,
            workflow_payload=workflow_state,
        )

    def _refresh_request_expected_roadmap_phase(
        self,
        request: LoopRunRequest,
        workflow_state: dict[str, object],
    ) -> LoopRunRequest:
        roadmap = workflow_state.get("roadmap")
        if not isinstance(roadmap, dict):
            return request
        active_phase_ids = roadmap.get("active_phase_ids")
        if not isinstance(active_phase_ids, list):
            return request
        for phase_id in active_phase_ids:
            if isinstance(phase_id, str) and phase_id.strip():
                if phase_id == request.expected_roadmap_phase_id:
                    return request
                return replace(request, expected_roadmap_phase_id=phase_id)
        return request

    def _saved_continuation_prompt_ref(
        self,
        *,
        loop_state: dict[str, object],
        continuation_prompt_path: Path | None,
        run_id: str | None = None,
        role: str | None = None,
        stage_name: str | None = None,
    ) -> ArtifactRef | None:
        stored_ref = ArtifactRef.from_dict(loop_state.get("latest_continuation_prompt_artifact"))
        if stored_ref is not None:
            return stored_ref
        if continuation_prompt_path is None:
            return None
        return self.repository._artifact_writer().reference(
            kind="continuation_prompt",
            path=continuation_prompt_path,
            label="continuation_prompt",
            content_type="text/plain",
            run_id=run_id,
            role=role,
            stage_name=stage_name,
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
        request = self._refresh_request_expected_roadmap_phase(request, workflow_state)
        if max_retries_override is not None:
            request = LoopRunRequest(
                cli_path=request.cli_path,
                prompt_text=request.prompt_text,
                repo_root=request.repo_root,
                agent_role=request.agent_role,
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
        latest_run = workflow_state.get("latest_run", {})
        latest_run_id = latest_run.get("run_id") if isinstance(latest_run, dict) else None
        report_ref = self.repository.write_supervisor_report_ref(
            report.to_markdown(),
            run_id=latest_run_id,
            role=request.agent_role,
            stage_name=request.agent_role,
        )
        report_path = report_ref.path
        report = report.with_report_path(report_path)

        if report.verdict in {"blocked", "manual_review_needed"}:
            raise RuntimeError(report.summary)
        if report.verdict == "approved":
            timestamp = _iso_now()
            latest_started_at = (
                latest_run.get("started_at") if isinstance(latest_run, dict) else None
            )
            saved_continuation_prompt = loop_state.get("latest_continuation_prompt_path")
            continuation_prompt_path = (
                Path(saved_continuation_prompt)
                if isinstance(saved_continuation_prompt, str) and saved_continuation_prompt
                else None
            )
            continuation_ref = self._saved_continuation_prompt_ref(
                loop_state=loop_state,
                continuation_prompt_path=continuation_prompt_path,
                run_id=latest_run_id,
                role=request.agent_role,
                stage_name=request.agent_role,
            )
            summary = report.summary
            stage_timing = TimingMetadata(
                started_at=latest_started_at,
                completed_at=timestamp,
            )
            stage_results = (
                StageResult(
                    role=request.agent_role,
                    stage_name=request.agent_role,
                    status=ResultStatus.COMPLETED,
                    verdict=report.verdict,
                    summary=summary,
                    report_path=report_path,
                    artifacts=tuple(
                        artifact
                        for artifact in (report_ref, continuation_ref)
                        if artifact is not None
                    ),
                    retry=RetryMetadata(
                        attempt=int(loop_state.get("attempts_completed", 0)),
                        retries_used=int(loop_state.get("retries_used", 0)),
                        max_retries=request.max_retries,
                        max_iterations=request.max_iterations,
                    ),
                    timing=stage_timing,
                    metadata={
                        "latest_run_id": latest_run_id,
                        "revalidated_from_saved_state": True,
                    },
                ),
            )
            self._persist_completed_revalidation(
                request=request,
                loop_state=loop_state,
                report_ref=report_ref,
                supervisor_verdict=report.verdict,
                supervisor_escalation=report.escalation,
                supervisor_reason=report.summary,
            )
            return LoopRunResult(
                status="completed",
                attempts_completed=int(loop_state.get("attempts_completed", 0)),
                retries_used=int(loop_state.get("retries_used", 0)),
                max_retries=request.max_retries,
                max_iterations=request.max_iterations,
                latest_run_id=latest_run_id,
                supervisor_verdict=report.verdict,
                report_path=report_path,
                continuation_prompt_path=continuation_prompt_path,
                summary=summary,
                stage_results=stage_results,
                artifacts=tuple(
                    artifact
                    for artifact in (report_ref, continuation_ref)
                    if artifact is not None
                ),
                timing=stage_timing,
                metadata={"revalidated_from_saved_state": True},
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
        if request.max_iterations != -1 and attempts_completed >= request.max_iterations:
            timestamp = _iso_now()
            latest_run = workflow_state.get("latest_run", {})
            latest_run_id = latest_run.get("run_id") if isinstance(latest_run, dict) else None
            latest_started_at = (
                latest_run.get("started_at") if isinstance(latest_run, dict) else None
            )
            continuation_prompt_path = Path(prompt_path) if prompt_path else None
            continuation_ref = self._saved_continuation_prompt_ref(
                loop_state=loop_state,
                continuation_prompt_path=continuation_prompt_path,
                run_id=latest_run_id,
                role=request.agent_role,
                stage_name=request.agent_role,
            )
            summary = (
                f"{report.summary} Resume stopped because max_iterations is exhausted."
                if report.summary
                else "Resume stopped because max_iterations is exhausted."
            )
            retry = RetryMetadata(
                attempt=attempts_completed,
                retries_used=int(loop_state.get("retries_used", 0)),
                max_retries=request.max_retries,
                max_iterations=request.max_iterations,
            )
            timing = TimingMetadata(
                started_at=latest_started_at,
                completed_at=timestamp,
            )
            stage_results = (
                StageResult(
                    role=request.agent_role,
                    stage_name=request.agent_role,
                    status=ResultStatus.FAILED,
                    verdict=report.verdict,
                    summary=summary,
                    report_path=report_path,
                    artifacts=tuple(
                        artifact
                        for artifact in (
                            report_ref,
                            continuation_ref,
                        )
                        if artifact is not None
                    ),
                    retry=retry,
                    timing=timing,
                    metadata={
                        "latest_run_id": latest_run_id,
                        "resume_blocked": "max_iterations_exhausted",
                    },
                ),
            )
            return LoopRunResult(
                status="failed",
                attempts_completed=attempts_completed,
                retries_used=int(loop_state.get("retries_used", 0)),
                max_retries=request.max_retries,
                max_iterations=request.max_iterations,
                latest_run_id=latest_run_id,
                supervisor_verdict=report.verdict,
                report_path=report_path,
                continuation_prompt_path=continuation_prompt_path,
                summary=summary,
                stage_results=stage_results,
                artifacts=tuple(
                    artifact
                    for artifact in (report_ref, continuation_ref)
                    if artifact is not None
                ),
                retry=retry,
                timing=timing,
                metadata={"resume_blocked": "max_iterations_exhausted"},
            )
        return self.loop_runner.run(
            request,
            start_attempt=attempts_completed + 1,
            prompt_text=prompt_text,
        )
