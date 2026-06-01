import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config
from dormammu.operator_services import DaemonOperatorService, GoalsOperatorService, default_daemon_config_path
from dormammu.web.auth import credential_matches, hash_password, request_token
from dormammu.web.settings import apply_settings_patch, read_settings, set_web_password_hash, write_raw_settings
from dormammu.web.telegram_service import TelegramConversationService
from dormammu.web.terminal import (
    TerminalAccessError,
    TerminalRuntimeError,
    TerminalSessionManager,
    build_dormammu_terminal_command,
)


def create_app(config: AppConfig, *, token: str | None = None):
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - exercised by CLI import guard
        raise ImportError("FastAPI is required for dormammu web") from exc

    app = FastAPI(title="Dormammu Web", version="1.0")
    state: dict[str, Any] = {"config": config}
    terminal_manager = TerminalSessionManager(
        allowed_roots=config.web_config.allowed_roots,
        state_dir=config.global_home_dir / "web",
        repo_root=config.repo_root,
    )
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
        terminal_manager.repo_root = reloaded.repo_root
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
        terminal_manager.repo_root = reloaded.repo_root
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
                source="web",
                repo_root=state["config"].repo_root,
            )
        except (TerminalAccessError, TerminalRuntimeError) as exc:
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
        command = body.get("command")
        if isinstance(command, str):
            terminal_manager.record_command(session_id, command)
        return {"written": True}

    @app.post("/api/terminal/sessions/{session_id}/dormammu")
    async def run_dormammu_in_terminal(session_id: str, request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Dormammu run request must be an object")
        mode = str(body.get("mode") or "run")
        try:
            session = terminal_manager.get(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found") from None

        repo_root = Path(str(body.get("repo_root") or state["config"].repo_root)).expanduser().resolve()
        if not any(repo_root == root or repo_root.is_relative_to(root) for root in terminal_manager.allowed_roots):
            raise HTTPException(status_code=400, detail="repo_root is outside allowed roots")

        try:
            command = build_dormammu_terminal_command(
                mode=mode,
                repo_root=repo_root,
                prompt=str(body.get("prompt") or ""),
                prompt_file=body.get("prompt_file") if isinstance(body.get("prompt_file"), str) else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session.write(f"{command}\n")
        terminal_manager.record_command(session_id, command)
        return {"written": True, "command": command}

    @app.get("/api/daemon/status")
    def daemon_status(_: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            service = _daemon_service(state["config"])
            return _daemon_status_payload(service)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/daemon/start")
    def start_daemon(_: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            service = _daemon_service(state["config"])
            status = service.status()
            if status.pid_present:
                return {"started": False, "message": "daemon already appears to be running", "status": _daemon_status_payload(service)}
            log_path = service.base_dir() / "daemon.web.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_stream = log_path.open("a", encoding="utf-8")
            env = dict(os.environ)
            python_path = os.pathsep.join(path for path in sys.path if path)
            if python_path:
                env["PYTHONPATH"] = python_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            try:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        "from dormammu.cli import main; raise SystemExit(main())",
                        "daemonize",
                        "--repo-root",
                        str(state["config"].repo_root),
                        "--config",
                        str(status.config_path),
                    ],
                    stdout=log_stream,
                    stderr=log_stream,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    start_new_session=True,
                    close_fds=True,
                )
            finally:
                log_stream.close()
            return {"started": True, "pid": proc.pid, "log_path": str(log_path), "status": _daemon_status_payload(service)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/daemon/stop")
    def stop_daemon(_: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            pid = _daemon_service(state["config"]).request_stop()
            return {"stopped": True, "pid": pid}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/daemon/logs")
    def daemon_logs(max_lines: int = Query(default=80), _: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            tail = _daemon_service(state["config"]).latest_log_tail(max_lines=max(1, min(int(max_lines), 300)))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if tail is None:
            return {"path": None, "lines": []}
        return {"path": str(tail.path), "lines": list(tail.lines)}

    @app.post("/api/daemon/queue")
    async def enqueue_daemon_prompt(request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("text"), str) or not body["text"].strip():
            raise HTTPException(status_code=400, detail="text is required")
        try:
            path = _daemon_service(state["config"]).enqueue_prompt(body["text"], source="web")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"queued": True, "prompt": _file_payload(path, include_content=True)}

    @app.delete("/api/daemon/queue/{filename}")
    def delete_queued_prompt(filename: str, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            path = _safe_child(_daemon_service(state["config"]).load_config().prompt_path, filename)
            path.unlink(missing_ok=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted": True, "filename": filename}

    @app.get("/api/daemon/prompts")
    def list_daemon_prompts(_: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            daemon_config = _daemon_service(state["config"]).load_config()
            prompts = _list_markdown_files(daemon_config.prompt_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(daemon_config.prompt_path), "prompts": prompts}

    @app.get("/api/daemon/prompts/{filename}")
    def get_daemon_prompt(filename: str, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            path = _safe_child(_daemon_service(state["config"]).load_config().prompt_path, filename)
            return _file_payload(path, include_content=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/daemon/prompts/{filename}")
    async def put_daemon_prompt(filename: str, request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("content"), str) or not body["content"].strip():
            raise HTTPException(status_code=400, detail="content is required")
        try:
            path = _safe_child(_daemon_service(state["config"]).load_config().prompt_path, filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body["content"].rstrip() + "\n", encoding="utf-8")
            return {"saved": True, "prompt": _file_payload(path, include_content=True)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/daemon/prompts/{filename}")
    def delete_daemon_prompt(filename: str, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            path = _safe_child(_daemon_service(state["config"]).load_config().prompt_path, filename)
            path.unlink(missing_ok=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted": True, "filename": filename}

    @app.get("/api/daemon/goals")
    def list_daemon_goals(_: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            goals = _goals_service(state["config"])
            goals_path = goals.goals_path
            return {
                "path": str(goals_path) if goals_path is not None else None,
                "goals": [_file_payload(path) for path in goals.list_goals()],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/daemon/goals/{filename}")
    def get_daemon_goal(filename: str, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            goals = _goals_service(state["config"])
            if goals.goals_path is None:
                raise RuntimeError("Goals are not configured.")
            return _file_payload(_safe_child(goals.goals_path, filename), include_content=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/daemon/goals")
    async def create_daemon_goal(request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("content"), str):
            raise HTTPException(status_code=400, detail="content is required")
        try:
            path = _goals_service(state["config"]).save_goal(body["content"])
            return {"saved": True, "goal": _file_payload(path, include_content=True)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/daemon/goals/{filename}")
    async def put_daemon_goal(filename: str, request: Request, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("content"), str) or not body["content"].strip():
            raise HTTPException(status_code=400, detail="content is required")
        try:
            goals = _goals_service(state["config"])
            if goals.goals_path is None:
                raise RuntimeError("Goals are not configured.")
            path = _safe_child(goals.goals_path, filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body["content"].rstrip() + "\n", encoding="utf-8")
            return {"saved": True, "goal": _file_payload(path, include_content=True)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/daemon/goals/{filename}")
    def delete_daemon_goal(filename: str, _: None = Depends(_require_http_auth)) -> dict[str, object]:
        try:
            goals = _goals_service(state["config"])
            if goals.goals_path is None:
                raise RuntimeError("Goals are not configured.")
            goals.delete_goal(_safe_child(goals.goals_path, filename))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted": True, "filename": filename}

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
                    await websocket.send_json({"type": "snapshot", "data": chunk.decode("utf-8", errors="replace")})

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


def _daemon_service(config: AppConfig) -> DaemonOperatorService:
    return DaemonOperatorService(config, daemon_config_path=default_daemon_config_path(config))


def _goals_service(config: AppConfig) -> GoalsOperatorService:
    daemon_config = load_daemon_config(default_daemon_config_path(config), app_config=config)
    return GoalsOperatorService(daemon_config)


def _daemon_status_payload(service: DaemonOperatorService) -> dict[str, object]:
    status = service.status()
    queue = [_file_payload(path) for path in service.list_queue()]
    return {
        "config_path": str(status.config_path),
        "prompt_path": str(status.prompt_path),
        "result_path": str(status.result_path),
        "pid_path": str(status.pid_path),
        "heartbeat_path": str(status.heartbeat_path),
        "pid_present": status.pid_present,
        "heartbeat_present": status.heartbeat_present,
        "queue_depth": status.queue_depth,
        "heartbeat_payload": status.heartbeat_payload,
        "heartbeat_error": status.heartbeat_error,
        "queue": queue,
    }


def _safe_child(root: Path, filename: str) -> Path:
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise ValueError("filename must be a plain file name")
    if not filename.endswith(".md"):
        raise ValueError("filename must end with .md")
    root = root.expanduser().resolve()
    candidate = (root / filename).resolve()
    if candidate.parent != root:
        raise ValueError("filename is outside the configured directory")
    return candidate


def _list_markdown_files(root: Path) -> list[dict[str, object]]:
    if not root.exists():
        return []
    return [_file_payload(path) for path in sorted(root.iterdir()) if path.is_file() and path.suffix == ".md"]


def _file_payload(path: Path, *, include_content: bool = False) -> dict[str, object]:
    stat = path.stat()
    payload: dict[str, object] = {
        "filename": path.name,
        "path": str(path),
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }
    if include_content:
        payload["content"] = path.read_text(encoding="utf-8", errors="replace")
    return payload
