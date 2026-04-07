from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse


router = APIRouter(tags=["ui"])


def _index_path(request: Request) -> Path:
    return request.app.state.config.frontend_dir / "index.html"


@router.get("/", include_in_schema=False)
def show_root_ui(request: Request) -> FileResponse:
    target = _index_path(request)
    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="UI assets are missing.")
    return FileResponse(target)


@router.get("/ui", include_in_schema=False)
def show_named_ui(request: Request) -> FileResponse:
    target = _index_path(request)
    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="UI assets are missing.")
    return FileResponse(target)
