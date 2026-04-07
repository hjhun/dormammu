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

            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            self.assertEqual(workflow_state["state_schema_version"], 3)
            self.assertEqual(
                workflow_state["operator_sync"]["tasks"]["pending_tasks"],
                3,
            )
            self.assertEqual(
                workflow_state["operator_sync"]["tasks"]["next_pending_task"],
                "Confirm the current user goal",
            )

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

    def test_ensure_bootstrap_state_syncs_existing_task_checkboxes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            dev_dir = root / ".dev"
            dev_dir.mkdir(parents=True, exist_ok=True)
            tasks_path = dev_dir / "TASKS.md"
            tasks_path.write_text(
                "\n".join(
                    [
                        "# TASKS",
                        "",
                        "## Current Workflow",
                        "",
                        "- [O] Finish the first slice",
                        "- [ ] Validate the second slice",
                        "",
                        "## Resume Checkpoint",
                        "",
                        "Resume from the first unchecked task.",
                        "",
                        "## Completion Rule",
                        "",
                        "Keep markdown and machine state aligned.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state()

            self.assertIn("Finish the first slice", tasks_path.read_text(encoding="utf-8"))

            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            task_sync = workflow_state["operator_sync"]["tasks"]
            self.assertEqual(task_sync["total_tasks"], 2)
            self.assertEqual(task_sync["completed_tasks"], 1)
            self.assertEqual(task_sync["pending_tasks"], 1)
            self.assertEqual(task_sync["next_pending_task"], "Validate the second slice")
            self.assertEqual(
                task_sync["resume_checkpoint"],
                "Resume from the first unchecked task.",
            )

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            self.assertEqual(
                session_state["task_sync"]["completed_tasks"],
                1,
            )

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text(
            "\n".join(
                [
                    "# DASHBOARD",
                    "",
                    "## Workflow Summary",
                    "",
                    "- Goal: ${goal}",
                    "- Active delivery slice: ${active_delivery_slice}",
                    "- Current workflow phase: ${active_phase}",
                    "- Last completed workflow phase: ${last_completed_phase}",
                    "- Supervisor verdict: `${supervisor_verdict}`",
                    "- Escalation status: `${escalation_status}`",
                    "- Resume point: ${resume_point}",
                    "",
                    "## Next Action",
                    "",
                    "${next_action}",
                    "",
                    "## Notes",
                    "",
                    "${notes}",
                    "",
                    "## Active Roadmap Focus",
                    "",
                    "${active_roadmap_focus}",
                    "",
                    "## Risks And Watchpoints",
                    "",
                    "${risks_and_watchpoints}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (templates / "tasks.md.tmpl").write_text(
            "\n".join(
                [
                    "# TASKS",
                    "",
                    "## Current Workflow",
                    "",
                    "${task_items}",
                    "",
                    "## Resume Checkpoint",
                    "",
                    "${resume_checkpoint}",
                    "",
                    "## Completion Rule",
                    "",
                    "${completion_rule}",
                    "",
                ]
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
