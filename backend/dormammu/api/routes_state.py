from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from dormammu.state import StateRepository


FILE_TARGETS = {
    "dashboard": ".dev/DASHBOARD.md",
    "tasks": ".dev/TASKS.md",
    "continuation": ".dev/continuation_prompt.txt",
    "supervisor_report": ".dev/supervisor_report.md",
}
RUN_ARTIFACT_TARGETS = {
    "prompt_artifact": "prompt",
    "stdout_artifact": "stdout",
    "stderr_artifact": "stderr",
    "metadata_artifact": "metadata",
}


router = APIRouter(prefix="/api/state", tags=["state"])


def _resolve_file_target(
    repository: StateRepository,
    session_state: dict[str, Any],
    workflow_state: dict[str, Any],
    name: str,
) -> Path | None:
    if name in RUN_ARTIFACT_TARGETS:
        active_run = _active_run_payload(session_state, workflow_state)
        artifact_value = None
        if active_run is not None:
            artifact_value = active_run.get("artifacts", {}).get(RUN_ARTIFACT_TARGETS[name])
        return Path(str(artifact_value)) if artifact_value else None
    if name == "continuation":
        configured = workflow_state.get("latest_continuation_prompt")
        if configured:
            return Path(configured)
    if name == "supervisor_report":
        configured = workflow_state.get("supervisor_report", {}).get("path")
        if configured:
            return Path(configured)
    if name not in FILE_TARGETS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown file target.")
    return repository.config.repo_root / FILE_TARGETS[name]


def _read_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _tail_lines(path: Path | None, *, lines: int) -> str:
    if path is None or not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    parts = content.splitlines()
    return "\n".join(parts[-lines:])


def _active_run_payload(session_state: dict[str, Any], workflow_state: dict[str, Any]) -> dict[str, Any] | None:
    current_run = workflow_state.get("current_run") or session_state.get("current_run")
    if isinstance(current_run, dict):
        return current_run
    latest_run = workflow_state.get("latest_run") or session_state.get("latest_run")
    if isinstance(latest_run, dict):
        return latest_run
    return None


def _log_payload(
    session_state: dict[str, Any],
    workflow_state: dict[str, Any],
    *,
    stream: str,
    lines: int,
) -> dict[str, Any]:
    active_run = _active_run_payload(session_state, workflow_state)
    artifact_path: Path | None = None
    if active_run is not None:
        artifact_value = active_run.get("artifacts", {}).get(stream)
        if artifact_value:
            artifact_path = Path(str(artifact_value))
    return {
        "stream": stream,
        "run_id": active_run.get("run_id") if active_run else None,
        "path": str(artifact_path) if artifact_path else None,
        "running": workflow_state.get("current_run") is not None,
        "content": _tail_lines(artifact_path, lines=lines),
    }


@router.get("/summary")
def get_state_summary(request: Request) -> dict[str, Any]:
    repository: StateRepository = request.app.state.state_repository
    session_state = repository.read_session_state()
    workflow_state = repository.read_workflow_state()
    file_status = {}
    for name in [*FILE_TARGETS, *RUN_ARTIFACT_TARGETS]:
        target = _resolve_file_target(repository, session_state, workflow_state, name)
        file_status[name] = {
            "path": str(target) if target else None,
            "exists": bool(target and target.exists()),
            "size": target.stat().st_size if target and target.exists() else 0,
        }
    return {
        "app": request.app.state.config.to_dict(),
        "session": {
            "active_phase": session_state.get("active_phase"),
            "active_roadmap_phase_ids": session_state.get("active_roadmap_phase_ids", []),
            "next_action": session_state.get("next_action"),
            "task_sync": session_state.get("task_sync"),
            "loop": session_state.get("loop", {}),
        },
        "workflow": {
            "active_phase": workflow_state.get("workflow", {}).get("active_phase"),
            "last_completed_phase": workflow_state.get("workflow", {}).get("last_completed_phase"),
            "resume_from_phase": workflow_state.get("workflow", {}).get("resume_from_phase"),
            "roadmap": workflow_state.get("roadmap", {}),
            "supervisor": workflow_state.get("supervisor", {}),
            "next_action": workflow_state.get("next_action"),
            "current_run": workflow_state.get("current_run"),
            "latest_run": workflow_state.get("latest_run"),
        },
        "ui_run": request.app.state.run_controller.snapshot(),
        "files": file_status,
    }


@router.get("/files/{name}")
def get_state_file(name: str, request: Request) -> dict[str, Any]:
    repository: StateRepository = request.app.state.state_repository
    session_state = repository.read_session_state()
    workflow_state = repository.read_workflow_state()
    target = _resolve_file_target(repository, session_state, workflow_state, name)
    return {
        "name": name,
        "path": str(target) if target else None,
        "exists": bool(target and target.exists()),
        "content": _read_text(target),
    }


@router.get("/logs/{stream}")
def get_log_tail(
    stream: str,
    request: Request,
    lines: int = Query(default=120, ge=1, le=1000),
) -> dict[str, Any]:
    if stream not in {"stdout", "stderr"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown log stream.")
    repository: StateRepository = request.app.state.state_repository
    session_state = repository.read_session_state()
    workflow_state = repository.read_workflow_state()
    return _log_payload(session_state, workflow_state, stream=stream, lines=lines)


@router.get("/logs/{stream}/stream")
async def stream_log_tail(
    stream: str,
    request: Request,
    lines: int = Query(default=120, ge=1, le=1000),
) -> StreamingResponse:
    if stream not in {"stdout", "stderr"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown log stream.")

    repository: StateRepository = request.app.state.state_repository

    async def events() -> Any:
        previous = None
        while True:
            if await request.is_disconnected():
                break
            session_state = repository.read_session_state()
            workflow_state = repository.read_workflow_state()
            payload = _log_payload(session_state, workflow_state, stream=stream, lines=lines)
            serialized = json.dumps(payload, ensure_ascii=True)
            if serialized != previous:
                previous = serialized
                yield f"data: {serialized}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")
