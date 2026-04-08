from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import dormammu
from dormammu import _version


class VersionTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop(_version.BUILD_VERSION_ENV, None)
        importlib.reload(dormammu)

    def test_imported_version_prefers_build_override(self) -> None:
        with patch.dict(os.environ, {_version.BUILD_VERSION_ENV: "1.2.3"}, clear=False):
            module = importlib.reload(dormammu)

        self.assertEqual(module.__version__, "1.2.3")

    def test_get_version_uses_installed_metadata_when_available(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            with patch.object(_version, "version", return_value="2.0.0"):
                resolved = _version.get_version()

        self.assertEqual(resolved, "2.0.0")

    def test_get_version_falls_back_to_source_version_without_metadata(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            with patch.object(
                _version,
                "version",
                side_effect=_version.PackageNotFoundError,
            ):
                resolved = _version.get_version()

        self.assertEqual(resolved, _version.SOURCE_VERSION)
