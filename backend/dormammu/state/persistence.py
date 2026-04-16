"""Low-level JSON persistence primitives for .dev/ state files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def deep_merge(defaults: dict[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge *current* values on top of *defaults*.

    Values present in *current* override *defaults* at every depth.
    """
    merged = dict(defaults)
    for key, value in current.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file and return its contents as a dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Serialise *payload* to *path* with stable indentation."""
    path.write_text(
        json.dumps(dict(payload), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def ensure_json_file(path: Path, defaults: dict[str, Any]) -> None:
    """Create *path* from *defaults* if it does not exist; otherwise merge."""
    if path.exists():
        current = read_json(path)
        merged = deep_merge(defaults, current)
    else:
        merged = defaults
    write_json(path, merged)
