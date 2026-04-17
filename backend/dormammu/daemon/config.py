from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from dormammu.config import AppConfig
from dormammu.daemon.autonomous_config import AutonomousConfig, parse_autonomous_config
from dormammu.daemon.goals_config import GoalsConfig, parse_goals_config
from dormammu.daemon.models import DaemonConfig, QueueConfig, WatchConfig


def _resolve_path(value: str, *, base_dir: Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (base_dir / candidate).resolve()


def _require_mapping(value: Any, *, field_name: str, config_path: Path) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{field_name} must be a JSON object in {config_path}")
    return value


def _require_non_empty_string(value: Any, *, field_name: str, config_path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{field_name} must be a non-empty string in {config_path}")
    return value


def _parse_watch_config(value: Any, *, config_path: Path) -> WatchConfig:
    payload = _require_mapping(value or {}, field_name="watch", config_path=config_path)
    backend = str(payload.get("backend", "auto"))
    if backend not in {"auto", "inotify", "polling"}:
        raise RuntimeError(f"watch.backend must be one of auto, inotify, polling in {config_path}")
    poll_interval_seconds = int(payload.get("poll_interval_seconds", 60))
    settle_seconds = int(payload.get("settle_seconds", 2))
    if poll_interval_seconds < 1:
        raise RuntimeError(f"watch.poll_interval_seconds must be >= 1 in {config_path}")
    if settle_seconds < 0:
        raise RuntimeError(f"watch.settle_seconds must be >= 0 in {config_path}")
    return WatchConfig(
        backend=backend,
        poll_interval_seconds=poll_interval_seconds,
        settle_seconds=settle_seconds,
    )


def _parse_queue_config(value: Any, *, config_path: Path) -> QueueConfig:
    payload = _require_mapping(value or {}, field_name="queue", config_path=config_path)
    allowed_extensions = payload.get("allowed_extensions", [])
    if not isinstance(allowed_extensions, list) or any(not isinstance(item, str) for item in allowed_extensions):
        raise RuntimeError(f"queue.allowed_extensions must be a JSON array of strings in {config_path}")
    normalized = tuple(item if item.startswith(".") else f".{item}" for item in allowed_extensions)
    ignore_hidden = payload.get("ignore_hidden_files", True)
    if not isinstance(ignore_hidden, bool):
        raise RuntimeError(f"queue.ignore_hidden_files must be a boolean in {config_path}")
    return QueueConfig(
        allowed_extensions=normalized,
        ignore_hidden_files=ignore_hidden,
    )


def load_daemon_config(path: Path, *, app_config: AppConfig) -> DaemonConfig:
    config_path = path.expanduser().resolve()
    try:
        raw_payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Daemon config file was not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse daemon config file: {config_path}") from exc

    payload = _require_mapping(raw_payload, field_name="daemon config", config_path=config_path)
    if "phases" in payload:
        raise RuntimeError(
            f"phases is no longer supported in {config_path}. "
            "Configure the coding agent through dormammu.json and let daemonize reuse dormammu run semantics."
        )
    schema_version = int(payload.get("schema_version", 1))
    prompt_path = _resolve_path(
        _require_non_empty_string(payload.get("prompt_path"), field_name="prompt_path", config_path=config_path),
        base_dir=config_path.parent,
    )
    result_path = _resolve_path(
        _require_non_empty_string(payload.get("result_path"), field_name="result_path", config_path=config_path),
        base_dir=config_path.parent,
    )
    return DaemonConfig(
        schema_version=schema_version,
        config_path=config_path,
        prompt_path=prompt_path,
        result_path=result_path,
        watch=_parse_watch_config(payload.get("watch"), config_path=config_path),
        queue=_parse_queue_config(payload.get("queue"), config_path=config_path),
        goals=parse_goals_config(payload.get("goals"), config_path=config_path),
        autonomous=parse_autonomous_config(payload.get("autonomous"), config_path=config_path),
    )
