from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
import sys
from typing import TextIO
from typing import Any, Mapping, Sequence

from dormammu._utils import iso_now as _iso_now
from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.agent.permissions import PermissionDecision
from dormammu.agent.profiles import AgentProfile
from dormammu.config import AppConfig
from dormammu.continuation import build_continuation_prompt
from dormammu.lifecycle import (
    ArtifactPersistedPayload,
    ArtifactRef,
    LifecycleEventType,
    LifecycleRecorder,
    PermissionGatePayload,
    RunEventPayload,
    StageEventPayload,
    SupervisorHandoffPayload,
    WorktreeEventPayload,
)
from dormammu.runtime_hooks import RuntimeHookBlocked, RuntimeHookController
from dormammu.results import (
    ResultArtifact,
    ResultStatus,
    RetryMetadata,
    RunResult as LoopRunResult,
    StageResult,
    TimingMetadata,
)
from dormammu.skills import runtime_skill_summary
from dormammu.state import StateRepository
from dormammu.supervisor import Supervisor, SupervisorReport, SupervisorRequest
from dormammu.worktree import ManagedWorktree, WorktreeOwner, WorktreeService, WorktreeServiceError

# ── Termination constants ────────────────────────────────────────────────────
#
# RALPH INSIGHT: Every agent loop must have an upper bound.
# Source: github.com/snarktank/ralph — ralph uses MAX_ITERATIONS (default 10).
# Dormammu's default budget is 50 iterations (see _resolve_loop_retry_budget).
# The -1 "infinite" sentinel is still bounded by _HARD_ITERATION_CAP so that
# a misconfigured or runaway loop cannot spin forever and consume unbounded API
# quota.  Operators who legitimately need more iterations should supply a
# positive --max-iterations value larger than this ceiling instead of -1.
#
# STAGNATION: Even within the allowed budget a loop that makes no measurable
# forward progress is wasting cycles and money.  If the same (pending_tasks,
# next_pending_task) snapshot repeats _STAGNATION_WINDOW consecutive iterations
# the loop is cycling in place; we surface this as a "blocked" result so the
# operator can intervene rather than burning the full retry budget silently.

_HARD_ITERATION_CAP: int = 100
"""Absolute maximum iterations even when max_retries=-1 (ralph-derived safety ceiling)."""

_STAGNATION_WINDOW: int = 3
"""Consecutive identical task-state snapshots that trigger a stagnation bail-out."""


class _StagnationDetector:
    """Sliding-window detector that identifies when a loop makes no forward progress.

    Stagnation is defined as the same ``(pending_tasks, next_pending_task)``
    snapshot repeating :attr:`window_size` consecutive iterations with at
    least one pending task remaining.

    Create one instance per :meth:`LoopRunner.run` call so each run starts
    with a clean window and resumed loops don't inherit stale state.
    """

    def __init__(self, window_size: int = _STAGNATION_WINDOW) -> None:
        self._window_size = window_size
        self._window: list[tuple[int, str | None]] = []

    def record(self, pending_tasks: int, next_pending_task: str | None) -> None:
        """Record the current task-state snapshot, evicting the oldest entry."""
        self._window.append((pending_tasks, next_pending_task))
        if len(self._window) > self._window_size:
            self._window.pop(0)

    def is_stagnant(self, pending_tasks: int) -> bool:
        """Return True when the window is full and every snapshot is identical."""
        return (
            pending_tasks > 0
            and len(self._window) >= self._window_size
            and len(set(self._window)) == 1
        )


@dataclass(frozen=True, slots=True)
class LoopRunRequest:
    cli_path: Path
    prompt_text: str
    repo_root: Path
    agent_role: str = "developer"
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
            "agent_role": self.agent_role,
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
            agent_role=payload.get("agent_role", "developer"),
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

    def resolve_agent_profile(self, request: LoopRunRequest) -> AgentProfile:
        return self.config.resolve_agent_profile(request.agent_role)

    def _managed_worktree_requested(
        self,
        *,
        request: LoopRunRequest,
        profile: AgentProfile,
    ) -> bool:
        if request.agent_role != "developer":
            return False
        if not self.config.worktree.enabled:
            return False
        create_allowed = profile.worktree_policy.evaluate("create") is PermissionDecision.ALLOW
        reuse_allowed = profile.worktree_policy.evaluate("reuse") is PermissionDecision.ALLOW
        return create_allowed or reuse_allowed

    def _isolated_workdir(
        self,
        *,
        request: LoopRunRequest,
        worktree: ManagedWorktree,
    ) -> Path:
        if request.workdir is None:
            return worktree.isolated_path
        try:
            relative_workdir = request.workdir.resolve().relative_to(request.repo_root.resolve())
        except ValueError:
            return worktree.isolated_path
        return (worktree.isolated_path / relative_workdir).resolve()

    def _prepare_managed_worktree(
        self,
        *,
        request: LoopRunRequest,
        profile: AgentProfile,
        repository: StateRepository,
        session_id: str | None,
    ) -> ManagedWorktree | None:
        service = WorktreeService.from_app_config(self.config)
        owner = WorktreeOwner(
            session_id=session_id,
            agent_role=request.agent_role,
        )
        label = request.run_label or request.agent_role
        worktree: ManagedWorktree | None = None

        if profile.worktree_policy.evaluate("reuse") is PermissionDecision.ALLOW:
            worktree = service.find_worktree(
                source_repo_root=request.repo_root,
                owner=owner,
                label=label,
            )
        if (
            worktree is None
            and profile.worktree_policy.evaluate("create") is PermissionDecision.ALLOW
        ):
            worktree = service.ensure_worktree(
                source_repo_root=request.repo_root,
                owner=owner,
                label=label,
            )
        if worktree is None:
            return None

        repository.upsert_managed_worktree(worktree, active=True)
        return worktree

    def run(
        self,
        request: LoopRunRequest,
        *,
        start_attempt: int = 1,
        prompt_text: str | None = None,
        emit_prompt_intake: bool = True,
        emit_stage_hooks: bool = True,
        manage_session_lifecycle: bool = True,
    ) -> LoopRunResult:
        if request.max_retries < -1:
            raise ValueError("max_retries must be -1 or greater.")
        profile = self.resolve_agent_profile(request)

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
                runtime_supervisor = Supervisor(runtime_config, repository=runtime_repository)

        session_state = runtime_repository.read_session_state()
        session_id = session_state.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            session_id = None
        runtime_skill_state = runtime_repository.record_runtime_skill_resolution(
            role=request.agent_role,
            profile=profile,
        )
        hook_controller = RuntimeHookController(
            self.config,
            repository=runtime_repository,
            progress_stream=self.progress_stream,
        )
        lifecycle = LifecycleRecorder.for_execution(
            runtime_repository,
            scope="loop",
            session_id=session_id,
            label=request.run_label or request.agent_role,
            default_metadata={"source": "loop_runner", "entrypoint": "LoopRunner.run"},
        )
        lifecycle.emit(
            event_type=LifecycleEventType.RUN_REQUESTED,
            role=request.agent_role,
            stage=request.agent_role,
            status="requested",
            payload=RunEventPayload(
                source="loop_runner",
                entrypoint="LoopRunner.run",
                trigger="interactive",
                prompt_summary=request.prompt_text.splitlines()[0].strip()
                if request.prompt_text.strip()
                else None,
            ),
            metadata={
                "run_label": request.run_label,
                "max_retries": request.max_retries,
                "expected_roadmap_phase_id": request.expected_roadmap_phase_id,
            },
        )

        current_prompt = prompt_text if prompt_text is not None else request.prompt_text
        attempt_number = start_attempt
        retries_used = max(start_attempt - 1, 0)
        continuation_prompt_path: Path | None = None
        report_path: Path | None = None
        active_worktree: ManagedWorktree | None = None
        worktree_released = False
        run_started_at = _iso_now()
        # Reset per run() call so resumed loops don't inherit stale state.
        # Read _STAGNATION_WINDOW at call time so tests can patch it dynamically.
        stagnation = _StagnationDetector(window_size=_STAGNATION_WINDOW)

        def _blocked_result(
            *,
            attempts_completed_value: int,
            retries_used_value: int,
            latest_run_id_value: str | None,
            report_value: SupervisorReport | None,
            continuation_prompt_value: Path | None,
        ) -> LoopRunResult:
            return LoopRunResult(
                status="blocked",
                attempts_completed=attempts_completed_value,
                retries_used=retries_used_value,
                max_retries=request.max_retries,
                max_iterations=request.max_iterations,
                latest_run_id=latest_run_id_value,
                supervisor_verdict="blocked",
                report_path=report_value.report_path if report_value is not None else None,
                continuation_prompt_path=continuation_prompt_value,
            )

        def _enrich_result(
            result: LoopRunResult,
            *,
            report_value: SupervisorReport | None,
            continuation_prompt_value: Path | None,
            terminal_error: str | None,
        ) -> LoopRunResult:
            completed_at = _iso_now()
            summary = result.summary
            if summary is None:
                if report_value is not None:
                    summary = report_value.summary
                else:
                    summary = terminal_error
            stage_artifacts: list[ResultArtifact] = []
            if continuation_prompt_value is not None:
                stage_artifacts.append(
                    ResultArtifact(
                        kind="continuation_prompt",
                        path=continuation_prompt_value,
                        label="continuation_prompt",
                        content_type="text/plain",
                    )
                )
            stage_results = result.stage_results
            if not stage_results:
                stage_results = (
                    StageResult(
                        role=request.agent_role,
                        stage_name=request.agent_role,
                        status=result.status,
                        verdict=result.supervisor_verdict,
                        summary=summary,
                        report_path=result.report_path,
                        artifacts=tuple(stage_artifacts),
                        retry=RetryMetadata(
                            attempt=result.attempts_completed,
                            retries_used=result.retries_used,
                            max_retries=result.max_retries,
                            max_iterations=result.max_iterations,
                        ),
                        timing=TimingMetadata(
                            started_at=run_started_at,
                            completed_at=completed_at,
                        ),
                        metadata={"latest_run_id": result.latest_run_id},
                    ),
                )
            return replace(
                result,
                summary=summary,
                stage_results=stage_results,
                retry=result.retry
                or RetryMetadata(
                    attempt=result.attempts_completed,
                    retries_used=result.retries_used,
                    max_retries=result.max_retries,
                    max_iterations=result.max_iterations,
                ),
                timing=result.timing
                or TimingMetadata(
                    started_at=run_started_at,
                    completed_at=completed_at,
                ),
            )

        def _finish(
            result: LoopRunResult,
            *,
            attempts_completed_value: int,
            retries_used_value: int,
            latest_run_id_value: str | None,
            report_value: SupervisorReport | None,
            continuation_prompt_value: Path | None,
            emit_stage_completion: bool = True,
            terminal_error: str | None = None,
        ) -> LoopRunResult:
            nonlocal worktree_released
            final_result = _enrich_result(
                result,
                report_value=report_value,
                continuation_prompt_value=continuation_prompt_value,
                terminal_error=terminal_error,
            )

            if emit_stage_hooks and emit_stage_completion:
                try:
                    hook_controller.emit_stage_complete(
                        source="loop_runner",
                        stage_name=request.agent_role,
                        agent_role=request.agent_role,
                        session_id=session_id,
                        run_id=lifecycle.run_id,
                        payload={
                            "status": result.status,
                            "attempts_completed": result.attempts_completed,
                            "retries_used": result.retries_used,
                            "supervisor_verdict": result.supervisor_verdict,
                        },
                    )
                except RuntimeHookBlocked as exc:
                    next_action = f"Stage completion hook blocked loop exit: {exc}"
                    terminal_error = str(exc)
                    self._persist_loop_state(
                        status="blocked",
                        request=request,
                        attempts_completed=attempts_completed_value,
                        retries_used=retries_used_value,
                        latest_run_id=latest_run_id_value,
                        report=report_value,
                        report_path=result.report_path,
                        continuation_prompt_path=continuation_prompt_value,
                        next_action=next_action,
                    )
                    final_result = _blocked_result(
                        attempts_completed_value=attempts_completed_value,
                        retries_used_value=retries_used_value,
                        latest_run_id_value=latest_run_id_value,
                        report_value=report_value,
                        continuation_prompt_value=continuation_prompt_value,
                    )

            if emit_stage_completion:
                event_type = (
                    LifecycleEventType.STAGE_COMPLETED
                    if final_result.status == "completed"
                    else LifecycleEventType.STAGE_FAILED
                )
                lifecycle.emit(
                    event_type=event_type,
                    role=request.agent_role,
                    stage=request.agent_role,
                    status=final_result.status,
                    payload=StageEventPayload(
                        attempt=attempts_completed_value,
                        verdict=final_result.supervisor_verdict,
                        reason=report_value.summary if report_value is not None else None,
                        error=terminal_error
                        or (
                            report_value.summary
                            if report_value is not None and final_result.status != "completed"
                            else None
                        ),
                    ),
                )

            if active_worktree is not None and not worktree_released:
                lifecycle.emit(
                    event_type=LifecycleEventType.WORKTREE_RELEASED,
                    role=request.agent_role,
                    stage=request.agent_role,
                    status="released",
                    payload=WorktreeEventPayload(
                        worktree_id=active_worktree.worktree_id,
                        source_repo_root=str(active_worktree.source_repo_root),
                        isolated_path=str(active_worktree.isolated_path),
                        owner_role=active_worktree.owner.agent_role,
                        owner_run_id=active_worktree.owner.run_id,
                    ),
                    metadata={"result_status": final_result.status},
                )
                worktree_released = True

            if manage_session_lifecycle:
                try:
                    hook_controller.emit_session_end(
                        source="loop_runner",
                        session_id=session_id,
                        run_id=lifecycle.run_id,
                        agent_role=request.agent_role,
                        result=final_result.to_dict(),
                    )
                except RuntimeHookBlocked as exc:
                    next_action = f"Session-end hook blocked loop exit: {exc}"
                    terminal_error = str(exc)
                    self._persist_loop_state(
                        status="blocked",
                        request=request,
                        attempts_completed=attempts_completed_value,
                        retries_used=retries_used_value,
                        latest_run_id=latest_run_id_value,
                        report=report_value,
                        report_path=final_result.report_path,
                        continuation_prompt_path=continuation_prompt_value,
                        next_action=next_action,
                    )
                    final_result = _blocked_result(
                        attempts_completed_value=attempts_completed_value,
                        retries_used_value=retries_used_value,
                        latest_run_id_value=latest_run_id_value,
                        report_value=report_value,
                        continuation_prompt_value=continuation_prompt_value,
                    )

            run_error = terminal_error
            if run_error is None and report_value is not None and final_result.status != "completed":
                run_error = report_value.summary
            lifecycle.emit(
                event_type=LifecycleEventType.RUN_FINISHED,
                role=request.agent_role,
                stage=request.agent_role,
                status=final_result.status,
                payload=RunEventPayload(
                    source="loop_runner",
                    entrypoint="LoopRunner.run",
                    attempts_completed=attempts_completed_value,
                    retries_used=retries_used_value,
                    supervisor_verdict=final_result.supervisor_verdict,
                    outcome=final_result.status,
                    error=run_error,
                ),
            )
            return final_result

        worktree_create_allowed = (
            profile.worktree_policy.evaluate("create") is PermissionDecision.ALLOW
        )
        worktree_reuse_allowed = (
            profile.worktree_policy.evaluate("reuse") is PermissionDecision.ALLOW
        )
        if request.agent_role == "developer" and self.config.worktree.enabled:
            lifecycle.emit(
                event_type=LifecycleEventType.PERMISSION_GATE,
                role=request.agent_role,
                stage=request.agent_role,
                status=(
                    "approved"
                    if (worktree_create_allowed or worktree_reuse_allowed)
                    else "blocked"
                ),
                payload=PermissionGatePayload(
                    gate_name="managed_worktree",
                    decision=(
                        "approved"
                        if (worktree_create_allowed or worktree_reuse_allowed)
                        else "blocked"
                    ),
                    reason=(
                        "Agent profile allows managed worktree isolation."
                        if (worktree_create_allowed or worktree_reuse_allowed)
                        else "Agent profile denied managed worktree create/reuse actions."
                    ),
                    requested_action="create_or_reuse",
                ),
            )

        if self._managed_worktree_requested(request=request, profile=profile):
            try:
                active_worktree = self._prepare_managed_worktree(
                    request=request,
                    profile=profile,
                    repository=runtime_repository,
                    session_id=session_id,
                )
            except WorktreeServiceError as exc:
                next_action = f"Managed worktree setup failed: {exc}"
                self._persist_loop_state(
                    status="blocked",
                    request=request,
                    attempts_completed=attempt_number - 1,
                    retries_used=retries_used,
                    latest_run_id=None,
                    report=None,
                    report_path=None,
                    continuation_prompt_path=None,
                    next_action=next_action,
                )
                return _finish(
                    _blocked_result(
                        attempts_completed_value=attempt_number - 1,
                        retries_used_value=retries_used,
                        latest_run_id_value=None,
                        report_value=None,
                        continuation_prompt_value=None,
                    ),
                    attempts_completed_value=attempt_number - 1,
                    retries_used_value=retries_used,
                    latest_run_id_value=None,
                    report_value=None,
                    continuation_prompt_value=None,
                    emit_stage_completion=False,
                )
            if active_worktree is not None:
                runtime_config = self.config.with_overrides(
                    repo_root=active_worktree.isolated_path,
                    dev_dir=runtime_repository.dev_dir,
                    logs_dir=runtime_repository.logs_dir,
                )
                runtime_adapter = CliAdapter(
                    runtime_config,
                    live_output_stream=self.progress_stream,
                )
                runtime_supervisor = Supervisor(
                    runtime_config,
                    repository=runtime_repository,
                )
                lifecycle.emit(
                    event_type=LifecycleEventType.WORKTREE_PREPARED,
                    role=request.agent_role,
                    stage=request.agent_role,
                    status="prepared",
                    payload=WorktreeEventPayload(
                        worktree_id=active_worktree.worktree_id,
                        source_repo_root=str(active_worktree.source_repo_root),
                        isolated_path=str(active_worktree.isolated_path),
                        owner_role=active_worktree.owner.agent_role,
                        owner_run_id=active_worktree.owner.run_id,
                    ),
                )

        if emit_prompt_intake:
            try:
                hook_controller.emit_prompt_intake(
                    prompt_text=current_prompt,
                    source="loop_runner",
                    entrypoint="LoopRunner.run",
                    session_id=session_id,
                    run_id=lifecycle.run_id,
                    agent_role=request.agent_role,
                )
            except RuntimeHookBlocked as exc:
                next_action = f"Prompt intake hook blocked execution: {exc}"
                self._persist_loop_state(
                    status="blocked",
                    request=request,
                    attempts_completed=attempt_number - 1,
                    retries_used=retries_used,
                    latest_run_id=None,
                    report=None,
                    report_path=None,
                    continuation_prompt_path=None,
                    next_action=next_action,
                )
                return _finish(
                    _blocked_result(
                        attempts_completed_value=attempt_number - 1,
                        retries_used_value=retries_used,
                        latest_run_id_value=None,
                        report_value=None,
                        continuation_prompt_value=None,
                    ),
                    attempts_completed_value=attempt_number - 1,
                    retries_used_value=retries_used,
                    latest_run_id_value=None,
                    report_value=None,
                    continuation_prompt_value=None,
                    emit_stage_completion=False,
                    terminal_error=str(exc),
                )

        lifecycle.emit(
            event_type=LifecycleEventType.STAGE_QUEUED,
            role=request.agent_role,
            stage=request.agent_role,
            status="queued",
            payload=StageEventPayload(
                attempt=start_attempt,
                reason="Loop runner accepted the stage for supervised execution.",
            ),
        )
        lifecycle.emit(
            event_type=LifecycleEventType.RUN_STARTED,
            role=request.agent_role,
            stage=request.agent_role,
            status="started",
            payload=RunEventPayload(
                source="loop_runner",
                entrypoint="LoopRunner.run",
                trigger="supervised_loop",
            ),
        )

        if emit_stage_hooks:
            try:
                hook_controller.emit_stage_start(
                    source="loop_runner",
                    stage_name=request.agent_role,
                    agent_role=request.agent_role,
                    session_id=session_id,
                    run_id=lifecycle.run_id,
                    payload={
                        "run_label": request.run_label,
                        "start_attempt": start_attempt,
                    },
                    metadata={"runtime_skills": runtime_skill_summary(runtime_skill_state.get("latest"))},
                )
            except RuntimeHookBlocked as exc:
                next_action = f"Stage start hook blocked execution: {exc}"
                self._persist_loop_state(
                    status="blocked",
                    request=request,
                    attempts_completed=attempt_number - 1,
                    retries_used=retries_used,
                    latest_run_id=None,
                    report=None,
                    report_path=None,
                    continuation_prompt_path=None,
                    next_action=next_action,
                )
                return _finish(
                    _blocked_result(
                        attempts_completed_value=attempt_number - 1,
                        retries_used_value=retries_used,
                        latest_run_id_value=None,
                        report_value=None,
                        continuation_prompt_value=None,
                    ),
                    attempts_completed_value=attempt_number - 1,
                    retries_used_value=retries_used,
                    latest_run_id_value=None,
                    report_value=None,
                    continuation_prompt_value=None,
                    emit_stage_completion=False,
                    terminal_error=str(exc),
                )
        lifecycle.emit(
            event_type=LifecycleEventType.STAGE_STARTED,
            role=request.agent_role,
            stage=request.agent_role,
            status="started",
            payload=StageEventPayload(
                attempt=start_attempt,
                reason="Stage start hooks completed and agent execution can begin.",
            ),
            metadata={"runtime_skills": runtime_skill_summary(runtime_skill_state.get("latest"))},
        )

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
            agent_request = (
                AgentRunRequest(
                    cli_path=request.cli_path,
                    prompt_text=current_prompt,
                    repo_root=active_worktree.isolated_path,
                    workdir=self._isolated_workdir(
                        request=request,
                        worktree=active_worktree,
                    ),
                    input_mode=request.input_mode,
                    prompt_flag=request.prompt_flag,
                    extra_args=request.extra_args,
                    run_label=request.run_label,
                )
                if active_worktree is not None
                else request.as_agent_run_request(current_prompt)
            )
            self._emit_loop_snapshot(
                repository=runtime_repository,
                request=request,
                profile=profile,
                runtime_skill_state=runtime_skill_state,
                attempt_number=attempt_number,
                retries_used=retries_used,
            )

            def _handle_started(started: Any) -> None:
                runtime_repository.record_current_run(started)
                self._emit_command_started(started)
                lifecycle.emit(
                    event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                    role=request.agent_role,
                    stage=request.agent_role,
                    status="persisted",
                    payload=ArtifactPersistedPayload(
                        artifact_kind="agent_run_artifacts",
                        summary="Persisted prompt/stdout/stderr/metadata artifact references for the active agent run.",
                    ),
                    artifact_refs=(
                        ArtifactRef.from_path(kind="prompt", path=started.prompt_path, label="prompt"),
                        ArtifactRef.from_path(kind="stdout", path=started.stdout_path, label="stdout"),
                        ArtifactRef.from_path(kind="stderr", path=started.stderr_path, label="stderr"),
                        ArtifactRef.from_path(kind="metadata", path=started.metadata_path, label="metadata"),
                    ),
                    metadata={"agent_run_id": started.run_id},
                )
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
                agent_request,
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
                return _finish(
                    LoopRunResult(
                        status="completed",
                        attempts_completed=attempt_number,
                        retries_used=retries_used,
                        max_retries=request.max_retries,
                        max_iterations=request.max_iterations,
                        latest_run_id=result.run_id,
                        supervisor_verdict="promise_complete",
                        report_path=report_path,
                        continuation_prompt_path=continuation_prompt_path,
                    ),
                    attempts_completed_value=attempt_number,
                    retries_used_value=retries_used,
                    latest_run_id_value=result.run_id,
                    report_value=None,
                    continuation_prompt_value=continuation_prompt_path,
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
                return _finish(
                    _blocked_result(
                        attempts_completed_value=attempt_number,
                        retries_used_value=retries_used,
                        latest_run_id_value=result.run_id,
                        report_value=None,
                        continuation_prompt_value=continuation_prompt_path,
                    ),
                    attempts_completed_value=attempt_number,
                    retries_used_value=retries_used,
                    latest_run_id_value=result.run_id,
                    report_value=None,
                    continuation_prompt_value=continuation_prompt_path,
                )

            report = runtime_supervisor.validate(
                SupervisorRequest(
                    required_paths=request.required_paths,
                    require_worktree_changes=request.require_worktree_changes,
                    expected_roadmap_phase_id=request.expected_roadmap_phase_id,
                )
            )
            report_path = runtime_repository.write_supervisor_report(report.to_markdown())
            lifecycle.emit(
                event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                role=request.agent_role,
                stage=request.agent_role,
                status="persisted",
                payload=ArtifactPersistedPayload(
                    artifact_kind="supervisor_report",
                    summary="Persisted the latest supervisor verification report.",
                ),
                artifact_refs=(
                    ArtifactRef.from_path(
                        kind="supervisor_report",
                        path=report_path,
                        label="supervisor_report",
                        content_type="text/markdown",
                    ),
                ),
            )
            report = report.with_report_path(report_path)
            self._emit_supervisor_result(report, attempt_number=attempt_number)
            try:
                hook_controller.emit_final_verification(
                    source="loop_runner",
                    session_id=session_id,
                    run_id=lifecycle.run_id,
                    agent_role=request.agent_role,
                    attempt_number=attempt_number,
                    report=report.to_dict(),
                )
            except RuntimeHookBlocked as exc:
                next_action = f"Final verification hook blocked completion: {exc}"
                self._persist_loop_state(
                    status="blocked",
                    request=request,
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    latest_run_id=result.run_id,
                    report=report,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                    next_action=next_action,
                )
                return _finish(
                    _blocked_result(
                        attempts_completed_value=attempt_number,
                        retries_used_value=retries_used,
                        latest_run_id_value=result.run_id,
                        report_value=report,
                        continuation_prompt_value=continuation_prompt_path,
                    ),
                    attempts_completed_value=attempt_number,
                    retries_used_value=retries_used,
                    latest_run_id_value=result.run_id,
                    report_value=report,
                    continuation_prompt_value=continuation_prompt_path,
                )

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
                return _finish(
                    LoopRunResult(
                        status="completed",
                        attempts_completed=attempt_number,
                        retries_used=retries_used,
                        max_retries=request.max_retries,
                        max_iterations=request.max_iterations,
                        latest_run_id=result.run_id,
                        supervisor_verdict=report.verdict,
                        report_path=report_path,
                        continuation_prompt_path=continuation_prompt_path,
                    ),
                    attempts_completed_value=attempt_number,
                    retries_used_value=retries_used,
                    latest_run_id_value=result.run_id,
                    report_value=report,
                    continuation_prompt_value=continuation_prompt_path,
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
                final_result = LoopRunResult(
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
                return _finish(
                    final_result,
                    attempts_completed_value=attempt_number,
                    retries_used_value=retries_used,
                    latest_run_id_value=result.run_id,
                    report_value=report,
                    continuation_prompt_value=continuation_prompt_path,
                )

            task_sync_now = runtime_repository.read_session_state().get("task_sync", {})
            next_task = task_sync_now.get("next_pending_task")
            workflow_state = runtime_repository.read_workflow_state()

            # ── Stagnation detection ──────────────────────────────────────────
            _pending_now = int(task_sync_now.get("pending_tasks", 0) or 0)
            stagnation.record(_pending_now, next_task)
            if stagnation.is_stagnant(_pending_now):
                stagnation_msg = (
                    f"Loop stagnated: the same {_pending_now} pending task(s) "
                    f"persisted unchanged across {stagnation._window_size} consecutive "
                    "iterations with no forward progress. "
                    "Verify that the agent can write to PLAN.md and TASKS.md, "
                    "or increase the task scope before resuming."
                )
                self._write_progress([
                    "=== dormammu stagnation ===",
                    stagnation_msg,
                ])
                self._persist_loop_state(
                    status="blocked",
                    request=request,
                    attempts_completed=attempt_number,
                    retries_used=retries_used,
                    latest_run_id=result.run_id,
                    report=report,
                    report_path=report_path,
                    continuation_prompt_path=continuation_prompt_path,
                    next_action=stagnation_msg,
                )
                return _finish(
                    _blocked_result(
                        attempts_completed_value=attempt_number,
                        retries_used_value=retries_used,
                        latest_run_id_value=result.run_id,
                        report_value=report,
                        continuation_prompt_value=continuation_prompt_path,
                    ),
                    attempts_completed_value=attempt_number,
                    retries_used_value=retries_used,
                    latest_run_id_value=result.run_id,
                    report_value=report,
                    continuation_prompt_value=continuation_prompt_path,
                )

            continuation = build_continuation_prompt(
                latest_run=workflow_state["latest_run"],
                report=report,
                next_task=next_task,
                original_prompt_text=request.prompt_text,
                repo_guidance=workflow_state.get("bootstrap", {}).get("repo_guidance"),
                runtime_skills=(
                    workflow_state.get("runtime_skills", {}).get("latest")
                    if isinstance(workflow_state.get("runtime_skills"), dict)
                    else None
                ),
                runtime_paths_text=self.config.runtime_path_prompt(),
                patterns_text=runtime_repository.read_patterns_text(),
                templates_dir=self.config.templates_dir,
            )
            continuation_prompt_path = runtime_repository.write_continuation_prompt(continuation.text)
            lifecycle.emit(
                event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                role=request.agent_role,
                stage=request.agent_role,
                status="persisted",
                payload=ArtifactPersistedPayload(
                    artifact_kind="continuation_prompt",
                    summary="Persisted the continuation prompt for the next retry.",
                ),
                artifact_refs=(
                    ArtifactRef.from_path(
                        kind="continuation_prompt",
                        path=continuation_prompt_path,
                        label="continuation_prompt",
                        content_type="text/plain",
                    ),
                ),
            )

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
                final_result = LoopRunResult(
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
                return _finish(
                    final_result,
                    attempts_completed_value=attempt_number,
                    retries_used_value=retries_used,
                    latest_run_id_value=result.run_id,
                    report_value=report,
                    continuation_prompt_value=continuation_prompt_path,
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
            lifecycle.emit(
                event_type=LifecycleEventType.STAGE_RETRIED,
                role=request.agent_role,
                stage=request.agent_role,
                status="retried",
                payload=StageEventPayload(
                    attempt=attempt_number,
                    next_attempt=attempt_number + 1,
                    reason=next_action,
                ),
            )
            lifecycle.emit(
                event_type=LifecycleEventType.SUPERVISOR_HANDOFF,
                role="supervisor",
                stage=request.agent_role,
                status="handoff",
                payload=SupervisorHandoffPayload(
                    from_role="supervisor",
                    to_role=request.agent_role,
                    reason=next_action,
                    attempt=attempt_number + 1,
                ),
                artifact_refs=(
                    ArtifactRef.from_path(
                        kind="continuation_prompt",
                        path=continuation_prompt_path,
                        label="continuation_prompt",
                        content_type="text/plain",
                    ),
                ),
            )
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
        profile: AgentProfile,
        runtime_skill_state: Mapping[str, Any] | None,
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
            f"agent role: {request.agent_role}",
            f"agent profile: {profile.name} ({profile.source})",
            f"cli: {request.cli_path}",
            f"workdir: {(request.workdir or request.repo_root).resolve()}",
        ]
        skill_summary = runtime_skill_summary(
            runtime_skill_state.get("latest")
            if isinstance(runtime_skill_state, Mapping)
            else None
        )
        if skill_summary.get("interesting_for_operator"):
            lines.append(
                "runtime skills: "
                f"visible={skill_summary.get('visible_count', 0)} "
                f"custom={skill_summary.get('custom_visible_count', 0)} "
                f"hidden={skill_summary.get('hidden_count', 0)} "
                f"preloaded={skill_summary.get('preloaded_count', 0)} "
                f"missing_preloads={skill_summary.get('missing_preload_count', 0)} "
                f"shadowed={skill_summary.get('shadowed_count', 0)}"
            )
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
        # Hard ceiling enforced even for the "infinite" (-1) sentinel so that a
        # misconfigured loop cannot spin indefinitely.  retries_used equals
        # (total_attempts - 1), so this fires after _HARD_ITERATION_CAP runs.
        # Ralph pattern: always bound your loop — the -1 flag is a convenience,
        # not a promise of unlimited execution.
        if max_retries == -1 and retries_used >= _HARD_ITERATION_CAP - 1:
            return False
        if max_retries == -1:
            return True
        return retries_used < max_retries

    # The promise token must appear on its own line (optionally surrounded by
    # whitespace) so that occurrences inside quoted prompt text — which the
    # agent echoes back — are not mistakenly treated as self-completion signals.
    _PROMISE_COMPLETE_RE = re.compile(
        r"^\s*<promise>COMPLETE</promise>\s*$", re.MULTILINE
    )

    @staticmethod
    def _stdout_has_promise_complete(stdout_path: Path) -> bool:
        """Return True if the agent stdout contains the self-completion signal.

        The signal must appear as a standalone line so that agents that echo
        their prompt back (which may include the token in guidance text) do not
        trigger a false positive.
        """
        if not stdout_path.exists():
            return False
        try:
            content = stdout_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return bool(LoopRunner._PROMISE_COMPLETE_RE.search(content))

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
