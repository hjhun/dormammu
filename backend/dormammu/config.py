from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from typing import Any, Mapping


REPO_MARKERS = ("pyproject.toml", "AGENTS.md", ".dev")
DEFAULT_CONFIG_FILENAME = "dormammu.json"
DEFAULT_GLOBAL_HOME_DIRNAME = ".dormammu"
DEFAULT_GLOBAL_CONFIG_FILENAME = "config"
VALID_INPUT_MODES = {"auto", "file", "arg", "stdin", "positional"}
DEFAULT_FALLBACK_AGENT_CLIS = ("codex", "claude", "gemini")
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


def _resolve_home_dir(env: Mapping[str, str]) -> Path:
    home_value = env.get("HOME")
    if home_value:
        return Path(home_value).expanduser()
    return Path.home()


def _global_home_dir(env: Mapping[str, str]) -> Path:
    return _resolve_home_dir(env) / DEFAULT_GLOBAL_HOME_DIRNAME


def _default_global_config_path(env: Mapping[str, str]) -> Path:
    return _global_home_dir(env) / DEFAULT_GLOBAL_CONFIG_FILENAME


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
    global_candidate = _default_global_config_path(env)
    if global_candidate.exists():
        return global_candidate.resolve()
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
        return Path(os.path.abspath(str(candidate)))
    if config_dir is not None and ("/" in raw_path or raw_path.startswith(".")):
        return (config_dir / candidate).resolve()
    return candidate


def _parse_active_agent_cli(
    value: Any,
    *,
    config_path: Path | None,
) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        source = str(config_path) if config_path is not None else DEFAULT_CONFIG_FILENAME
        raise RuntimeError(f"active_agent_cli must be a non-empty string in {source}")
    config_dir = config_path.parent if config_path is not None else None
    return _resolve_cli_path(value, config_dir=config_dir)


def _discover_asset_root(root: Path, env: Mapping[str, str]) -> Path:
    explicit_root = env.get("DORMAMMU_ASSET_ROOT")
    if explicit_root:
        candidate = Path(explicit_root).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        return candidate

    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "templates").exists():
        return source_root

    packaged_asset_root = Path(__file__).resolve().parent / "assets"
    if (packaged_asset_root / "templates").exists():
        return packaged_asset_root
    return root


def _discover_agents_dir(root: Path, env: Mapping[str, str], asset_root: Path) -> Path:
    explicit_dir = env.get("DORMAMMU_AGENTS_DIR")
    if explicit_dir:
        candidate = Path(explicit_dir).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        return candidate

    global_agents_dir = _global_home_dir(env) / "agents"
    if (global_agents_dir / "AGENTS.md").exists():
        return global_agents_dir

    repo_agents_dir = root / "agents"
    if (repo_agents_dir / "AGENTS.md").exists():
        return repo_agents_dir

    packaged_agents_dir = asset_root / "agents"
    if (packaged_agents_dir / "AGENTS.md").exists():
        return packaged_agents_dir

    return repo_agents_dir


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
class CliInvocationConfig:
    extra_args: tuple[str, ...] = ()
    input_mode: str | None = None
    prompt_flag: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "extra_args": list(self.extra_args),
            "input_mode": self.input_mode,
            "prompt_flag": self.prompt_flag,
        }


@dataclass(frozen=True, slots=True)
class FallbackCliConfig(CliInvocationConfig):
    path: Path = Path()

    def to_dict(self) -> dict[str, object]:
        payload = CliInvocationConfig.to_dict(self)
        payload["path"] = str(self.path)
        return payload


def _parse_cli_invocation_settings(
    payload: Mapping[str, Any],
    *,
    field_prefix: str,
    config_path: Path | None,
) -> CliInvocationConfig:
    input_mode = payload.get("input_mode")
    if input_mode is not None and input_mode not in VALID_INPUT_MODES:
        raise RuntimeError(f"Unsupported {field_prefix}.input_mode: {input_mode}")

    prompt_flag = payload.get("prompt_flag")
    if prompt_flag is not None and not isinstance(prompt_flag, str):
        raise RuntimeError(f"{field_prefix}.prompt_flag must be a string when provided")

    return CliInvocationConfig(
        extra_args=_coerce_string_list(
            payload.get("extra_args", []),
            field_name=f"{field_prefix}.extra_args",
            config_path=config_path,
        ),
        input_mode=input_mode,
        prompt_flag=prompt_flag,
    )


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
    invocation = _parse_cli_invocation_settings(
        entry,
        field_prefix="fallback_agent_clis",
        config_path=config_path,
    )

    return FallbackCliConfig(
        path=_resolve_cli_path(raw_path, config_dir=config_dir),
        extra_args=invocation.extra_args,
        input_mode=invocation.input_mode,
        prompt_flag=invocation.prompt_flag,
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


def _default_fallback_agent_clis() -> tuple[FallbackCliConfig, ...]:
    return tuple(FallbackCliConfig(path=Path(name)) for name in DEFAULT_FALLBACK_AGENT_CLIS)


def _normalize_cli_override_key(raw_key: str, *, config_dir: Path | None) -> str:
    candidate = Path(raw_key).expanduser()
    if candidate.is_absolute() or "/" in raw_key or raw_key.startswith("."):
        if not candidate.is_absolute() and config_dir is not None:
            candidate = config_dir / candidate
        return os.path.abspath(str(candidate)).lower()
    return raw_key.strip().lower()


def _parse_cli_overrides(
    value: Any,
    *,
    config_path: Path | None,
) -> dict[str, CliInvocationConfig]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        source = str(config_path) if config_path is not None else DEFAULT_CONFIG_FILENAME
        raise RuntimeError(f"cli_overrides must be a JSON object in {source}")

    config_dir = config_path.parent if config_path is not None else None
    overrides: dict[str, CliInvocationConfig] = {}
    for raw_key, raw_payload in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise RuntimeError("cli_overrides keys must be non-empty strings")
        if not isinstance(raw_payload, Mapping):
            raise RuntimeError("cli_overrides values must be JSON objects")
        overrides[_normalize_cli_override_key(raw_key, config_dir=config_dir)] = (
            _parse_cli_invocation_settings(
                raw_payload,
                field_prefix="cli_overrides",
                config_path=config_path,
            )
        )
    return overrides


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_name: str
    repo_root: Path
    home_dir: Path
    global_home_dir: Path
    base_dev_dir: Path
    dev_dir: Path
    logs_dir: Path
    templates_dir: Path
    agents_dir: Path
    config_file: Path | None
    active_agent_cli: Path | None = None
    fallback_agent_clis: tuple[FallbackCliConfig, ...] = ()
    cli_overrides: dict[str, CliInvocationConfig] | None = None
    token_exhaustion_patterns: tuple[str, ...] = DEFAULT_TOKEN_EXHAUSTION_PATTERNS
    guidance_files: tuple[Path, ...] = ()
    default_guidance_files: tuple[Path, ...] = ()

    @classmethod
    def load(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        repo_root: Path | None = None,
    ) -> "AppConfig":
        values = env or os.environ
        root = discover_repo_root(repo_root)
        asset_root = _discover_asset_root(root, values)
        agents_dir = _discover_agents_dir(root, values, asset_root)
        base_dev_dir = root / ".dev"
        dev_dir = base_dev_dir
        config_file = _resolve_config_file(root, values)
        config_payload = _load_config_payload(config_file)
        fallback_agent_clis = (
            _parse_fallback_agent_clis(
                config_payload.get("fallback_agent_clis"),
                config_path=config_file,
            )
            if "fallback_agent_clis" in config_payload
            else _default_fallback_agent_clis()
        )
        return cls(
            app_name=str(values.get("DORMAMMU_APP_NAME", _config_value(config_payload, "app_name", "dormammu"))),
            repo_root=root,
            home_dir=_resolve_home_dir(values),
            global_home_dir=_global_home_dir(values),
            base_dev_dir=base_dev_dir,
            dev_dir=dev_dir,
            logs_dir=dev_dir / "logs",
            templates_dir=asset_root / "templates",
            agents_dir=agents_dir,
            config_file=config_file,
            active_agent_cli=_parse_active_agent_cli(
                config_payload.get("active_agent_cli"),
                config_path=config_file,
            ),
            fallback_agent_clis=fallback_agent_clis,
            cli_overrides=_parse_cli_overrides(
                config_payload.get("cli_overrides"),
                config_path=config_file,
            ),
            token_exhaustion_patterns=_coerce_string_list(
                config_payload.get("token_exhaustion_patterns", list(DEFAULT_TOKEN_EXHAUSTION_PATTERNS)),
                field_name="token_exhaustion_patterns",
                config_path=config_file,
            )
            or DEFAULT_TOKEN_EXHAUSTION_PATTERNS,
            default_guidance_files=((agents_dir / "AGENTS.md",) if (agents_dir / "AGENTS.md").exists() else ()),
        )

    def with_overrides(self, **kwargs: object) -> "AppConfig":
        return replace(self, **kwargs)

    def to_dict(self) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "repo_root": str(self.repo_root),
            "home_dir": str(self.home_dir),
            "global_home_dir": str(self.global_home_dir),
            "base_dev_dir": str(self.base_dev_dir),
            "dev_dir": str(self.dev_dir),
            "logs_dir": str(self.logs_dir),
            "templates_dir": str(self.templates_dir),
            "agents_dir": str(self.agents_dir),
            "config_file": str(self.config_file) if self.config_file else None,
            "active_agent_cli": str(self.active_agent_cli) if self.active_agent_cli else None,
            "fallback_agent_clis": [item.to_dict() for item in self.fallback_agent_clis],
            "cli_overrides": {
                key: value.to_dict()
                for key, value in (self.cli_overrides or {}).items()
            },
            "token_exhaustion_patterns": list(self.token_exhaustion_patterns),
            "guidance_files": [str(path) for path in self.guidance_files],
            "default_guidance_files": [str(path) for path in self.default_guidance_files],
        }
