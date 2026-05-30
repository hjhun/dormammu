import asyncio
from pathlib import Path
from typing import Any

from dormammu.config import AppConfig
from dormammu.web.auth import credential_matches, hash_password, request_token
from dormammu.web.settings import apply_settings_patch, read_settings, set_web_password_hash, write_raw_settings
from dormammu.web.telegram_service import TelegramConversationService
from dormammu.web.terminal import TerminalAccessError, TerminalSessionManager


def create_app(config: AppConfig, *, token: str | None = None):
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - exercised by CLI import guard
        raise ImportError("FastAPI is required for dormammu web") from exc

    app = FastAPI(title="Dormammu Web", version="1.0")
    state: dict[str, Any] = {"config": config}
    terminal_manager = TerminalSessionManager(allowed_roots=config.web_config.allowed_roots)
    telegram_service = TelegramConversationService(config)

    def _require_http_auth(
        authorization: str | None = Header(default=None),
        x_dormammu_token: str | None = Header(default=None),
    ) -> None:
        supplied = request_token(
            {
                "authorization": authorization or "",
                "x-dormammu-token": x_dormammu_token or "",
            }
        )
        if not credential_matches(
            token=token,
            password_hash=state["config"].web_config.password_hash,
            supplied=supplied,
        ):
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/api/health")
    def health() -> dict[str, object]:
        current = state["config"]
        return {
            "ok": True,
            "repo_root": str(current.repo_root),
            "allowed_roots": [str(path) for path in terminal_manager.allowed_roots],
        }

    @app.get("/api/auth/state")
    def auth_state() -> dict[str, object]:
        password_configured = bool(state["config"].web_config.password_hash)
        return {
            "password_configured": password_configured,
            "setup_required": not password_configured,
        }

    @app.post("/api/auth/setup")
    async def setup_password(request: Request) -> dict[str, object]:
        if state["config"].web_config.password_hash:
            raise HTTPException(status_code=409, detail="Password is already configured")
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Setup request must be an object")
        password = str(body.get("password") or "")
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        password_hash = hash_password(password)
        try:
            written = set_web_password_hash(state["config"], password_hash)
            state["config"] = AppConfig.load(repo_root=state["config"].repo_root)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "config_file": str(written)}

    @app.post("/api/auth/login")
    async def login(request: Request) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Login request must be an object")
        supplied = str(body.get("token") or "")
        if not credential_matches(
            token=token,
            password_hash=state["config"].web_config.password_hash,
            supplied=supplied,
        ):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"ok": True}

    @app.get("/api/config")
    def get_config(
        scope: str = Query(default="project"),
        _: None = Depends(_require_http_auth),
    ) -> dict[str, object]:
        try:
            return read_settings(state["config"], scope=scope)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/config")
    async def patch_config(request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Config patch must be an object")
        scope = str(body.pop("scope", "project"))
        try:
            written = apply_settings_patch(state["config"], body, scope=scope)
            reloaded = AppConfig.load(repo_root=state["config"].repo_root)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state["config"] = reloaded
        terminal_manager.allowed_roots = reloaded.web_config.allowed_roots
        return {
            "config_file": str(written),
            "settings": read_settings(reloaded, scope=scope),
        }

    @app.patch("/api/config/raw")
    async def patch_raw_config(request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Raw config patch must be an object")
        scope = str(body.get("scope", "project"))
        raw_json = body.get("raw_json")
        if not isinstance(raw_json, str):
            raise HTTPException(status_code=400, detail="raw_json is required")
        try:
            written = write_raw_settings(state["config"], raw_json, scope=scope)
            reloaded = AppConfig.load(repo_root=state["config"].repo_root)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state["config"] = reloaded
        terminal_manager.allowed_roots = reloaded.web_config.allowed_roots
        return {
            "config_file": str(written),
            "settings": read_settings(reloaded, scope=scope),
        }

    @app.get("/api/terminal/sessions")
    def list_terminal_sessions(_: None = Depends(_require_http_auth)) -> dict[str, object]:
        return {
            "sessions": [snapshot.to_dict() for snapshot in terminal_manager.list_sessions()],
            "allowed_roots": [str(path) for path in terminal_manager.allowed_roots],
        }

    @app.post("/api/terminal/sessions")
    async def create_terminal_session(request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Session request must be an object")
        cwd = body.get("cwd") or str(state["config"].repo_root)
        try:
            snapshot = terminal_manager.create_session(
                cwd=str(cwd),
                cols=int(body.get("cols") or 120),
                rows=int(body.get("rows") or 32),
            )
        except TerminalAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"session": snapshot.to_dict()}

    @app.delete("/api/terminal/sessions/{session_id}")
    def delete_terminal_session(session_id: str, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        deleted = terminal_manager.delete(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"deleted": True}

    @app.post("/api/terminal/sessions/{session_id}/input")
    async def write_terminal_input(session_id: str, request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Terminal input request must be an object")
        raw_data = body.get("data")
        if raw_data is None:
            command = body.get("command")
            if not isinstance(command, str) or not command.strip():
                raise HTTPException(status_code=400, detail="command is required")
            raw_data = command if command.endswith("\n") else f"{command}\n"
        if not isinstance(raw_data, str) or raw_data == "":
            raise HTTPException(status_code=400, detail="data must be a non-empty string")
        try:
            session = terminal_manager.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found") from None
        session.write(raw_data)
        return {"written": True}

    @app.websocket("/api/terminal/sessions/{session_id}/ws")
    async def terminal_ws(session_id: str, websocket: WebSocket, token_query: str | None = Query(default=None, alias="token")) -> None:
        supplied = request_token(websocket.headers, query_token=token_query)
        if not credential_matches(
            token=token,
            password_hash=state["config"].web_config.password_hash,
            supplied=supplied,
        ):
            await websocket.close(code=1008)
            return
        try:
            session = terminal_manager.get(session_id)
        except KeyError:
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def sender() -> None:
            with session.subscribe() as output:
                while True:
                    chunk = await asyncio.to_thread(output.get)
                    if chunk is None:
                        await websocket.send_json({"type": "status", "running": session.running, "exit_code": session.exit_code})
                        break
                    await websocket.send_json({"type": "output", "data": chunk.decode("utf-8", errors="replace")})

        async def receiver() -> None:
            while True:
                message = await websocket.receive_json()
                message_type = message.get("type")
                if message_type == "input":
                    session.write(str(message.get("data") or ""))
                elif message_type == "resize":
                    session.resize(cols=int(message.get("cols") or 120), rows=int(message.get("rows") or 32))

        sender_task = asyncio.create_task(sender())
        receiver_task = asyncio.create_task(receiver())
        try:
            done, pending = await asyncio.wait(
                {sender_task, receiver_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            for task in (sender_task, receiver_task):
                task.cancel()

    @app.get("/api/telegram/sessions")
    def list_telegram_sessions(_: None = Depends(_require_http_auth)) -> dict[str, object]:
        return {"sessions": [item.to_dict() for item in telegram_service.list_sessions()]}

    @app.get("/api/telegram/sessions/{session_id}")
    def get_telegram_session(session_id: str, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        snapshot = telegram_service.load_session(session_id)
        return {
            "id": snapshot.session_id,
            "summary": snapshot.summary,
            "turns": [turn.to_dict() for turn in snapshot.turns],
            "compaction_count": snapshot.compaction_count,
        }

    @app.post("/api/telegram/sessions/{session_id}/messages")
    async def continue_telegram_session(session_id: str, request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("text"), str) or not body["text"].strip():
            raise HTTPException(status_code=400, detail="text is required")
        try:
            response = await asyncio.to_thread(telegram_service.continue_session, session_id, body["text"])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"response": response, "session": get_telegram_session(session_id)}

    static_dir = _frontend_dist_dir()
    if static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str = ""):
            target = static_dir / full_path
            if full_path and target.exists() and target.is_file():
                return FileResponse(target)
            return FileResponse(static_dir / "index.html")

    return app


def _frontend_dist_dir() -> Path:
    package_dist = Path(__file__).resolve().parent / "static"
    if package_dist.exists():
        return package_dist
    repo_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return repo_dist
