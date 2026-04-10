from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from dormammu.daemon.models import QueueConfig, QueuedPrompt


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def prompt_sort_key(filename: str) -> tuple[int, object, str]:
    numeric_match = re.match(r"^(\d+)", filename)
    if numeric_match is not None:
        return (0, int(numeric_match.group(1)), filename.casefold())
    alpha_match = re.match(r"^([A-Za-z]+)", filename)
    if alpha_match is not None:
        return (1, alpha_match.group(1).casefold(), filename.casefold())
    return (2, filename.casefold(), filename.casefold())


def is_prompt_candidate(path: Path, queue_config: QueueConfig) -> bool:
    if not path.is_file():
        return False
    if queue_config.ignore_hidden_files and path.name.startswith("."):
        return False
    if queue_config.allowed_extensions and path.suffix.lower() not in {
        item.lower() for item in queue_config.allowed_extensions
    }:
        return False
    return True


def queued_prompt_for_path(path: Path) -> QueuedPrompt:
    return QueuedPrompt(
        path=path,
        filename=path.name,
        sort_key=prompt_sort_key(path.name),
        detected_at=_iso_now(),
    )
