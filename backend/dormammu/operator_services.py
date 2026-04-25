from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import time
from typing import Any

from dormammu.config import AppConfig, set_config_value
from dormammu.daemon.config import load_daemon_config
from dormammu.daemon.models import DaemonConfig
from dormammu.daemon.queue import is_prompt_candidate, prompt_sort_key


def default_daemon_config_path(config: AppConfig) -> Path:
    return (config.home_dir / ".dormammu" / "daemonize.json").expanduser().resolve()


def nested_get(payload: dict[str, object], dotted_key: str) -> object | None:
    current: object = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


@dataclass(frozen=True, slots=True)
class DaemonStatusSnapshot:
    config_path: Path
    prompt_path: Path
    result_path: Path
    pid_path: Path
    heartbeat_path: Path
    pid_present: bool
    heartbeat_present: bool
    queue_depth: int
    heartbeat_payload: dict[str, Any] | None = None
    heartbeat_error: str | None = None


@dataclass(frozen=True, slots=True)
class LogTail:
    path: Path
    lines: tuple[str, ...]


class ConfigOperatorService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def resolved_config(self) -> dict[str, Any]:
        return self._config.to_dict()

    def get(self, dotted_key: str) -> object | None:
        return nested_get(self._config.to_dict(), dotted_key)

    def set_value(
        self,
        key: str,
        *,
        value: str | None = None,
        add: str | None = None,
        remove: str | None = None,
        unset: bool = False,
        global_scope: bool = False,
    ) -> Path:
        return set_config_value(
            self._config,
            key,
            value=value,
            add=add,
            remove=remove,
            unset=unset,
            global_scope=global_scope,
        )


class DaemonOperatorService:
    def __init__(
        self,
        app_config: AppConfig,
        *,
        daemon_config: DaemonConfig | None = None,
        daemon_config_path: Path | None = None,
    ) -> None:
        self._app_config = app_config
        self._daemon_config = daemon_config
        self._daemon_config_path = daemon_config_path

    def load_config(self) -> DaemonConfig:
        if self._daemon_config is not None:
            return self._daemon_config
        path = self._daemon_config_path or default_daemon_config_path(self._app_config)
        return load_daemon_config(path, app_config=self._app_config)

    def base_dir(self) -> Path:
        return self.load_config().result_path.parent

    def pid_path(self) -> Path:
        return self.base_dir() / "daemon.pid"

    def heartbeat_path(self) -> Path:
        return self.base_dir() / "daemon_heartbeat.json"

    def list_queue(self) -> tuple[Path, ...]:
        daemon_config = self.load_config()
        if not daemon_config.prompt_path.exists():
            return ()
        return tuple(
            sorted(
                (
                    path
                    for path in daemon_config.prompt_path.iterdir()
                    if is_prompt_candidate(path, daemon_config.queue)
                ),
                key=lambda item: prompt_sort_key(item.name),
            )
        )

    def status(self) -> DaemonStatusSnapshot:
        daemon_config = self.load_config()
        heartbeat_path = self.heartbeat_path()
        heartbeat_payload: dict[str, Any] | None = None
        heartbeat_error: str | None = None
        if heartbeat_path.exists():
            try:
                payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                heartbeat_error = str(exc)
            else:
                if isinstance(payload, dict):
                    heartbeat_payload = payload
                else:
                    heartbeat_error = "heartbeat payload is not an object"
        return DaemonStatusSnapshot(
            config_path=daemon_config.config_path,
            prompt_path=daemon_config.prompt_path,
            result_path=daemon_config.result_path,
            pid_path=self.pid_path(),
            heartbeat_path=heartbeat_path,
            pid_present=self.pid_path().exists(),
            heartbeat_present=heartbeat_path.exists(),
            queue_depth=len(self.list_queue()),
            heartbeat_payload=heartbeat_payload,
            heartbeat_error=heartbeat_error,
        )

    def enqueue_prompt(self, prompt: str, *, source: str = "operator") -> Path:
        daemon_config = self.load_config()
        daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
        stem = f"{source}-{os.getpid()}-{len(prompt)}-{int(time.time())}"
        prompt_path = daemon_config.prompt_path / f"{stem}.md"
        prompt_path.write_text(prompt.rstrip() + "\n", encoding="utf-8")
        return prompt_path

    def request_stop(self) -> int:
        pid_path = self.pid_path()
        if not pid_path.exists():
            raise RuntimeError("daemon is not running")
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"failed to read daemon pid: {exc}") from exc
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            raise RuntimeError(f"failed to stop daemon pid {pid}: {exc}") from exc
        return pid

    def latest_log_tail(self, *, max_lines: int = 40) -> LogTail | None:
        base = self.base_dir()
        progress_dir = base / "progress"
        candidates: list[Path] = []
        if progress_dir.exists():
            candidates.extend(sorted(progress_dir.glob("*.log"), key=lambda path: path.stat().st_mtime))
        daemon_log = base / "daemon.shell.log"
        if daemon_log.exists():
            candidates.append(daemon_log)
        if not candidates:
            return None
        target = candidates[-1]
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = tuple(lines[-max_lines:] if len(lines) > max_lines else lines)
        return LogTail(path=target, lines=tail)


class GoalsOperatorService:
    def __init__(self, daemon_config: DaemonConfig) -> None:
        self._daemon_config = daemon_config

    @property
    def goals_path(self) -> Path | None:
        goals_cfg = getattr(self._daemon_config, "goals", None)
        return goals_cfg.path if goals_cfg is not None else None

    def list_goals(self) -> tuple[Path, ...]:
        path = self.goals_path
        if path is None or not path.exists():
            return ()
        return tuple(sorted(p for p in path.iterdir() if p.is_file() and p.suffix == ".md"))

    def filename_for_content(self, text: str, *, date_str: str | None = None) -> str:
        first_line = text.splitlines()[0].strip()
        stem = re.sub(r"[^\w\s-]", "", first_line.lower())
        stem = re.sub(r"[\s_]+", "-", stem).strip("-") or "goal"
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"{date_str}_{stem}.md"

    def save_goal(self, text: str, *, date_str: str | None = None) -> Path:
        goals_path = self.goals_path
        if goals_path is None:
            raise RuntimeError("Goals are not configured.")
        content = text.strip()
        if not content:
            raise ValueError("Goal content cannot be empty.")
        filename = self.filename_for_content(content, date_str=date_str)
        dest = goals_path / filename
        goals_path.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest

    def delete_goal(self, goal_path: Path) -> None:
        goal_path.unlink(missing_ok=True)
