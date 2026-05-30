from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from dormammu.config import AppConfig, DEFAULT_CONFIG_FILENAME, DEFAULT_GLOBAL_CONFIG_FILENAME


MASKED_SECRET = "***"
_SECRET_PATHS = (
    ("telegram", "bot_token"),
    ("web", "password_hash"),
)


def _load_json_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse config file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Config file must contain a JSON object: {path}")
    return payload


def _write_target(config: AppConfig, *, scope: str) -> Path:
    if scope == "global":
        path = config.global_home_dir / DEFAULT_GLOBAL_CONFIG_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    if scope != "project":
        raise ValueError("scope must be 'project' or 'global'")
    global_default = config.global_home_dir / DEFAULT_GLOBAL_CONFIG_FILENAME
    if config.config_file is not None and config.config_file != global_default:
        return config.config_file
    return config.repo_root / DEFAULT_CONFIG_FILENAME


def _clean_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return [item for item in value if item.strip()]


def _set_or_remove(payload: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        payload.pop(key, None)
    else:
        payload[key] = value


def _redacted_raw_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(raw))
    for parent, key in _SECRET_PATHS:
        section = payload.get(parent)
        if isinstance(section, dict) and key in section:
            section[key] = MASKED_SECRET
    return payload


def _restore_masked_secrets(next_payload: dict[str, Any], previous_payload: Mapping[str, Any]) -> None:
    for parent, key in _SECRET_PATHS:
        section = next_payload.get(parent)
        if not isinstance(section, dict) or section.get(key) != MASKED_SECRET:
            continue
        previous_section = previous_payload.get(parent)
        if isinstance(previous_section, Mapping) and key in previous_section:
            section[key] = previous_section[key]
        else:
            section.pop(key, None)


def _settings_payload_from_raw(config: AppConfig, raw: Mapping[str, Any], *, target: Path, scope: str) -> dict[str, Any]:
    telegram = dict(raw.get("telegram") or {})
    if "bot_token" in telegram:
        telegram["bot_token"] = MASKED_SECRET
    web = dict(raw.get("web") or {})
    web.pop("password_hash", None)
    if "allowed_roots" not in web:
        web["allowed_roots"] = [str(path) for path in config.web_config.allowed_roots]
    web["password_configured"] = bool(config.web_config.password_hash)
    redacted_raw = _redacted_raw_payload(raw)
    return {
        "scope": scope,
        "config_file": str(target),
        "repo_root": str(config.repo_root),
        "active_agent_cli": raw.get("active_agent_cli"),
        "fallback_agent_clis": raw.get("fallback_agent_clis", []),
        "token_exhaustion_patterns": raw.get("token_exhaustion_patterns", list(config.token_exhaustion_patterns)),
        "telegram": telegram,
        "web": web,
        "process_timeout_seconds": raw.get("process_timeout_seconds"),
        "fallback_on_nonzero_exit": bool(raw.get("fallback_on_nonzero_exit", False)),
        "resolved": config.to_dict(),
        "raw_json": json.dumps(redacted_raw, indent=2, ensure_ascii=True) + "\n",
    }


def read_settings(config: AppConfig, *, scope: str = "project") -> dict[str, Any]:
    target = _write_target(config, scope=scope)
    raw = _load_json_object(target)
    return _settings_payload_from_raw(config, raw, target=target, scope=scope)


def write_raw_settings(config: AppConfig, raw_json: str, *, scope: str = "project") -> Path:
    target = _write_target(config, scope=scope)
    previous = _load_json_object(target)
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse raw config JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Raw config must be a JSON object")
    _restore_masked_secrets(payload, previous)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return target


def apply_settings_patch(
    config: AppConfig,
    patch: Mapping[str, Any],
    *,
    scope: str = "project",
) -> Path:
    target = _write_target(config, scope=scope)
    payload = _load_json_object(target)

    if "active_agent_cli" in patch:
        value = patch["active_agent_cli"]
        if value is not None and not isinstance(value, str):
            raise ValueError("active_agent_cli must be a string or null")
        _set_or_remove(payload, "active_agent_cli", value.strip() if isinstance(value, str) and value.strip() else None)

    if "fallback_agent_clis" in patch:
        payload["fallback_agent_clis"] = _clean_string_list(patch["fallback_agent_clis"], field="fallback_agent_clis")

    if "token_exhaustion_patterns" in patch:
        payload["token_exhaustion_patterns"] = _clean_string_list(
            patch["token_exhaustion_patterns"],
            field="token_exhaustion_patterns",
        )

    if "telegram" in patch:
        telegram_patch = patch["telegram"]
        if telegram_patch is None:
            payload.pop("telegram", None)
        elif isinstance(telegram_patch, Mapping):
            telegram = dict(payload.get("telegram") or {})
            if "bot_token" in telegram_patch:
                token = telegram_patch["bot_token"]
                if token not in (None, "", MASKED_SECRET):
                    if not isinstance(token, str):
                        raise ValueError("telegram.bot_token must be a string")
                    telegram["bot_token"] = token.strip()
                elif token is None:
                    telegram.pop("bot_token", None)
            if "allowed_chat_ids" in telegram_patch:
                ids = telegram_patch["allowed_chat_ids"]
                if not isinstance(ids, list):
                    raise ValueError("telegram.allowed_chat_ids must be a list")
                telegram["allowed_chat_ids"] = [int(item) for item in ids]
            for key in ("stream_on_start",):
                if key in telegram_patch:
                    telegram[key] = bool(telegram_patch[key])
            for key in ("chunk_size",):
                if key in telegram_patch:
                    telegram[key] = int(telegram_patch[key])
            for key in ("flush_interval_seconds",):
                if key in telegram_patch:
                    telegram[key] = float(telegram_patch[key])
            if telegram:
                payload["telegram"] = telegram
            else:
                payload.pop("telegram", None)
        else:
            raise ValueError("telegram must be an object or null")

    if "web" in patch:
        web_patch = patch["web"]
        if not isinstance(web_patch, Mapping):
            raise ValueError("web must be an object")
        web = dict(payload.get("web") or {})
        if "allowed_roots" in web_patch:
            roots = _clean_string_list(web_patch["allowed_roots"], field="web.allowed_roots")
            if not roots:
                raise ValueError("web.allowed_roots must contain at least one directory")
            web["allowed_roots"] = roots
        if "host" in web_patch:
            host = web_patch["host"]
            if host is None or host == "":
                web.pop("host", None)
            elif isinstance(host, str):
                web["host"] = host.strip()
            else:
                raise ValueError("web.host must be a string or null")
        if "port" in web_patch:
            port = web_patch["port"]
            if port is None or port == "":
                web.pop("port", None)
            else:
                web["port"] = int(port)
        payload["web"] = web

    if "process_timeout_seconds" in patch:
        value = patch["process_timeout_seconds"]
        _set_or_remove(payload, "process_timeout_seconds", None if value in (None, "") else int(value))

    if "fallback_on_nonzero_exit" in patch:
        payload["fallback_on_nonzero_exit"] = bool(patch["fallback_on_nonzero_exit"])

    telegram = payload.get("telegram")
    if isinstance(telegram, dict) and telegram and not str(telegram.get("bot_token") or "").strip():
        raise ValueError("telegram.bot_token is required when telegram settings are present")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return target


def set_web_password_hash(
    config: AppConfig,
    password_hash: str,
    *,
    scope: str = "project",
) -> Path:
    target = _write_target(config, scope=scope)
    payload = _load_json_object(target)
    web = dict(payload.get("web") or {})
    web["password_hash"] = password_hash
    payload["web"] = web
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return target
