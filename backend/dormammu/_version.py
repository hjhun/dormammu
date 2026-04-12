from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

SOURCE_VERSION = "0.4.0"
BUILD_VERSION_ENV = "DORMAMMU_BUILD_VERSION"


def get_version() -> str:
    override = os.environ.get(BUILD_VERSION_ENV)
    if override:
        return override

    try:
        return version("dormammu")
    except PackageNotFoundError:
        return SOURCE_VERSION
