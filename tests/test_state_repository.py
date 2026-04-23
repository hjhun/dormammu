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
from dormammu.worktree import ManagedWorktree, WorktreeLifecycleStatus, WorktreeOwner


class StateRepositoryTests(unittest.TestCase):
    @staticmethod
    def _display_path(path: Path, root: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)

    def test_ensure_bootstrap_state_creates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Bootstrap test goal")

            self.assertTrue(artifacts.dashboard.exists())
            self.assertTrue(artifacts.plan.exists())
            self.assertTrue(artifacts.tasks.exists())
            self.assertTrue(artifacts.session.exists())
            self.assertTrue(artifacts.workflow_state.exists())
            self.assertTrue(artifacts.logs_dir.exists())
            self.assertIn(str(config.sessions_dir), str(artifacts.dashboard))
            root_session_index = json.loads(
                (config.base_dev_dir / "session.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                root_session_index["active_session_id"],
                repository.read_session_state()["session_id"],
            )

            dashboard = artifacts.dashboard.read_text(encoding="utf-8")
            self.assertIn("Bootstrap test goal", dashboard)

            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            self.assertEqual(workflow_state["state_schema_version"], 9)
            self.assertEqual(
                workflow_state["operator_sync"]["tasks"]["pending_tasks"],
                3,
            )
            self.assertEqual(
                workflow_state["operator_sync"]["tasks"]["source"],
                self._display_path(artifacts.tasks, root),
            )
            self.assertEqual(
                workflow_state["operator_sync"]["tasks"]["next_pending_task"],
                "Phase 1. Confirm the goal and success criteria for Bootstrap test goal",
            )
            self.assertEqual(workflow_state["bootstrap"]["goal"], "Bootstrap test goal")
            self.assertIn("AGENTS.md", workflow_state["bootstrap"]["repo_guidance"]["rule_files"])

    def test_record_runtime_skill_resolution_persists_structured_skill_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            skill_path = root / "agents" / "skills" / "designing-agent" / "SKILL.md"
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            skill_path.write_text(
                """---
schema_version: 1
name: designing-agent
description: Project designing skill
---

# designing-agent

Use this skill in state repository tests.
""",
                encoding="utf-8",
            )

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Runtime skills state")

            runtime_skills = repository.record_runtime_skill_resolution(role="designer")

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            root_session_index = json.loads(
                (config.base_dev_dir / "session.json").read_text(encoding="utf-8")
            )

            self.assertEqual(runtime_skills["active_role"], "designer")
            self.assertEqual(session_state["runtime_skills"]["active_role"], "designer")
            self.assertEqual(
                session_state["runtime_skills"]["latest"]["summary"]["custom_visible_count"],
                1,
            )
            self.assertIn(
                "designing-agent",
                [
                    entry["name"]
                    for entry in workflow_state["runtime_skills"]["latest"]["visibility"]["visible"]
                ],
            )
            self.assertIn("AGENTS.md", workflow_state["bootstrap"]["repo_guidance"]["rule_files"])
            self.assertEqual(
                root_session_index["current_session"]["runtime_skills"]["active_role"],
                "designer",
            )

    def test_record_runtime_skill_resolution_keeps_built_in_only_visibility_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Built-in skills only")

            runtime_skills = repository.record_runtime_skill_resolution(role="planner")

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            root_session_index = json.loads(
                (config.base_dev_dir / "session.json").read_text(encoding="utf-8")
            )
            root_workflow_index = json.loads(
                (config.base_dev_dir / "workflow_state.json").read_text(encoding="utf-8")
            )

            self.assertEqual(runtime_skills["active_role"], "planner")
            self.assertEqual(runtime_skills["latest"]["summary"]["custom_visible_count"], 0)
            self.assertFalse(runtime_skills["latest"]["summary"]["interesting_for_operator"])
            self.assertEqual(runtime_skills["latest"]["prompt_lines"], [])
            self.assertEqual(session_state["runtime_skills"]["latest"]["prompt_lines"], [])
            self.assertEqual(workflow_state["runtime_skills"]["latest"]["prompt_lines"], [])
            expected_root_summary = {
                "active_role": "planner",
                "profile_name": runtime_skills["latest"]["profile"]["name"],
                "profile_source": runtime_skills["latest"]["profile"]["source"],
                "selected_count": runtime_skills["latest"]["summary"]["selected_count"],
                "visible_count": runtime_skills["latest"]["summary"]["visible_count"],
                "hidden_count": runtime_skills["latest"]["summary"]["hidden_count"],
                "preloaded_count": runtime_skills["latest"]["summary"]["preloaded_count"],
                "missing_preload_count": runtime_skills["latest"]["summary"]["missing_preload_count"],
                "shadowed_count": runtime_skills["latest"]["summary"]["shadowed_count"],
                "custom_visible_count": runtime_skills["latest"]["summary"]["custom_visible_count"],
                "interesting_for_operator": runtime_skills["latest"]["summary"]["interesting_for_operator"],
            }
            self.assertEqual(
                root_session_index["current_session"]["runtime_skills"],
                expected_root_summary,
            )
            self.assertEqual(
                root_workflow_index["current_session"]["runtime_skills"],
                expected_root_summary,
            )

    def test_worktree_state_reads_as_empty_without_persisting_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="No worktree state")

            self.assertTrue(repository.read_session_worktree_state().is_empty)
            self.assertTrue(repository.read_workflow_worktree_state().is_empty)

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            self.assertNotIn("worktrees", session_state)
            self.assertNotIn("worktrees", workflow_state)

    def test_upsert_managed_worktree_persists_metadata_in_session_and_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Persist worktree state")

            session_id = repository.read_session_state()["session_id"]
            worktree = ManagedWorktree(
                worktree_id="phase-4-review",
                source_repo_root=root.resolve(),
                isolated_path=(root / "managed-worktrees" / "phase-4-review").resolve(),
                owner=WorktreeOwner(
                    session_id=session_id,
                    run_id="run-001",
                    agent_role="developer",
                ),
                status=WorktreeLifecycleStatus.ACTIVE,
            )

            repository.upsert_managed_worktree(worktree, active=True)

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            self.assertEqual(session_state["worktrees"]["active_worktree_id"], worktree.worktree_id)
            self.assertEqual(workflow_state["worktrees"]["active_worktree_id"], worktree.worktree_id)
            self.assertEqual(session_state["worktrees"]["managed"], [worktree.to_dict()])
            self.assertEqual(workflow_state["worktrees"]["managed"], [worktree.to_dict()])

    def test_upsert_managed_worktree_normalizes_active_registry_invariants(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Normalize worktree state")

            session_id = repository.read_session_state()["session_id"]
            first = ManagedWorktree(
                worktree_id="first-active",
                source_repo_root=root.resolve(),
                isolated_path=(root / "managed-worktrees" / "first-active").resolve(),
                owner=WorktreeOwner(session_id=session_id, run_id="run-101"),
                status=WorktreeLifecycleStatus.ACTIVE,
            )
            second = ManagedWorktree(
                worktree_id="second-selected",
                source_repo_root=root.resolve(),
                isolated_path=(root / "managed-worktrees" / "second-selected").resolve(),
                owner=WorktreeOwner(session_id=session_id, run_id="run-102"),
                status=WorktreeLifecycleStatus.PLANNED,
            )

            repository.upsert_managed_worktree(first, active=True)
            repository.upsert_managed_worktree(second, active=True)

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            for payload in (session_state, workflow_state):
                self.assertEqual(payload["worktrees"]["active_worktree_id"], "second-selected")
                managed_by_id = {
                    record["worktree_id"]: record for record in payload["worktrees"]["managed"]
                }
                self.assertEqual(managed_by_id["first-active"]["status"], "planned")
                self.assertEqual(managed_by_id["second-selected"]["status"], "active")

    def test_restore_session_preserves_managed_worktree_state_for_resume_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Resume worktree state")
            original_session = repository.read_session_state()["session_id"]

            worktree = ManagedWorktree(
                worktree_id="resume-check",
                source_repo_root=root.resolve(),
                isolated_path=(root / "managed-worktrees" / "resume-check").resolve(),
                owner=WorktreeOwner(session_id=original_session, run_id="run-777"),
                status=WorktreeLifecycleStatus.ACTIVE,
            )
            repository.upsert_managed_worktree(worktree, active=True)

            repository.start_new_session(goal="Temporary session", session_id="temp-session")
            repository.restore_session(original_session)

            session_worktrees = repository.read_session_worktree_state()
            workflow_worktrees = repository.read_workflow_worktree_state()
            self.assertEqual(session_worktrees.active_worktree_id, "resume-check")
            self.assertEqual(workflow_worktrees.active_worktree_id, "resume-check")
            self.assertEqual(session_worktrees.managed[0].to_dict(), worktree.to_dict())
            self.assertEqual(workflow_worktrees.managed[0].to_dict(), worktree.to_dict())

    def test_restore_session_updates_repository_scope_to_target_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Session A")
            original_session = repository.read_session_state()["session_id"]

            repository.start_new_session(goal="Session B", session_id="session-b")

            repository.restore_session(original_session)

            self.assertEqual(repository.session_id, original_session)
            self.assertEqual(repository.dev_dir, config.sessions_dir / original_session)
            self.assertEqual(repository.logs_dir, config.sessions_dir / original_session / "logs")
            self.assertEqual(repository.read_session_state()["session_id"], original_session)

    def test_restore_session_repairs_stale_loop_request_expected_roadmap_phase_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(
                goal="Restore roadmap sync",
                active_roadmap_phase_ids=["phase_4"],
            )
            original_session = repository.read_session_state()["session_id"]
            session_repository = repository.for_session(original_session)

            session_state = session_repository.read_session_state()
            session_state["active_roadmap_phase_ids"] = ["phase_6"]
            session_state["loop"] = {
                "status": "running",
                "request": {"expected_roadmap_phase_id": "phase_4"},
            }
            session_repository.state_file("session.json").write_text(
                json.dumps(session_state, indent=2) + "\n",
                encoding="utf-8",
            )

            workflow_state = session_repository.read_workflow_state()
            workflow_state.setdefault("roadmap", {})
            workflow_state["roadmap"]["active_phase_ids"] = ["phase_6"]
            workflow_state["loop"] = {
                "status": "running",
                "request": {"expected_roadmap_phase_id": "phase_4"},
            }
            session_repository.state_file("workflow_state.json").write_text(
                json.dumps(workflow_state, indent=2) + "\n",
                encoding="utf-8",
            )

            repository.start_new_session(goal="Temporary session", session_id="temp-session")
            repository.restore_session(original_session)

            repaired_session = repository.read_session_state()
            repaired_workflow = repository.read_workflow_state()
            root_index = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))

            self.assertEqual(repaired_session["active_roadmap_phase_ids"], ["phase_6"])
            self.assertEqual(repaired_session["loop"]["request"]["expected_roadmap_phase_id"], "phase_6")
            self.assertEqual(repaired_workflow["roadmap"]["active_phase_ids"], ["phase_6"])
            self.assertEqual(repaired_workflow["loop"]["request"]["expected_roadmap_phase_id"], "phase_6")
            self.assertEqual(root_index["current_session"]["active_roadmap_phase_ids"], ["phase_6"])

    def test_forget_managed_worktree_clears_root_session_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Forget worktree state")

            session_id = repository.read_session_state()["session_id"]
            worktree = ManagedWorktree(
                worktree_id="cleanup-me",
                source_repo_root=root.resolve(),
                isolated_path=(root / "managed-worktrees" / "cleanup-me").resolve(),
                owner=WorktreeOwner(session_id=session_id, run_id="run-222"),
                status=WorktreeLifecycleStatus.ACTIVE,
            )
            repository.upsert_managed_worktree(worktree, active=True)

            root_session = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(root_session["current_session"]["active_worktree_id"], "cleanup-me")
            self.assertEqual(root_session["current_session"]["managed_worktree_count"], 1)

            repository.forget_managed_worktree("cleanup-me")

            root_session = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            self.assertIsNone(root_session["current_session"]["active_worktree_id"])
            self.assertEqual(root_session["current_session"]["managed_worktree_count"], 0)
            self.assertTrue(repository.read_session_worktree_state().is_empty)
            self.assertTrue(repository.read_workflow_worktree_state().is_empty)

    def test_read_worktree_state_is_backward_compatible_with_legacy_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Legacy worktree payload")

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            session_state["state_schema_version"] = 7
            workflow_state["state_schema_version"] = 7
            session_state.pop("worktrees", None)
            workflow_state.pop("worktrees", None)
            artifacts.session.write_text(json.dumps(session_state, indent=2) + "\n", encoding="utf-8")
            artifacts.workflow_state.write_text(
                json.dumps(workflow_state, indent=2) + "\n",
                encoding="utf-8",
            )

            session_worktrees = repository.read_session_worktree_state()
            workflow_worktrees = repository.read_workflow_worktree_state()
            self.assertTrue(session_worktrees.is_empty)
            self.assertTrue(workflow_worktrees.is_empty)

    def test_read_worktree_state_normalizes_conflicting_active_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Normalize conflicting worktree payload")

            session_id = repository.read_session_state()["session_id"]
            conflicting_payload = {
                "active_worktree_id": "selected",
                "managed": [
                    ManagedWorktree(
                        worktree_id="selected",
                        source_repo_root=root.resolve(),
                        isolated_path=(root / "managed-worktrees" / "selected").resolve(),
                        owner=WorktreeOwner(session_id=session_id, run_id="run-201"),
                        status=WorktreeLifecycleStatus.PLANNED,
                    ).to_dict(),
                    ManagedWorktree(
                        worktree_id="stale-active",
                        source_repo_root=root.resolve(),
                        isolated_path=(root / "managed-worktrees" / "stale-active").resolve(),
                        owner=WorktreeOwner(session_id=session_id, run_id="run-202"),
                        status=WorktreeLifecycleStatus.ACTIVE,
                    ).to_dict(),
                ],
            }
            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            session_state["worktrees"] = conflicting_payload
            workflow_state["worktrees"] = conflicting_payload
            artifacts.session.write_text(json.dumps(session_state, indent=2) + "\n", encoding="utf-8")
            artifacts.workflow_state.write_text(
                json.dumps(workflow_state, indent=2) + "\n",
                encoding="utf-8",
            )

            for worktrees in (
                repository.read_session_worktree_state(),
                repository.read_workflow_worktree_state(),
            ):
                self.assertEqual(worktrees.active_worktree_id, "selected")
                managed_by_id = {record.worktree_id: record for record in worktrees.managed}
                self.assertEqual(
                    managed_by_id["selected"].status,
                    WorktreeLifecycleStatus.ACTIVE,
                )
                self.assertEqual(
                    managed_by_id["stale-active"].status,
                    WorktreeLifecycleStatus.PLANNED,
                )

    def test_read_worktree_state_deduplicates_duplicate_worktree_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Deduplicate worktree payload")

            session_id = repository.read_session_state()["session_id"]
            duplicate_payload = {
                "active_worktree_id": "duplicate",
                "managed": [
                    ManagedWorktree(
                        worktree_id="duplicate",
                        source_repo_root=root.resolve(),
                        isolated_path=(root / "managed-worktrees" / "duplicate-old").resolve(),
                        owner=WorktreeOwner(session_id=session_id, run_id="run-301"),
                        status=WorktreeLifecycleStatus.PLANNED,
                    ).to_dict(),
                    ManagedWorktree(
                        worktree_id="duplicate",
                        source_repo_root=root.resolve(),
                        isolated_path=(root / "managed-worktrees" / "duplicate-new").resolve(),
                        owner=WorktreeOwner(session_id=session_id, run_id="run-302"),
                        status=WorktreeLifecycleStatus.ACTIVE,
                    ).to_dict(),
                ],
            }
            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            session_state["worktrees"] = duplicate_payload
            workflow_state["worktrees"] = duplicate_payload
            artifacts.session.write_text(json.dumps(session_state, indent=2) + "\n", encoding="utf-8")
            artifacts.workflow_state.write_text(
                json.dumps(workflow_state, indent=2) + "\n",
                encoding="utf-8",
            )

            for worktrees in (
                repository.read_session_worktree_state(),
                repository.read_workflow_worktree_state(),
            ):
                self.assertEqual(worktrees.active_worktree_id, "duplicate")
                self.assertEqual(len(worktrees.managed), 1)
                self.assertEqual(worktrees.managed[0].owner.run_id, "run-302")
                self.assertEqual(
                    worktrees.managed[0].status,
                    WorktreeLifecycleStatus.ACTIVE,
                )

    def test_upsert_managed_worktree_collapses_duplicate_registry_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Collapse duplicate registry entries")

            session_id = repository.read_session_state()["session_id"]
            duplicate_payload = {
                "active_worktree_id": "duplicate",
                "managed": [
                    ManagedWorktree(
                        worktree_id="duplicate",
                        source_repo_root=root.resolve(),
                        isolated_path=(root / "managed-worktrees" / "duplicate-a").resolve(),
                        owner=WorktreeOwner(session_id=session_id, run_id="run-401"),
                        status=WorktreeLifecycleStatus.ACTIVE,
                    ).to_dict(),
                    ManagedWorktree(
                        worktree_id="duplicate",
                        source_repo_root=root.resolve(),
                        isolated_path=(root / "managed-worktrees" / "duplicate-b").resolve(),
                        owner=WorktreeOwner(session_id=session_id, run_id="run-402"),
                        status=WorktreeLifecycleStatus.PLANNED,
                    ).to_dict(),
                ],
            }
            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            session_state["worktrees"] = duplicate_payload
            workflow_state["worktrees"] = duplicate_payload
            artifacts.session.write_text(json.dumps(session_state, indent=2) + "\n", encoding="utf-8")
            artifacts.workflow_state.write_text(
                json.dumps(workflow_state, indent=2) + "\n",
                encoding="utf-8",
            )

            replacement = ManagedWorktree(
                worktree_id="duplicate",
                source_repo_root=root.resolve(),
                isolated_path=(root / "managed-worktrees" / "duplicate-replacement").resolve(),
                owner=WorktreeOwner(session_id=session_id, run_id="run-403"),
                status=WorktreeLifecycleStatus.PLANNED,
            )

            repository.upsert_managed_worktree(replacement, active=True)

            session_state = json.loads(artifacts.session.read_text(encoding="utf-8"))
            workflow_state = json.loads(artifacts.workflow_state.read_text(encoding="utf-8"))
            for payload in (session_state, workflow_state):
                self.assertEqual(payload["worktrees"]["active_worktree_id"], "duplicate")
                self.assertEqual(payload["worktrees"]["managed"], [
                    {
                        **replacement.to_dict(),
                        "status": "active",
                    }
                ])

    def test_upsert_managed_worktree_refreshes_root_index_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Refresh root schema version")

            for filename in ("session.json", "workflow_state.json"):
                root_index_path = config.base_dev_dir / filename
                root_index = json.loads(root_index_path.read_text(encoding="utf-8"))
                root_index["state_schema_version"] = 7
                root_index_path.write_text(
                    json.dumps(root_index, indent=2) + "\n",
                    encoding="utf-8",
                )

            session_id = repository.read_session_state()["session_id"]
            worktree = ManagedWorktree(
                worktree_id="refresh-root-index",
                source_repo_root=root.resolve(),
                isolated_path=(root / "managed-worktrees" / "refresh-root-index").resolve(),
                owner=WorktreeOwner(session_id=session_id, run_id="run-501"),
                status=WorktreeLifecycleStatus.ACTIVE,
            )

            repository.upsert_managed_worktree(worktree, active=True)

            root_session = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            root_workflow = json.loads(
                (config.base_dev_dir / "workflow_state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(root_session["state_schema_version"], 9)
            self.assertEqual(root_workflow["state_schema_version"], 9)
            self.assertEqual(root_session["current_session"]["active_worktree_id"], worktree.worktree_id)
            self.assertEqual(root_workflow["current_session"]["active_worktree_id"], worktree.worktree_id)
            self.assertEqual(root_session["current_session"]["managed_worktree_count"], 1)
            self.assertEqual(root_workflow["current_session"]["managed_worktree_count"], 1)

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

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state()

            active_session_id = json.loads(
                (config.base_dev_dir / "session.json").read_text(encoding="utf-8")
            )[
                "active_session_id"
            ]
            migrated_session_path = config.sessions_dir / active_session_id / "session.json"
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

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state()
            session_plan_path = artifacts.plan
            self.assertIn("Finish the first slice", session_plan_path.read_text(encoding="utf-8"))
            self.assertIn("Finish the first slice", artifacts.tasks.read_text(encoding="utf-8"))

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

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
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
            root_index = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(root_index["active_session_id"], "phase7-multi-session")
            self.assertTrue((config.base_dev_dir / "DASHBOARD.md").exists())
            self.assertTrue((config.base_dev_dir / "PLAN.md").exists())

            archived_dir = config.sessions_dir / original_session
            self.assertTrue((archived_dir / "session.json").exists())
            self.assertTrue((archived_dir / "workflow_state.json").exists())
            self.assertTrue((config.sessions_dir / "phase7-multi-session" / "DASHBOARD.md").exists())
            self.assertTrue((archived_dir / "supervisor_report.md").exists())
            self.assertTrue((archived_dir / "continuation_prompt.txt").exists())
            self.assertTrue((config.sessions_dir / "phase7-multi-session" / "PLAN.md").exists())

    def test_start_new_session_uses_prompt_summary_when_goal_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)

            repository.start_new_session(
                prompt_text=(
                    "Create a small casual browser game in this workspace using "
                    "plain HTML, CSS, and JavaScript."
                ),
                active_roadmap_phase_ids=["phase_4"],
                session_id="prompt-derived-goal",
            )

            session_state = repository.read_session_state()
            workflow_state = repository.read_workflow_state()
            self.assertEqual(
                session_state["bootstrap"]["goal"],
                "Create a small casual browser game in this workspace using plain HTML, CSS, and JavaScript.",
            )
            self.assertEqual(
                workflow_state["bootstrap"]["goal"],
                session_state["bootstrap"]["goal"],
            )

    def test_start_new_session_root_workflow_index_mirrors_intake_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)

            repository.start_new_session(
                prompt_text="Implement a small browser game with tests and verification.",
                active_roadmap_phase_ids=["phase_4"],
                session_id="mirrored-policy-session",
            )

            root_workflow = json.loads(
                (config.base_dev_dir / "workflow_state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                root_workflow["intake"]["request_class"],
                "full_workflow",
            )
            self.assertEqual(
                root_workflow["workflow_policy"]["request_class"],
                "full_workflow",
            )
            self.assertEqual(
                root_workflow["bootstrap"]["goal"],
                "Implement a small browser game with tests and verification.",
            )

    def test_list_sessions_marks_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
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

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Original goal")
            original_session = repository.read_session_state()["session_id"]
            (config.sessions_dir / original_session / "DASHBOARD.md").write_text(
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
                (config.sessions_dir / original_session / "DASHBOARD.md").read_text(
                    encoding="utf-8"
                ),
            )
            root_index = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(root_index["active_session_id"], original_session)
            self.assertFalse((config.base_dev_dir / "supervisor_report.md").exists())

    def test_write_workflow_state_syncs_session_active_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Workflow sync goal")

            workflow_state = repository.read_workflow_state()
            workflow_state["updated_at"] = "2026-04-20T21:20:00+09:00"
            workflow_state["workflow"]["active_phase"] = "commit"
            repository.write_workflow_state(workflow_state)

            session_state = repository.read_session_state()
            root_index = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(session_state["active_phase"], "commit")
            self.assertEqual(session_state["updated_at"], "2026-04-20T21:20:00+09:00")
            self.assertEqual(root_index["current_session"]["active_phase"], "commit")

    def test_write_workflow_state_syncs_session_active_roadmap_phase_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Workflow roadmap sync goal", active_roadmap_phase_ids=["phase_4"])

            workflow_state = repository.read_workflow_state()
            workflow_state["updated_at"] = "2026-04-20T21:20:01+09:00"
            workflow_state.setdefault("roadmap", {})
            workflow_state["roadmap"]["active_phase_ids"] = ["phase_6"]
            repository.write_workflow_state(workflow_state)

            session_state = repository.read_session_state()
            root_index = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(session_state["active_roadmap_phase_ids"], ["phase_6"])
            self.assertEqual(root_index["current_session"]["active_roadmap_phase_ids"], ["phase_6"])

    def test_write_session_state_syncs_workflow_active_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Session sync goal")

            session_state = repository.read_session_state()
            session_state["updated_at"] = "2026-04-20T21:21:00+09:00"
            session_state["active_phase"] = "final_verification"
            repository.write_session_state(session_state)

            workflow_state = repository.read_workflow_state()
            root_index = json.loads((config.base_dev_dir / "workflow_state.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow_state["workflow"]["active_phase"], "final_verification")
            self.assertEqual(workflow_state["updated_at"], "2026-04-20T21:21:00+09:00")
            self.assertEqual(root_index["current_session"]["session_id"], repository.read_session_state()["session_id"])

    def test_write_session_state_syncs_workflow_active_roadmap_phase_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Session roadmap sync goal", active_roadmap_phase_ids=["phase_4"])

            session_state = repository.read_session_state()
            session_state["updated_at"] = "2026-04-20T21:21:01+09:00"
            session_state["active_roadmap_phase_ids"] = ["phase_6"]
            repository.write_session_state(session_state)

            workflow_state = repository.read_workflow_state()
            root_index = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(workflow_state["roadmap"]["active_phase_ids"], ["phase_6"])
            self.assertEqual(root_index["current_session"]["active_roadmap_phase_ids"], ["phase_6"])

    def test_write_state_pair_keeps_phase_pointer_consistent_when_payloads_disagree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Paired state write")

            session_state = repository.read_session_state()
            workflow_state = repository.read_workflow_state()

            session_state["active_phase"] = "plan"
            session_state["updated_at"] = "2026-04-22T01:10:00+09:00"
            workflow_state["workflow"]["active_phase"] = "final_verification"
            workflow_state["updated_at"] = "2026-04-22T01:10:00+09:00"

            repository.write_state_pair(
                session_payload=session_state,
                workflow_payload=workflow_state,
            )

            paired_session = repository.read_session_state()
            paired_workflow = repository.read_workflow_state()
            root_session = json.loads(
                (config.base_dev_dir / "session.json").read_text(encoding="utf-8")
            )

            self.assertEqual(paired_session["active_phase"], "final_verification")
            self.assertEqual(
                paired_workflow["workflow"]["active_phase"],
                "final_verification",
            )
            self.assertEqual(
                root_session["current_session"]["active_phase"],
                "final_verification",
            )

    def test_write_session_state_syncs_loop_request_expected_roadmap_phase_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Session loop sync goal", active_roadmap_phase_ids=["phase_4"])

            session_state = repository.read_session_state()
            session_state["loop"] = {
                "status": "running",
                "request": {"expected_roadmap_phase_id": "phase_4"},
            }
            repository.write_session_state(session_state)
            workflow_state = repository.read_workflow_state()
            workflow_state["loop"] = {
                "status": "running",
                "request": {"expected_roadmap_phase_id": "phase_4"},
            }
            repository.write_workflow_state(workflow_state)

            session_state = repository.read_session_state()
            session_state["updated_at"] = "2026-04-20T21:21:02+09:00"
            session_state["active_roadmap_phase_ids"] = ["phase_6"]
            repository.write_session_state(session_state)

            workflow_state = repository.read_workflow_state()
            self.assertEqual(
                workflow_state["loop"]["request"]["expected_roadmap_phase_id"],
                "phase_6",
            )

    def test_write_workflow_state_syncs_loop_request_expected_roadmap_phase_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Workflow loop sync goal", active_roadmap_phase_ids=["phase_4"])

            workflow_state = repository.read_workflow_state()
            workflow_state["loop"] = {
                "status": "running",
                "request": {"expected_roadmap_phase_id": "phase_4"},
            }
            repository.write_workflow_state(workflow_state)
            session_state = repository.read_session_state()
            session_state["loop"] = {
                "status": "running",
                "request": {"expected_roadmap_phase_id": "phase_4"},
            }
            repository.write_session_state(session_state)

            workflow_state = repository.read_workflow_state()
            workflow_state["updated_at"] = "2026-04-20T21:21:03+09:00"
            workflow_state.setdefault("roadmap", {})
            workflow_state["roadmap"]["active_phase_ids"] = ["phase_6"]
            repository.write_workflow_state(workflow_state)

            session_state = repository.read_session_state()
            self.assertEqual(
                session_state["loop"]["request"]["expected_roadmap_phase_id"],
                "phase_6",
            )

    def test_ensure_bootstrap_state_preserves_existing_active_roadmap_phase_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Preserve roadmap phase", active_roadmap_phase_ids=["phase_6"])

            repository.ensure_bootstrap_state(goal="Preserve roadmap phase")

            session_state = repository.read_session_state()
            workflow_state = repository.read_workflow_state()
            self.assertEqual(session_state["active_roadmap_phase_ids"], ["phase_6"])
            self.assertEqual(workflow_state["roadmap"]["active_phase_ids"], ["phase_6"])

    def test_sync_operator_state_imports_newer_active_root_task_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Mirror root PLAN state")

            session_id = repository.read_session_state()["session_id"]
            session_tasks = config.sessions_dir / session_id / "TASKS.md"
            root_tasks = config.base_dev_dir / "TASKS.md"
            self.assertTrue(root_tasks.exists())

            root_tasks.write_text(
                root_tasks.read_text(encoding="utf-8").replace("- [ ] ", "- [O] "),
                encoding="utf-8",
            )
            session_mtime_ns = session_tasks.stat().st_mtime_ns
            bumped_mtime = (session_mtime_ns + 5_000_000) / 1_000_000_000
            os.utime(root_tasks, (bumped_mtime, bumped_mtime))

            repository.sync_operator_state()

            self.assertEqual(root_tasks.read_text(encoding="utf-8"), session_tasks.read_text(encoding="utf-8"))
            task_sync = repository.read_session_state()["task_sync"]
            self.assertTrue(task_sync["all_completed"])
            self.assertEqual(task_sync["pending_tasks"], 0)

    def test_session_scoped_bootstrap_keeps_active_root_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.start_new_session(
                goal="Active session goal",
                active_roadmap_phase_ids=["phase_7"],
                session_id="active-session",
            )
            active_root_index = (config.base_dev_dir / "session.json").read_text(encoding="utf-8")

            session_repository = StateRepository(config, session_id="parallel-session")
            session_repository.ensure_bootstrap_state(
                goal="Parallel session goal",
                active_roadmap_phase_ids=["phase_7"],
            )

            self.assertEqual(
                active_root_index,
                (config.base_dev_dir / "session.json").read_text(encoding="utf-8"),
            )
            parallel_dashboard = (
                config.sessions_dir / "parallel-session" / "DASHBOARD.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Parallel session goal", parallel_dashboard)
            self.assertTrue((config.sessions_dir / "parallel-session" / "PLAN.md").exists())
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

            sessions_dir = home / ".dormammu" / "sessions"
            config = AppConfig.load(
                repo_root=root,
                env={
                    "HOME": str(home),
                    "DORMAMMU_SESSIONS_DIR": str(sessions_dir),
                    **{key: value for key, value in os.environ.items() if key not in ("HOME", "DORMAMMU_SESSIONS_DIR")},
                },
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
            global_prompt = sessions_dir / "prompt-session" / ".dev" / "PROMPT.md"
            self.assertTrue(global_prompt.exists())
            self.assertEqual(global_prompt.read_text(encoding="utf-8"), source_prompt.read_text(encoding="utf-8"))

    def test_ensure_bootstrap_state_regenerates_dashboard_and_plan_when_prompt_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
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
            refreshed_tasks = artifacts.tasks.read_text(encoding="utf-8")
            self.assertNotIn("stale dashboard", refreshed_dashboard)
            self.assertNotIn("Stale work", refreshed_plan)
            self.assertNotIn("Stale work", refreshed_tasks)
            self.assertIn("Updated goal", refreshed_dashboard)
            self.assertIn("Phase 1. Implement beta support", refreshed_plan)
            self.assertIn("Phase 1. Implement beta support", refreshed_tasks)

    def test_sync_operator_state_prefers_newer_plan_document_when_tasks_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Queue source test")

            artifacts.plan.write_text(
                "# PLAN\n\n## Prompt-Derived Implementation Plan\n\n- [O] Phase 1. Plan-only item\n",
                encoding="utf-8",
            )
            artifacts.tasks.write_text(
                "# TASKS\n\n## Prompt-Derived Development Queue\n\n- [ ] Phase 1. Queue-owned item\n",
                encoding="utf-8",
            )
            plan_stat = artifacts.plan.stat()
            bumped_mtime = (plan_stat.st_mtime_ns + 5_000_000) / 1_000_000_000
            os.utime(artifacts.plan, (bumped_mtime, bumped_mtime))

            repository.sync_operator_state()

            task_sync = repository.read_session_state()["task_sync"]
            self.assertEqual(task_sync["source"], self._display_path(artifacts.plan, root))
            self.assertTrue(task_sync["all_completed"])
            self.assertIsNone(task_sync["next_pending_task"])

    def test_sync_operator_state_prefers_more_complete_file_even_when_it_is_older(self) -> None:
        """Regression: _resolve_operator_sync_source must prefer the file with
        fewer pending items over the file with a newer mtime.

        Before the fix, a recently-touched but incomplete TASKS.md would beat a
        fully-complete PLAN.md, causing the supervisor to always see pending
        tasks and return rework_required indefinitely — the root cause of the
        infinite retry loop reported when agents only update PLAN.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Completion priority test")

            # PLAN.md is fully complete.
            artifacts.plan.write_text(
                "# PLAN\n\n## Prompt-Derived Implementation Plan\n\n- [O] Phase 1. Done item\n",
                encoding="utf-8",
            )
            # TASKS.md still has a pending item, AND it has a newer mtime
            # (simulates an agent that read/touched TASKS.md after writing PLAN.md).
            artifacts.tasks.write_text(
                "# TASKS\n\n## Prompt-Derived Development Queue\n\n- [ ] Phase 1. Pending item\n",
                encoding="utf-8",
            )
            tasks_stat = artifacts.tasks.stat()
            bumped_mtime = (tasks_stat.st_mtime_ns + 5_000_000) / 1_000_000_000
            os.utime(artifacts.tasks, (bumped_mtime, bumped_mtime))

            repository.sync_operator_state()

            task_sync = repository.read_session_state()["task_sync"]
            # Must have selected PLAN.md (fewer pending), not the newer TASKS.md.
            self.assertEqual(task_sync["source"], self._display_path(artifacts.plan, root))
            self.assertTrue(task_sync["all_completed"])
            self.assertIsNone(task_sync["next_pending_task"])

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
