from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from dormammu.config import AppConfig
from dormammu.config import VALID_INPUT_MODES
from dormammu.daemon.models import (
    DaemonConfig,
    PHASE_SEQUENCE,
    PhaseCliConfig,
    PhaseExecutionConfig,
    QueueConfig,
    WatchConfig,
)


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
    normalized = tuple(
        item if item.startswith(".") else f".{item}"
        for item in allowed_extensions
    )
    ignore_hidden = payload.get("ignore_hidden_files", True)
    if not isinstance(ignore_hidden, bool):
        raise RuntimeError(f"queue.ignore_hidden_files must be a boolean in {config_path}")
    return QueueConfig(
        allowed_extensions=normalized,
        ignore_hidden_files=ignore_hidden,
    )


def _parse_phase_cli_config(value: Any, *, phase_name: str, config_path: Path, base_dir: Path) -> PhaseCliConfig:
    payload = _require_mapping(
        value,
        field_name=f"phases.{phase_name}.agent_cli",
        config_path=config_path,
    )
    path_text = _require_non_empty_string(
        payload.get("path"),
        field_name=f"phases.{phase_name}.agent_cli.path",
        config_path=config_path,
    )
    input_mode = str(payload.get("input_mode", "auto"))
    if input_mode not in VALID_INPUT_MODES:
        raise RuntimeError(
            f"phases.{phase_name}.agent_cli.input_mode must be one of {sorted(VALID_INPUT_MODES)} in {config_path}"
        )
    prompt_flag = payload.get("prompt_flag")
    if prompt_flag is not None and not isinstance(prompt_flag, str):
        raise RuntimeError(f"phases.{phase_name}.agent_cli.prompt_flag must be a string in {config_path}")
    extra_args = payload.get("extra_args", [])
    if not isinstance(extra_args, list) or any(not isinstance(item, str) for item in extra_args):
        raise RuntimeError(f"phases.{phase_name}.agent_cli.extra_args must be a JSON array of strings in {config_path}")
    cli_path = _resolve_path(path_text, base_dir=base_dir) if "/" in path_text or path_text.startswith(".") else Path(path_text)
    return PhaseCliConfig(
        path=cli_path,
        input_mode=input_mode,
        prompt_flag=prompt_flag,
        extra_args=tuple(extra_args),
    )


def _resolve_skill_path(
    *,
    skill_path_text: str | None,
    skill_name: str | None,
    app_config: AppConfig,
    config_path: Path,
    base_dir: Path,
) -> tuple[str | None, Path]:
    if skill_path_text and skill_name:
        raise RuntimeError(f"Specify only one of skill_path or skill_name in {config_path}")

    if skill_path_text:
        resolved = _resolve_path(skill_path_text, base_dir=base_dir)
        if not resolved.exists():
            raise RuntimeError(f"Skill path was not found: {resolved}")
        return None, resolved

    if skill_name:
        candidates = (
            app_config.repo_root / "agents" / "skills" / skill_name / "SKILL.md",
            app_config.global_home_dir / "agents" / "skills" / skill_name / "SKILL.md",
        )
        for candidate in candidates:
            if candidate.exists():
                return skill_name, candidate.resolve()
        raise RuntimeError(
            f"Skill name '{skill_name}' was not found under "
            f"{app_config.repo_root / 'agents' / 'skills'} or "
            f"{app_config.global_home_dir / 'agents' / 'skills'}"
        )

    raise RuntimeError(f"Each phase must define skill_path or skill_name in {config_path}")


def _parse_phase_config(
    value: Any,
    *,
    phase_name: str,
    config_path: Path,
    base_dir: Path,
    app_config: AppConfig,
) -> PhaseExecutionConfig:
    payload = _require_mapping(value, field_name=f"phases.{phase_name}", config_path=config_path)
    skill_path_text = payload.get("skill_path")
    if skill_path_text is not None and not isinstance(skill_path_text, str):
        raise RuntimeError(f"phases.{phase_name}.skill_path must be a string in {config_path}")
    raw_skill_name = payload.get("skill_name")
    skill_name = None
    if raw_skill_name is not None:
        skill_name = _require_non_empty_string(
            raw_skill_name,
            field_name=f"phases.{phase_name}.skill_name",
            config_path=config_path,
        )
    resolved_skill_name, resolved_skill_path = _resolve_skill_path(
        skill_path_text=skill_path_text,
        skill_name=skill_name,
        app_config=app_config,
        config_path=config_path,
        base_dir=base_dir,
    )
    return PhaseExecutionConfig(
        phase_name=phase_name,
        skill_name=resolved_skill_name,
        skill_path=resolved_skill_path,
        agent_cli=_parse_phase_cli_config(
            payload.get("agent_cli"),
            phase_name=phase_name,
            config_path=config_path,
            base_dir=base_dir,
        ),
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
    schema_version = int(payload.get("schema_version", 1))
    prompt_path = _resolve_path(
        _require_non_empty_string(payload.get("prompt_path"), field_name="prompt_path", config_path=config_path),
        base_dir=config_path.parent,
    )
    result_path = _resolve_path(
        _require_non_empty_string(payload.get("result_path"), field_name="result_path", config_path=config_path),
        base_dir=config_path.parent,
    )
    phases_payload = _require_mapping(payload.get("phases"), field_name="phases", config_path=config_path)
    phases = {
        phase_name: _parse_phase_config(
            phases_payload.get(phase_name),
            phase_name=phase_name,
            config_path=config_path,
            base_dir=config_path.parent,
            app_config=app_config,
        )
        for phase_name in PHASE_SEQUENCE
    }
    return DaemonConfig(
        schema_version=schema_version,
        config_path=config_path,
        prompt_path=prompt_path,
        result_path=result_path,
        watch=_parse_watch_config(payload.get("watch"), config_path=config_path),
        queue=_parse_queue_config(payload.get("queue"), config_path=config_path),
        phases=phases,
    )
