from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.cli import main


class CliTests(unittest.TestCase):
    def test_show_config_prints_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["show-config", "--repo-root", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["repo_root"], str(root))

    def test_init_state_creates_bootstrap_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "init-state",
                        "--repo-root",
                        str(root),
                        "--goal",
                        "CLI bootstrap",
                        "--roadmap-phase",
                        "phase_1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue((root / ".dev" / "DASHBOARD.md").exists())
            self.assertEqual(payload["logs_dir"], str(root / ".dev" / "logs"))

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text(
            "# DASHBOARD\n\n- Goal: ${goal}\n",
            encoding="utf-8",
        )
        (templates / "tasks.md.tmpl").write_text(
            "# TASKS\n\n${task_items}\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
