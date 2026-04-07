from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import os
from pathlib import Path
from typing import Mapping


REPO_MARKERS = ("pyproject.toml", "AGENTS.md", ".dev")


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
        return cls(
            app_name=values.get("DORMAMMU_APP_NAME", "dormammu"),
            host=values.get("DORMAMMU_HOST", "127.0.0.1"),
            port=_read_int(values, "DORMAMMU_PORT", 8000),
            log_level=values.get("DORMAMMU_LOG_LEVEL", "info"),
            repo_root=root,
            dev_dir=dev_dir,
            logs_dir=dev_dir / "logs",
            templates_dir=root / "templates",
            frontend_dir=root / "frontend",
        )

    def with_overrides(self, **kwargs: object) -> "AppConfig":
        return replace(self, **kwargs)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        return {key: str(value) if isinstance(value, Path) else value for key, value in data.items()}
