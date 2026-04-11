from __future__ import annotations

from datetime import datetime, timezone


def iso_now() -> str:
    """Return the current local time as an ISO 8601 string with seconds precision."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
