"""Configuration model and parser for the autonomous self-improvement scheduler."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_MIN_INTERVAL_MINUTES = 5
DEFAULT_AGENT_TIMEOUT_SECONDS = 600

VALID_FOCUS_VALUES = ("all", "bugs", "improvements", "tests", "docs")


@dataclass(frozen=True, slots=True)
class AutonomousConfig:
    """Configuration for autonomous self-improvement mode.

    When enabled the daemon periodically analyzes the repository, identifies
    the highest-priority improvement task, generates a full development prompt,
    and queues it for execution — without any human-supplied goal files.

    Attributes
    ----------
    enabled:
        Whether autonomous mode is active.
    interval_minutes:
        How often (in minutes) to analyze the repository and emit a new
        development prompt.  Minimum 5.
    focus:
        Which improvement area to prioritize.  One of:
        ``"all"``          — anything the agent considers most impactful.
        ``"bugs"``         — crash reports, failing tests, error-prone paths.
        ``"improvements"`` — performance, readability, architecture.
        ``"tests"``        — missing or weak test coverage.
        ``"docs"``         — missing or stale documentation.
    agent_timeout_seconds:
        Per-agent subprocess timeout in seconds.  Defaults to 600.
    max_queued_tasks:
        Maximum number of auto-generated prompts allowed in the queue at
        the same time.  New generation is skipped when this limit is reached.
    """

    enabled: bool
    interval_minutes: int
    focus: str
    agent_timeout_seconds: int
    max_queued_tasks: int

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "interval_minutes": self.interval_minutes,
            "focus": self.focus,
            "agent_timeout_seconds": self.agent_timeout_seconds,
            "max_queued_tasks": self.max_queued_tasks,
        }


def parse_autonomous_config(
    value: Any,
    *,
    config_path: Path,
) -> AutonomousConfig | None:
    """Parse the ``autonomous`` section of a daemonize config file.

    Returns ``None`` when the section is absent (autonomous mode disabled).
    """
    if value is None:
        return None

    source = str(config_path)
    if not isinstance(value, Mapping):
        raise RuntimeError(f"autonomous must be a JSON object in {source}")

    enabled_raw = value.get("enabled", True)
    enabled = bool(enabled_raw)

    interval_raw = value.get("interval_minutes", 120)
    try:
        interval_minutes = int(interval_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"autonomous.interval_minutes must be an integer in {source}"
        ) from exc
    if interval_minutes < _MIN_INTERVAL_MINUTES:
        raise RuntimeError(
            f"autonomous.interval_minutes must be >= {_MIN_INTERVAL_MINUTES} in {source}"
        )

    focus_raw = value.get("focus", "all")
    if focus_raw not in VALID_FOCUS_VALUES:
        raise RuntimeError(
            f"autonomous.focus must be one of {VALID_FOCUS_VALUES} in {source}"
        )
    focus = str(focus_raw)

    timeout_raw = value.get("agent_timeout_seconds", DEFAULT_AGENT_TIMEOUT_SECONDS)
    try:
        agent_timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"autonomous.agent_timeout_seconds must be an integer in {source}"
        ) from exc
    if agent_timeout_seconds < 1:
        raise RuntimeError(
            f"autonomous.agent_timeout_seconds must be >= 1 in {source}"
        )

    max_queued_raw = value.get("max_queued_tasks", 3)
    try:
        max_queued_tasks = int(max_queued_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"autonomous.max_queued_tasks must be an integer in {source}"
        ) from exc
    if max_queued_tasks < 1:
        raise RuntimeError(
            f"autonomous.max_queued_tasks must be >= 1 in {source}"
        )

    return AutonomousConfig(
        enabled=enabled,
        interval_minutes=interval_minutes,
        focus=focus,
        agent_timeout_seconds=agent_timeout_seconds,
        max_queued_tasks=max_queued_tasks,
    )
