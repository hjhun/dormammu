from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
import sys

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu._cli_handlers import (
    _DEFAULT_MANAGED_PROCESS_TIMEOUT_SECONDS,
    _with_managed_process_timeout,
)
from dormammu.config import AppConfig


class ManagedProcessTimeoutTests(unittest.TestCase):
    def test_applies_default_timeout_when_config_is_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = AppConfig.load(repo_root=root, discover=False)

            updated = _with_managed_process_timeout(config)

            self.assertIsNone(config.process_timeout_seconds)
            self.assertEqual(
                updated.process_timeout_seconds,
                _DEFAULT_MANAGED_PROCESS_TIMEOUT_SECONDS,
            )

    def test_preserves_explicit_timeout_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = AppConfig.load(repo_root=root, discover=False).with_overrides(
                process_timeout_seconds=42,
            )

            updated = _with_managed_process_timeout(config)

            self.assertEqual(updated.process_timeout_seconds, 42)


if __name__ == "__main__":
    unittest.main()
