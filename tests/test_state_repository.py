from __future__ import annotations

import json
import os
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
            self.assertTrue(artifacts.plan.exists())
            self.assertTrue(artifacts.session.exists())
            self.assertTrue(artifacts.workflow_state.exists())
            self.assertTrue(artifacts.logs_dir.exists())
            self.assertIn(".dev/sessions/", str(artifacts.dashboard))
            root_session_index = json.loads((root / ".dev" / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(
                root_session_index["active_session_id"],
                repository.read_session_state()["session_id"],
            )

            dashboard = artifacts.dashboard.read_text(encoding="utf-8")
            self.assertIn("Bootstrap test goal", dashboard)

            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            self.assertEqual(workflow_state["state_schema_version"], 6)
            self.assertEqual(
                workflow_state["operator_sync"]["tasks"]["pending_tasks"],
                3,
            )
            self.assertEqual(
                workflow_state["operator_sync"]["tasks"]["next_pending_task"],
                "Phase 1. Confirm the goal and success criteria for Bootstrap test goal",
            )
            self.assertEqual(workflow_state["bootstrap"]["goal"], "Bootstrap test goal")
            self.assertIn("AGENTS.md", workflow_state["bootstrap"]["repo_guidance"]["rule_files"])

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

            active_session_id = json.loads((root / ".dev" / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            migrated_session_path = root / ".dev" / "sessions" / active_session_id / "session.json"
            merged = json.loads(migrated_session_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["session_id"], "existing")
            self.assertEqual(merged["custom"]["answer"], 42)
            self.assertIn("active_phase", merged)

    def test_ensure_bootstrap_state_syncs_existing_task_checkboxes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            dev_dir = root / ".dev"
            dev_dir.mkdir(parents=True, exist_ok=True)
            legacy_tasks_path = dev_dir / "TASKS.md"
            legacy_tasks_path.write_text(
                "\n".join(
                    [
                        "# TASKS",
                        "",
                        "## Prompt-Derived Development Queue",
                        "",
                        "- [O] Phase 1. Finish the first slice",
                        "- [ ] Phase 2. Validate the second slice",
                        "",
                        "## Resume Checkpoint",
                        "",
                        "Resume from the first unchecked task.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state()
            session_plan_path = artifacts.plan
            self.assertIn("Finish the first slice", session_plan_path.read_text(encoding="utf-8"))

            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            task_sync = workflow_state["operator_sync"]["tasks"]
            self.assertEqual(task_sync["total_tasks"], 2)
            self.assertEqual(task_sync["completed_tasks"], 1)
            self.assertEqual(task_sync["pending_tasks"], 1)
            self.assertEqual(task_sync["next_pending_task"], "Phase 2. Validate the second slice")
            self.assertEqual(
                task_sync["resume_checkpoint"],
                "Resume from the first unchecked task.",
            )

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            self.assertEqual(
                session_state["task_sync"]["completed_tasks"],
                1,
            )

    def test_start_new_session_archives_previous_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Original goal")
            original_session = repository.read_session_state()["session_id"]
            repository.write_supervisor_report("# Report\n")
            repository.write_continuation_prompt("continue here")

            repository.start_new_session(
                goal="Fresh goal",
                active_roadmap_phase_ids=["phase_7"],
                session_id="phase7-multi-session",
            )

            current_session = repository.read_session_state()
            self.assertEqual(current_session["session_id"], "phase7-multi-session")
            self.assertEqual(current_session["run_type"], "session")
            root_index = json.loads((root / ".dev" / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(root_index["active_session_id"], "phase7-multi-session")
            self.assertFalse((root / ".dev" / "DASHBOARD.md").exists())

            archived_dir = root / ".dev" / "sessions" / original_session
            self.assertTrue((archived_dir / "session.json").exists())
            self.assertTrue((archived_dir / "workflow_state.json").exists())
            self.assertTrue((root / ".dev" / "sessions" / "phase7-multi-session" / "DASHBOARD.md").exists())
            self.assertTrue((archived_dir / "supervisor_report.md").exists())
            self.assertTrue((archived_dir / "continuation_prompt.txt").exists())
            self.assertTrue((root / ".dev" / "sessions" / "phase7-multi-session" / "PLAN.md").exists())

    def test_list_sessions_marks_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Original goal")
            repository.start_new_session(
                goal="Second goal",
                active_roadmap_phase_ids=["phase_7"],
                session_id="phase7-second",
            )

            sessions = repository.list_sessions()

            self.assertEqual(len(sessions), 2)
            active_sessions = [item for item in sessions if item["is_active"]]
            self.assertEqual(len(active_sessions), 1)
            self.assertEqual(active_sessions[0]["session_id"], "phase7-second")

    def test_restore_session_switches_active_pointer_without_copying_session_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Original goal")
            original_session = repository.read_session_state()["session_id"]
            (root / ".dev" / "sessions" / original_session / "DASHBOARD.md").write_text(
                "# DASHBOARD\n\nOriginal session\n",
                encoding="utf-8",
            )
            repository.write_supervisor_report("# Original report\n")

            repository.start_new_session(
                goal="Second goal",
                active_roadmap_phase_ids=["phase_7"],
                session_id="phase7-second",
            )

            repository.restore_session(original_session)

            restored_session = repository.read_session_state()
            self.assertEqual(restored_session["session_id"], original_session)
            self.assertIn(
                "Original session",
                (root / ".dev" / "sessions" / original_session / "DASHBOARD.md").read_text(
                    encoding="utf-8"
                ),
            )
            root_index = json.loads((root / ".dev" / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(root_index["active_session_id"], original_session)
            self.assertFalse((root / ".dev" / "supervisor_report.md").exists())

    def test_session_scoped_bootstrap_keeps_active_root_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.start_new_session(
                goal="Active session goal",
                active_roadmap_phase_ids=["phase_7"],
                session_id="active-session",
            )
            active_root_index = (root / ".dev" / "session.json").read_text(encoding="utf-8")

            session_repository = StateRepository(config, session_id="parallel-session")
            session_repository.ensure_bootstrap_state(
                goal="Parallel session goal",
                active_roadmap_phase_ids=["phase_7"],
            )

            self.assertEqual(
                active_root_index,
                (root / ".dev" / "session.json").read_text(encoding="utf-8"),
            )
            parallel_dashboard = (
                root / ".dev" / "sessions" / "parallel-session" / "DASHBOARD.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Parallel session goal", parallel_dashboard)
            self.assertTrue((root / ".dev" / "sessions" / "parallel-session" / "PLAN.md").exists())
            self.assertEqual(
                session_repository.read_session_state()["session_id"],
                "parallel-session",
            )

    def test_persist_input_prompt_copies_prompt_into_session_and_global_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            home = Path(tmpdir) / "home"
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={"HOME": str(home), **{key: value for key, value in os.environ.items() if key != "HOME"}},
            )
            repository = StateRepository(config)
            repository.start_new_session(goal="Prompt goal", session_id="prompt-session")

            source_prompt = root / "PROMPT.md"
            source_prompt.write_text("# Prompt\n\nImplement prompt-driven bootstrap.\n", encoding="utf-8")
            prompt_path = repository.persist_input_prompt(
                prompt_text=source_prompt.read_text(encoding="utf-8"),
                source_path=source_prompt,
            )

            self.assertEqual(prompt_path.read_text(encoding="utf-8"), source_prompt.read_text(encoding="utf-8"))
            global_prompt = home / ".dormammu" / "sessions" / "prompt-session" / ".dev" / "PROMPT.md"
            self.assertTrue(global_prompt.exists())
            self.assertEqual(global_prompt.read_text(encoding="utf-8"), source_prompt.read_text(encoding="utf-8"))

    def test_ensure_bootstrap_state_regenerates_dashboard_and_plan_when_prompt_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(
                goal="Original goal",
                prompt_text="Implement alpha support.",
            )

            artifacts.dashboard.write_text("# DASHBOARD\n\nstale dashboard\n", encoding="utf-8")
            artifacts.plan.write_text(
                "# PLAN\n\n## Prompt-Derived Implementation Plan\n\n- [O] Phase 1. Stale work\n",
                encoding="utf-8",
            )

            repository.ensure_bootstrap_state(
                goal="Updated goal",
                prompt_text="Implement beta support.",
            )

            refreshed_dashboard = artifacts.dashboard.read_text(encoding="utf-8")
            refreshed_plan = artifacts.plan.read_text(encoding="utf-8")
            self.assertNotIn("stale dashboard", refreshed_dashboard)
            self.assertNotIn("Stale work", refreshed_plan)
            self.assertIn("Updated goal", refreshed_dashboard)
            self.assertIn("Phase 1. Implement beta support", refreshed_plan)

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text(
            "\n".join(
                [
                    "# DASHBOARD",
                    "",
                    "## Actual Progress",
                    "",
                    "- Goal: ${goal}",
                    "- Prompt-driven scope: ${active_delivery_slice}",
                    "- Active roadmap focus:",
                    "${active_roadmap_focus}",
                    "- Current workflow phase: ${active_phase}",
                    "- Last completed workflow phase: ${last_completed_phase}",
                    "- Supervisor verdict: `${supervisor_verdict}`",
                    "- Escalation status: `${escalation_status}`",
                    "- Resume point: ${resume_point}",
                    "",
                    "## In Progress",
                    "",
                    "${next_action}",
                    "",
                    "## Progress Notes",
                    "",
                    "${notes}",
                    "",
                    "## Risks And Watchpoints",
                    "",
                    "${risks_and_watchpoints}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (templates / "plan.md.tmpl").write_text(
            "\n".join(
                [
                    "# PLAN",
                    "",
                    "## Prompt-Derived Implementation Plan",
                    "",
                    "${task_items}",
                    "",
                    "## Resume Checkpoint",
                    "",
                    "${resume_checkpoint}",
                    "",
                ]
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
