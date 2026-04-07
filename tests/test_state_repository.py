from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.state import StateRepository


class StateRepositoryTests(unittest.TestCase):
    def test_ensure_bootstrap_state_creates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Bootstrap test goal")

            self.assertTrue(artifacts.dashboard.exists())
            self.assertTrue(artifacts.tasks.exists())
            self.assertTrue(artifacts.session.exists())
            self.assertTrue(artifacts.workflow_state.exists())
            self.assertTrue(artifacts.logs_dir.exists())

            dashboard = artifacts.dashboard.read_text(encoding="utf-8")
            self.assertIn("Bootstrap test goal", dashboard)

    def test_ensure_bootstrap_state_merges_existing_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            dev_dir = root / ".dev"
            dev_dir.mkdir(parents=True, exist_ok=True)
            session_path = dev_dir / "session.json"
            session_path.write_text(
                json.dumps({"session_id": "existing", "custom": {"answer": 42}}),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state()

            merged = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["session_id"], "existing")
            self.assertEqual(merged["custom"]["answer"], 42)
            self.assertIn("active_phase", merged)

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
