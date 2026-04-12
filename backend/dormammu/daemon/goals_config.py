from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_MIN_INTERVAL_MINUTES = 1
DEFAULT_AGENT_TIMEOUT_SECONDS = 600  # 10 minutes


@dataclass(frozen=True, slots=True)
class GoalsConfig:
    """Configuration for the goals-based prompt auto-generation feature.

    ``path`` — directory that contains goal ``.md`` files.
    ``interval_minutes`` — how often (in minutes) to process all goal files
    and emit new prompts.  Minimum 1.
    ``agent_timeout_seconds`` — per-role-agent subprocess timeout in seconds.
    Defaults to 600 (10 minutes).
    """

    path: Path
    interval_minutes: int
    agent_timeout_seconds: int = DEFAULT_AGENT_TIMEOUT_SECONDS

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "interval_minutes": self.interval_minutes,
            "agent_timeout_seconds": self.agent_timeout_seconds,
        }


def parse_goals_config(
    value: Any,
    *,
    config_path: Path,
) -> GoalsConfig | None:
    """Parse the ``goals`` section of a daemonize config file.

    Returns ``None`` when the section is absent (goals feature disabled).
    ``config_path`` is used both for error messages and for resolving
    relative paths.
    """
    if value is None:
        return None

    source = str(config_path)
    if not isinstance(value, Mapping):
        raise RuntimeError(f"goals must be a JSON object in {source}")

    path_raw = value.get("path")
    if not isinstance(path_raw, str) or not path_raw.strip():
        raise RuntimeError(
            f"goals.path must be a non-empty string in {source}"
        )
    candidate = Path(path_raw.strip()).expanduser()
    goals_path = (
        candidate
        if candidate.is_absolute()
        else (config_path.parent / candidate).resolve()
    )

    interval_raw = value.get("interval_minutes", 60)
    try:
        interval_minutes = int(interval_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"goals.interval_minutes must be an integer in {source}"
        ) from exc
    if interval_minutes < _MIN_INTERVAL_MINUTES:
        raise RuntimeError(
            f"goals.interval_minutes must be >= {_MIN_INTERVAL_MINUTES} in {source}"
        )

    timeout_raw = value.get("agent_timeout_seconds", DEFAULT_AGENT_TIMEOUT_SECONDS)
    try:
        agent_timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"goals.agent_timeout_seconds must be an integer in {source}"
        ) from exc
    if agent_timeout_seconds < 1:
        raise RuntimeError(
            f"goals.agent_timeout_seconds must be >= 1 in {source}"
        )

    return GoalsConfig(
        path=goals_path,
        interval_minutes=interval_minutes,
        agent_timeout_seconds=agent_timeout_seconds,
    )
