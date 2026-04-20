from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING, Any, Mapping

from dormammu.telegram.config import TelegramConfig, parse_telegram_config
from dormammu.workspace import WorkspacePaths, resolve_workspace_paths

if TYPE_CHECKING:
    from dormammu.agent.profiles import AgentProfile
    from dormammu.agent.role_config import AgentsConfig


REPO_MARKERS = ("pyproject.toml", "AGENTS.md", ".dev")
DEFAULT_CONFIG_FILENAME = "dormammu.json"
DEFAULT_GLOBAL_HOME_DIRNAME = ".dormammu"
DEFAULT_GLOBAL_CONFIG_FILENAME = "config"
VALID_INPUT_MODES = {"auto", "file", "arg", "stdin", "positional"}
DEFAULT_FALLBACK_AGENT_CLIS = ("codex", "claude", "gemini")
DEFAULT_ACTIVE_AGENT_CLI_PRIORITY = ("codex", "claude", "gemini", "cline")
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


def _default_global_config_path(global_home_dir: Path) -> Path:
    return global_home_dir / DEFAULT_GLOBAL_CONFIG_FILENAME


def _resolve_path_override(
    raw_value: str | None,
    *,
    root: Path,
) -> Path | None:
    if raw_value is None:
        return None
    stripped = raw_value.strip()
    if not stripped:
        return None
    candidate = Path(stripped).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _resolve_sessions_dir_override(
    *,
    env: Mapping[str, str],
    root: Path,
    explicit_env: bool,
) -> Path | None:
    """Resolve DORMAMMU_SESSIONS_DIR without leaking ambient state across repos.

    When a caller explicitly supplies ``env``, treat the override as intentional.
    For the default ambient process environment, only reuse the override when the
    requested repo root matches the current repo context. This preserves session
    isolation for explicit ``repo_root=...`` loads in tests and cross-project
    helpers even when the current process was launched with a managed sessions
    directory for some other repository.
    """
    raw_value = env.get("DORMAMMU_SESSIONS_DIR")
    if raw_value is None:
        return None
    if explicit_env:
        return _resolve_path_override(raw_value, root=root)

    ambient_root = discover_repo_root()
    if ambient_root.resolve() != root.resolve():
        return None
    return _resolve_path_override(raw_value, root=root)


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def _is_writable_path(path: Path) -> bool:
    return os.access(_nearest_existing_parent(path), os.W_OK)


def _resolve_global_home_dir(root: Path, env: Mapping[str, str]) -> Path:
    candidate = _global_home_dir(env)
    if _is_writable_path(candidate):
        return candidate
    user_fragment = str(os.getuid()) if hasattr(os, "getuid") else "default"
    return (Path(tempfile.gettempdir()) / f"dormammu-{user_fragment}").resolve()


def detect_available_agent_cli(env: Mapping[str, str] | None = None) -> Path | None:
    values = env or os.environ
    search_path = values.get("PATH")
    for cli_name in DEFAULT_ACTIVE_AGENT_CLI_PRIORITY:
        resolved = shutil.which(cli_name, path=search_path)
        if resolved:
            return Path(os.path.abspath(resolved))
    return None


def _resolve_config_file(
    root: Path,
    env: Mapping[str, str],
    *,
    global_home_dir: Path,
) -> Path | None:
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
    global_candidate = _default_global_config_path(global_home_dir)
    if global_candidate.exists():
        return global_candidate.resolve()
    return None


def _project_config_file(root: Path) -> Path | None:
    candidate = root / DEFAULT_CONFIG_FILENAME
    if candidate.exists():
        return candidate.resolve()
    return None


def _global_config_file(global_home_dir: Path) -> Path | None:
    candidate = _default_global_config_path(global_home_dir)
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


SETTABLE_SCALAR_KEYS: frozenset[str] = frozenset({
    "active_agent_cli",
    "telegram.bot_token",
})
SETTABLE_LIST_KEYS: frozenset[str] = frozenset({
    "token_exhaustion_patterns",
    "fallback_agent_clis",
    "telegram.allowed_chat_ids",
})


def _navigate_to_leaf(payload: dict[str, Any], key: str) -> tuple[dict[str, Any], str]:
    """Split a dotted key into (parent dict, leaf key), creating intermediate dicts as needed.

    For a flat key like ``"active_agent_cli"`` returns ``(payload, "active_agent_cli")``.
    For a nested key like ``"telegram.bot_token"`` returns ``(payload["telegram"], "bot_token")``.
    """
    parts = key.split(".", 1)
    if len(parts) == 1:
        return payload, key
    parent_key, child_key = parts
    if not isinstance(payload.get(parent_key), dict):
        payload[parent_key] = {}
    return _navigate_to_leaf(payload[parent_key], child_key)


def _prune_empty_parents(payload: dict[str, Any], key: str) -> None:
    """Remove an empty intermediate dict left behind after unset/remove operations."""
    parts = key.split(".", 1)
    if len(parts) == 1:
        return
    parent_key = parts[0]
    child = payload.get(parent_key)
    if isinstance(child, dict) and not child:
        del payload[parent_key]


def _resolve_write_target(config: "AppConfig", *, global_scope: bool) -> Path:
    """Return the config file path that set_config_value should write to.

    For the project scope (``global_scope=False``):
    - Prefer an explicitly set config file that is not the global default
      (e.g. set via ``DORMAMMU_CONFIG_PATH`` or a ``dormammu.json`` in the repo).
    - Fall back to ``<repo_root>/dormammu.json`` when only the global default
      config was resolved (or no config exists yet).
    """
    if global_scope:
        path = config.global_home_dir / DEFAULT_GLOBAL_CONFIG_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    global_default = config.global_home_dir / DEFAULT_GLOBAL_CONFIG_FILENAME
    if config.config_file is not None and config.config_file != global_default:
        return config.config_file
    return config.repo_root / DEFAULT_CONFIG_FILENAME


def set_config_value(
    config: "AppConfig",
    key: str,
    *,
    value: str | None = None,
    add: str | None = None,
    remove: str | None = None,
    unset: bool = False,
    global_scope: bool = False,
) -> Path:
    """Write a single config key mutation and persist to the config file.

    Exactly one of ``value``, ``add``, ``remove``, or ``unset`` must be given.
    Returns the path of the config file that was written.
    """
    if key not in SETTABLE_SCALAR_KEYS and key not in SETTABLE_LIST_KEYS:
        settable = sorted(SETTABLE_SCALAR_KEYS | SETTABLE_LIST_KEYS)
        raise ValueError(f"Unknown or non-writable config key: {key!r}. Settable keys: {settable}")

    operations = [v for v in (value, add, remove) if v is not None] + ([True] if unset else [])
    if len(operations) > 1:
        raise ValueError("Specify at most one of: value, --add, --remove, --unset")
    if not operations:
        raise ValueError("Specify one of: value, --add, --remove, --unset")

    config_path = _resolve_write_target(config, global_scope=global_scope)
    payload = _load_config_payload(config_path if config_path.exists() else None)

    target, leaf = _navigate_to_leaf(payload, key)

    if key in SETTABLE_SCALAR_KEYS:
        if add is not None or remove is not None:
            raise ValueError(f"{key!r} is a scalar key; use a plain value or --unset")
        if unset:
            target.pop(leaf, None)
            _prune_empty_parents(payload, key)
        else:
            target[leaf] = value
    else:
        if unset:
            target.pop(leaf, None)
            _prune_empty_parents(payload, key)
        elif add is not None:
            current: list[Any] = list(target.get(leaf) or [])
            if add not in current:
                current.append(add)
            target[leaf] = current
        elif remove is not None:
            current = list(target.get(leaf) or [])
            try:
                current.remove(remove)
            except ValueError:
                pass
            target[leaf] = current
            _prune_empty_parents(payload, key)
        else:
            try:
                parsed: Any = json.loads(value)  # type: ignore[arg-type]
            except json.JSONDecodeError:
                parsed = [value]
            if not isinstance(parsed, list):
                raise ValueError(f"{key!r} requires a JSON array when replacing the full value")
            target[leaf] = parsed

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return config_path


def write_active_agent_cli_config(config: "AppConfig", cli_path: Path) -> Path:
    config_path = config.config_file or (config.global_home_dir / DEFAULT_GLOBAL_CONFIG_FILENAME)
    payload = _load_config_payload(config_path if config_path.exists() else None)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload["active_agent_cli"] = str(cli_path)
    config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return config_path


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


def _discover_agents_dir(
    root: Path,
    env: Mapping[str, str],
    asset_root: Path,
    *,
    global_home_dir: Path,
) -> Path:
    explicit_dir = env.get("DORMAMMU_AGENTS_DIR")
    if explicit_dir:
        candidate = Path(explicit_dir).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        return candidate

    global_agents_dir = global_home_dir / "agents"
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
    repo_dev_dir: Path
    home_dir: Path
    global_home_dir: Path
    workspace_root: Path
    workspace_project_root: Path
    workspace_tmp_dir: Path
    results_dir: Path
    base_dev_dir: Path
    dev_dir: Path
    sessions_dir: Path
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
    telegram_config: TelegramConfig | None = None
    agents: AgentsConfig | None = None
    agent_profiles: dict[str, AgentProfile] | None = None
    process_timeout_seconds: int | None = None
    fallback_on_nonzero_exit: bool = False

    @classmethod
    def load(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        repo_root: Path | None = None,
        discover: bool = True,
    ) -> "AppConfig":
        explicit_env = env is not None
        values = env or os.environ
        root = discover_repo_root(repo_root) if discover else (repo_root or Path.cwd()).resolve()
        global_home_dir = _resolve_global_home_dir(root, values)
        home_dir = _resolve_home_dir(values)
        workspace_paths = resolve_workspace_paths(
            repo_root=root,
            home_dir=home_dir,
            global_home_dir=global_home_dir,
        )
        asset_root = _discover_asset_root(root, values)
        agents_dir = _discover_agents_dir(
            root,
            values,
            asset_root,
            global_home_dir=global_home_dir,
        )
        config_file = _resolve_config_file(root, values, global_home_dir=global_home_dir)
        config_payload = _load_config_payload(config_file)
        agents_config = _load_effective_agents_config(
            root=root,
            global_home_dir=global_home_dir,
            explicit_config_file=config_file if values.get("DORMAMMU_CONFIG_PATH") else None,
        )
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
            repo_dev_dir=workspace_paths.repo_dev_dir,
            home_dir=home_dir,
            global_home_dir=global_home_dir,
            workspace_root=workspace_paths.workspace_root,
            workspace_project_root=workspace_paths.workspace_project_root,
            workspace_tmp_dir=workspace_paths.tmp_dir,
            results_dir=workspace_paths.results_dir,
            base_dev_dir=workspace_paths.base_dev_dir,
            dev_dir=workspace_paths.dev_dir,
            sessions_dir=(
                _resolve_sessions_dir_override(
                    env=values,
                    root=root,
                    explicit_env=explicit_env,
                )
                or workspace_paths.sessions_dir
            ),
            logs_dir=workspace_paths.logs_dir,
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
            telegram_config=parse_telegram_config(
                config_payload.get("telegram"),
                config_path=config_file,
            ),
            agents=agents_config,
            agent_profiles=_normalize_agent_profiles(agents_config=agents_config),
            process_timeout_seconds=(
                int(config_payload["process_timeout_seconds"])
                if "process_timeout_seconds" in config_payload
                else None
            ),
            fallback_on_nonzero_exit=bool(config_payload.get("fallback_on_nonzero_exit", False)),
        )

    def with_overrides(self, **kwargs: object) -> "AppConfig":
        updated = replace(self, **kwargs)
        if "agent_profiles" in kwargs or "agents" not in kwargs:
            return updated
        return replace(
            updated,
            agent_profiles=_normalize_agent_profiles(agents_config=updated.agents),
        )

    def resolve_agent_profile(self, role: str) -> "AgentProfile":
        from dormammu.agent.profiles import resolve_agent_profile  # noqa: PLC0415

        return resolve_agent_profile(
            role,
            agents_config=self.agents,
            normalized_profiles=self.agent_profiles,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "repo_root": str(self.repo_root),
            "repo_dev_dir": str(self.repo_dev_dir),
            "home_dir": str(self.home_dir),
            "global_home_dir": str(self.global_home_dir),
            "workspace_root": str(self.workspace_root),
            "workspace_project_root": str(self.workspace_project_root),
            "workspace_tmp_dir": str(self.workspace_tmp_dir),
            "results_dir": str(self.results_dir),
            "base_dev_dir": str(self.base_dev_dir),
            "dev_dir": str(self.dev_dir),
            "sessions_dir": str(self.sessions_dir),
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
            "telegram_config": self.telegram_config.to_dict() if self.telegram_config else None,
            "agents": self.agents.to_dict() if self.agents else None,
            "agent_profiles": (
                {
                    name: profile.to_dict()
                    for name, profile in (self.agent_profiles or {}).items()
                }
                if self.agent_profiles is not None
                else None
            ),
            "process_timeout_seconds": self.process_timeout_seconds,
            "fallback_on_nonzero_exit": self.fallback_on_nonzero_exit,
        }

    def runtime_path_prompt(self) -> str:
        paths = WorkspacePaths(
            repo_root=self.repo_root,
            repo_dev_dir=self.repo_dev_dir,
            home_dir=self.home_dir,
            global_home_dir=self.global_home_dir,
            workspace_root=self.workspace_root,
            workspace_project_root=self.workspace_project_root,
            base_dev_dir=self.base_dev_dir,
            dev_dir=self.dev_dir,
            logs_dir=self.logs_dir,
            sessions_dir=self.sessions_dir,
            tmp_dir=self.workspace_tmp_dir,
            results_dir=self.results_dir,
        )
        return paths.runtime_path_prompt()


def _parse_agents_config(
    value: Any,
    *,
    config_path: Path | None,
) -> "AgentsConfig | None":
    """Parse the agents config block, importing lazily to avoid circular imports."""
    from dormammu.agent.role_config import parse_agents_config  # noqa: PLC0415

    return parse_agents_config(value, config_path=config_path)


def _load_effective_agents_config(
    *,
    root: Path,
    global_home_dir: Path,
    explicit_config_file: Path | None,
) -> "AgentsConfig | None":
    from dormammu.agent.role_config import merge_agents_config  # noqa: PLC0415

    if explicit_config_file is not None:
        explicit_payload = _load_config_payload(explicit_config_file)
        return _parse_agents_config(
            explicit_payload.get("agents"),
            config_path=explicit_config_file,
        )

    global_config_file = _global_config_file(global_home_dir)
    project_config_file = _project_config_file(root)
    global_agents = _parse_agents_config(
        _load_config_payload(global_config_file).get("agents"),
        config_path=global_config_file,
    )
    project_agents = _parse_agents_config(
        _load_config_payload(project_config_file).get("agents"),
        config_path=project_config_file,
    )
    return merge_agents_config(global_agents, project_agents)


def _normalize_agent_profiles(
    *,
    agents_config: "AgentsConfig | None",
) -> "dict[str, AgentProfile]":
    from dormammu.agent.profiles import normalize_agent_profiles  # noqa: PLC0415

    return normalize_agent_profiles(agents_config=agents_config)
