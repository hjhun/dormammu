from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from dormammu.config import AppConfig
from dormammu.loop_runner import LoopRunRequest, LoopRunner
from dormammu.recovery import RecoveryManager
from dormammu.state import StateRepository


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class RunStartPayload(BaseModel):
    agent_cli: str
    prompt: str
    workdir: str | None = None
    input_mode: str = "auto"
    prompt_flag: str | None = None
    extra_args: list[str] = Field(default_factory=list)
    run_label: str | None = None
    max_retries: int = 0
    required_paths: list[str] = Field(default_factory=list)
    require_worktree_changes: bool = False
    expected_roadmap_phase_id: str | None = None


class ResumePayload(BaseModel):
    max_retries: int | None = None


@dataclass
class RunController:
    config: AppConfig
    repository: StateRepository

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._job: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._job is None:
                return {"status": "idle"}
            return dict(self._job)

    def start_run(self, payload: RunStartPayload) -> dict[str, Any]:
        with self._lock:
            self._assert_available()
            job_id = f"ui-run-{datetime.now(timezone.utc).astimezone().strftime('%Y%m%d-%H%M%S')}"
            phase_id = payload.expected_roadmap_phase_id or self._current_roadmap_phase_id()
            loop_request = LoopRunRequest(
                cli_path=Path(payload.agent_cli),
                prompt_text=payload.prompt,
                repo_root=self.config.repo_root,
                workdir=Path(payload.workdir) if payload.workdir else None,
                input_mode=payload.input_mode,
                prompt_flag=payload.prompt_flag,
                extra_args=tuple(payload.extra_args),
                run_label=payload.run_label or "ui-run",
                max_retries=payload.max_retries,
                required_paths=tuple(payload.required_paths),
                require_worktree_changes=payload.require_worktree_changes,
                expected_roadmap_phase_id=phase_id,
            )
            self._job = {
                "job_id": job_id,
                "kind": "start",
                "status": "accepted",
                "submitted_at": _iso_now(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "result": None,
                "request": {
                    "agent_cli": str(loop_request.cli_path),
                    "workdir": str(loop_request.workdir) if loop_request.workdir else None,
                    "input_mode": loop_request.input_mode,
                    "run_label": loop_request.run_label,
                    "max_retries": loop_request.max_retries,
                    "required_paths": list(loop_request.required_paths),
                    "require_worktree_changes": loop_request.require_worktree_changes,
                    "expected_roadmap_phase_id": loop_request.expected_roadmap_phase_id,
                    "prompt_preview": loop_request.prompt_text[:160],
                },
            }
            thread = Thread(
                target=self._run_loop_request,
                args=(job_id, loop_request),
                daemon=True,
            )
            self._job["thread_name"] = thread.name
            thread.start()
            return dict(self._job)

    def resume_run(self, payload: ResumePayload) -> dict[str, Any]:
        with self._lock:
            self._assert_available()
            job_id = f"ui-resume-{datetime.now(timezone.utc).astimezone().strftime('%Y%m%d-%H%M%S')}"
            self._job = {
                "job_id": job_id,
                "kind": "resume",
                "status": "accepted",
                "submitted_at": _iso_now(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "result": None,
                "request": {
                    "max_retries": payload.max_retries,
                },
            }
            thread = Thread(
                target=self._resume_loop_request,
                args=(job_id, payload.max_retries),
                daemon=True,
            )
            self._job["thread_name"] = thread.name
            thread.start()
            return dict(self._job)

    def _current_roadmap_phase_id(self) -> str | None:
        workflow_state = self.repository.read_workflow_state()
        active_phase_ids = workflow_state.get("roadmap", {}).get("active_phase_ids", [])
        if active_phase_ids:
            return str(active_phase_ids[0])
        session_state = self.repository.read_session_state()
        session_phase_ids = session_state.get("active_roadmap_phase_ids", [])
        if session_phase_ids:
            return str(session_phase_ids[0])
        return None

    def _assert_available(self) -> None:
        if self._job is not None and self._job.get("status") in {"accepted", "running"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A UI-managed run is already in progress.",
            )

    def _run_loop_request(self, job_id: str, request: LoopRunRequest) -> None:
        self._mark_running(job_id)
        try:
            result = LoopRunner(self.config, repository=self.repository).run(request)
        except (RuntimeError, ValueError, OSError) as exc:
            self._mark_failed(job_id, str(exc))
            return
        self._mark_completed(job_id, result.to_dict())

    def _resume_loop_request(self, job_id: str, max_retries: int | None) -> None:
        self._mark_running(job_id)
        try:
            result = RecoveryManager(self.config, repository=self.repository).resume(
                max_retries_override=max_retries
            )
        except (RuntimeError, ValueError, OSError) as exc:
            self._mark_failed(job_id, str(exc))
            return
        self._mark_completed(job_id, result.to_dict())

    def _mark_running(self, job_id: str) -> None:
        with self._lock:
            if self._job is None or self._job.get("job_id") != job_id:
                return
            self._job["status"] = "running"
            self._job["started_at"] = _iso_now()

    def _mark_completed(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            if self._job is None or self._job.get("job_id") != job_id:
                return
            self._job["status"] = "completed"
            self._job["finished_at"] = _iso_now()
            self._job["result"] = result

    def _mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            if self._job is None or self._job.get("job_id") != job_id:
                return
            self._job["status"] = "failed"
            self._job["finished_at"] = _iso_now()
            self._job["error"] = error


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/setup")
def get_run_setup(request: Request) -> dict[str, Any]:
    repository: StateRepository = request.app.state.state_repository
    workflow_state = repository.read_workflow_state()
    active_phase_ids = workflow_state.get("roadmap", {}).get("active_phase_ids", [])
    return {
        "repo_root": str(request.app.state.config.repo_root),
        "workdir": str(request.app.state.config.repo_root),
        "input_modes": ["auto", "file", "arg", "stdin", "positional"],
        "default_input_mode": "auto",
        "default_max_retries": 0,
        "default_expected_roadmap_phase_id": active_phase_ids[0] if active_phase_ids else None,
        "active_job": request.app.state.run_controller.snapshot(),
    }


@router.get("/active")
def get_active_run(request: Request) -> dict[str, Any]:
    return request.app.state.run_controller.snapshot()


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
def start_run(payload: RunStartPayload, request: Request) -> dict[str, Any]:
    return request.app.state.run_controller.start_run(payload)


@router.post("/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_run(payload: ResumePayload, request: Request) -> dict[str, Any]:
    return request.app.state.run_controller.resume_run(payload)
