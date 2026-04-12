from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

BUILD_VERSION_ENV = "DORMAMMU_BUILD_VERSION"


def _read_source_version() -> str:
    """Walk up from this file to find the VERSION file at the repo root."""
    path = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = path / "VERSION"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
        path = path.parent
    return "0.0.0"


SOURCE_VERSION = _read_source_version()


def get_version() -> str:
    override = os.environ.get(BUILD_VERSION_ENV)
    if override:
        return override

    try:
        return version("dormammu")
    except PackageNotFoundError:
        return SOURCE_VERSION
