from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from typing import Any, Mapping


REPO_MARKERS = ("pyproject.toml", "AGENTS.md", ".dev")
DEFAULT_CONFIG_FILENAME = "dormammu.json"
VALID_INPUT_MODES = {"auto", "file", "arg", "stdin", "positional"}
DEFAULT_TOKEN_EXHAUSTION_PATTERNS = (
    "usage limit",
    "quota exceeded",
    "rate limit exceeded",
    "token limit",
    "insufficient credits",
    "credit balance is too low",
)


def discover_repo_root(start: Path | None = None) -> Path:
    """Find the nearest repository root from the current path upward."""

    candidate = (start or Path.cwd()).resolve()
    for path in (candidate, *candidate.parents):
        if any((path / marker).exists() for marker in REPO_MARKERS):
            return path
    return candidate


def _read_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None:
        return default
    return int(value)


def _config_value(payload: Mapping[str, Any], key: str, default: Any) -> Any:
    value = payload.get(key, default)
    return default if value is None else value


def _resolve_config_file(root: Path, env: Mapping[str, str]) -> Path | None:
    explicit_path = env.get("DORMAMMU_CONFIG_PATH")
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        if not candidate.exists():
            raise RuntimeError(f"Configured dormammu config file was not found: {candidate}")
        return candidate

    candidate = root / DEFAULT_CONFIG_FILENAME
    if candidate.exists():
        return candidate.resolve()
    return None


def _load_config_payload(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}

    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse dormammu config file: {path}") from exc

    if not isinstance(raw_payload, Mapping):
        raise RuntimeError(f"Dormammu config file must contain a JSON object: {path}")
    return dict(raw_payload)


def _resolve_cli_path(raw_path: str, *, config_dir: Path | None) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if config_dir is not None and ("/" in raw_path or raw_path.startswith(".")):
        return (config_dir / candidate).resolve()
    return candidate


def _coerce_string_list(
    value: Any,
    *,
    field_name: str,
    config_path: Path | None,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        source = str(config_path) if config_path is not None else DEFAULT_CONFIG_FILENAME
        raise RuntimeError(f"{field_name} must be a JSON array of strings in {source}")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class FallbackCliConfig:
    path: Path
    extra_args: tuple[str, ...] = ()
    input_mode: str | None = None
    prompt_flag: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "extra_args": list(self.extra_args),
            "input_mode": self.input_mode,
            "prompt_flag": self.prompt_flag,
        }


def _parse_fallback_cli_entry(
    entry: Any,
    *,
    config_path: Path | None,
) -> FallbackCliConfig:
    config_dir = config_path.parent if config_path is not None else None
    if isinstance(entry, str):
        return FallbackCliConfig(path=_resolve_cli_path(entry, config_dir=config_dir))

    if not isinstance(entry, Mapping):
        source = str(config_path) if config_path is not None else DEFAULT_CONFIG_FILENAME
        raise RuntimeError(f"fallback_agent_clis entries must be strings or objects in {source}")

    raw_path = entry.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        source = str(config_path) if config_path is not None else DEFAULT_CONFIG_FILENAME
        raise RuntimeError(f"fallback_agent_clis entries must include a non-empty 'path' in {source}")

    input_mode = entry.get("input_mode")
    if input_mode is not None and input_mode not in VALID_INPUT_MODES:
        raise RuntimeError(f"Unsupported fallback input_mode: {input_mode}")

    prompt_flag = entry.get("prompt_flag")
    if prompt_flag is not None and not isinstance(prompt_flag, str):
        raise RuntimeError("fallback_agent_clis.prompt_flag must be a string when provided")

    return FallbackCliConfig(
        path=_resolve_cli_path(raw_path, config_dir=config_dir),
        extra_args=_coerce_string_list(
            entry.get("extra_args", []),
            field_name="fallback_agent_clis.extra_args",
            config_path=config_path,
        ),
        input_mode=input_mode,
        prompt_flag=prompt_flag,
    )


def _parse_fallback_agent_clis(
    value: Any,
    *,
    config_path: Path | None,
) -> tuple[FallbackCliConfig, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        source = str(config_path) if config_path is not None else DEFAULT_CONFIG_FILENAME
        raise RuntimeError(f"fallback_agent_clis must be a JSON array in {source}")
    return tuple(_parse_fallback_cli_entry(item, config_path=config_path) for item in value)


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_name: str
    host: str
    port: int
    log_level: str
    repo_root: Path
    dev_dir: Path
    logs_dir: Path
    templates_dir: Path
    frontend_dir: Path
    config_file: Path | None
    fallback_agent_clis: tuple[FallbackCliConfig, ...] = ()
    token_exhaustion_patterns: tuple[str, ...] = DEFAULT_TOKEN_EXHAUSTION_PATTERNS

    @classmethod
    def load(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        repo_root: Path | None = None,
    ) -> "AppConfig":
        values = env or os.environ
        root = discover_repo_root(repo_root)
        dev_dir = root / ".dev"
        config_file = _resolve_config_file(root, values)
        config_payload = _load_config_payload(config_file)
        return cls(
            app_name=str(values.get("DORMAMMU_APP_NAME", _config_value(config_payload, "app_name", "dormammu"))),
            host=str(values.get("DORMAMMU_HOST", _config_value(config_payload, "host", "127.0.0.1"))),
            port=_read_int(values, "DORMAMMU_PORT", int(_config_value(config_payload, "port", 8000))),
            log_level=str(values.get("DORMAMMU_LOG_LEVEL", _config_value(config_payload, "log_level", "info"))),
            repo_root=root,
            dev_dir=dev_dir,
            logs_dir=dev_dir / "logs",
            templates_dir=root / "templates",
            frontend_dir=root / "frontend",
            config_file=config_file,
            fallback_agent_clis=_parse_fallback_agent_clis(
                config_payload.get("fallback_agent_clis"),
                config_path=config_file,
            ),
            token_exhaustion_patterns=_coerce_string_list(
                config_payload.get("token_exhaustion_patterns", list(DEFAULT_TOKEN_EXHAUSTION_PATTERNS)),
                field_name="token_exhaustion_patterns",
                config_path=config_file,
            )
            or DEFAULT_TOKEN_EXHAUSTION_PATTERNS,
        )

    def with_overrides(self, **kwargs: object) -> "AppConfig":
        return replace(self, **kwargs)

    def to_dict(self) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "host": self.host,
            "port": self.port,
            "log_level": self.log_level,
            "repo_root": str(self.repo_root),
            "dev_dir": str(self.dev_dir),
            "logs_dir": str(self.logs_dir),
            "templates_dir": str(self.templates_dir),
            "frontend_dir": str(self.frontend_dir),
            "config_file": str(self.config_file) if self.config_file else None,
            "fallback_agent_clis": [item.to_dict() for item in self.fallback_agent_clis],
            "token_exhaustion_patterns": list(self.token_exhaustion_patterns),
        }
