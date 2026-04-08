from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu import doctor


class DoctorTests(unittest.TestCase):
    def test_python_version_check_reports_python_310_as_supported(self) -> None:
        with patch.object(doctor.sys, "version_info", (3, 10, 0, "final", 0)):
            check = doctor._check_python_version()

        self.assertTrue(check.ok)
        self.assertEqual(check.details["required_minimum"], "3.10")

    def test_python_version_check_reports_python_39_as_too_old(self) -> None:
        with patch.object(doctor.sys, "version_info", (3, 9, 18, "final", 0)):
            check = doctor._check_python_version()

        self.assertFalse(check.ok)
        self.assertIn("3.10+ is required", check.summary)

    def test_run_doctor_uses_new_minimum_without_affecting_other_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".agents").mkdir()

            with patch.object(doctor.sys, "version_info", (3, 10, 1, "final", 0)):
                report = doctor.run_doctor(repo_root=root, agent_cli=None)

        checks = {item.name: item for item in report.checks}
        self.assertTrue(checks["python_version"].ok)
        self.assertFalse(checks["agent_cli"].ok)


if __name__ == "__main__":
    unittest.main()
