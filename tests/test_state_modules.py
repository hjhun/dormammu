"""Tests for the focused state management modules introduced in Phase 2.

Covers:
- state/persistence.py  (deep_merge, read_json, write_json, ensure_json_file)
- state/session_manager.py (SessionManager: normalize, generate, list, migrate)
- state/operator_sync.py (OperatorSync: mirror sync, root index write)
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from dormammu.config import AppConfig
from dormammu.results import RunResult, StageResult
from dormammu.state.execution_projection import (
    mutable_execution_block,
    project_lifecycle_execution_fact,
    project_run_result,
    project_stage_result,
)
from dormammu.state.persistence import (
    deep_merge,
    ensure_json_file,
    read_json,
    write_json,
)
from dormammu.state.session_manager import SessionManager


def _seed_repo(root: Path) -> None:
    """Create a minimal repository skeleton."""
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (root / "templates" / "dev").mkdir(parents=True, exist_ok=True)
    for tmpl in ("dashboard.md.tmpl", "plan.md.tmpl", "tasks.md.tmpl", "patterns.md.tmpl"):
        (root / "templates" / "dev" / tmpl).write_text(f"# {tmpl}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# execution_projection.py
# ---------------------------------------------------------------------------


class ExecutionProjectionTests(unittest.TestCase):
    def test_mutable_execution_block_normalizes_stage_results(self) -> None:
        state = {
            "execution": {
                "stage_results": {
                    "tester": {"role": "tester", "verdict": "pass"},
                    42: {"role": "invalid"},
                    "bad": "not-a-mapping",
                }
            }
        }

        execution = mutable_execution_block(state)

        self.assertEqual(
            execution["stage_results"],
            {"tester": {"role": "tester", "verdict": "pass"}},
        )

    def test_project_stage_result_updates_latest_stage_without_touching_other_blocks(self) -> None:
        state = {"bootstrap": {"goal": "keep"}}
        stage = StageResult(role="tester", stage_name="tester", verdict="pass")

        project_stage_result(
            state,
            stage=stage,
            run_id="run-1",
            timestamp="2026-04-25T00:00:00+00:00",
        )

        self.assertEqual(state["bootstrap"], {"goal": "keep"})
        self.assertEqual(state["updated_at"], "2026-04-25T00:00:00+00:00")
        execution = state["execution"]
        self.assertEqual(execution["latest_run_id"], "run-1")
        self.assertEqual(execution["latest_stage_result"]["stage_name"], "tester")
        self.assertEqual(execution["stage_results"]["tester"]["verdict"], "pass")

    def test_project_run_result_uses_latest_stage_result_per_key(self) -> None:
        state: dict[str, object] = {}
        result = RunResult(
            status="completed",
            attempts_completed=2,
            retries_used=1,
            max_retries=3,
            max_iterations=4,
            latest_run_id="agent-run-1",
            supervisor_verdict="approved",
            report_path=None,
            continuation_prompt_path=None,
            stage_results=(
                StageResult(role="tester", stage_name="tester", verdict="fail"),
                StageResult(role="tester", stage_name="tester", verdict="pass"),
            ),
        )

        project_run_result(
            state,
            result=result,
            run_id="pipeline-run-1",
            timestamp="2026-04-25T00:00:00+00:00",
        )

        execution = state["execution"]
        self.assertIsNone(execution["current_run"])
        self.assertEqual(execution["latest_run"]["run_id"], "pipeline-run-1")
        self.assertEqual(execution["latest_run"]["latest_run_id"], "agent-run-1")
        self.assertEqual(execution["stage_results"]["tester"]["verdict"], "pass")

    def test_project_lifecycle_execution_fact_projects_stage_event(self) -> None:
        state: dict[str, object] = {}

        project_lifecycle_execution_fact(
            state,
            event_payload={
                "event_type": "stage.failed",
                "run_id": "run-1",
                "role": "reviewer",
                "stage": "reviewer",
                "status": "completed",
                "payload": {"verdict": "needs_work", "reason": "review failed"},
                "artifact_refs": [{"kind": "stage_report", "path": "/tmp/review.md"}],
            },
            timestamp="2026-04-25T00:00:00+00:00",
        )

        execution = state["execution"]
        self.assertEqual(execution["latest_run_id"], "run-1")
        self.assertEqual(execution["latest_stage_result"]["stage_name"], "reviewer")
        self.assertEqual(execution["latest_stage_result"]["verdict"], "needs_work")


# ---------------------------------------------------------------------------
# persistence.py
# ---------------------------------------------------------------------------


class PersistenceTests(unittest.TestCase):
    def test_deep_merge_overrides_scalars(self) -> None:
        defaults = {"a": 1, "b": {"c": 2, "d": 3}}
        current = {"b": {"c": 99}}
        result = deep_merge(defaults, current)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"]["c"], 99)
        self.assertEqual(result["b"]["d"], 3)

    def test_deep_merge_adds_new_keys(self) -> None:
        result = deep_merge({"a": 1}, {"b": 2})
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_deep_merge_does_not_mutate_defaults(self) -> None:
        defaults: dict = {"nested": {"x": 1}}
        deep_merge(defaults, {"nested": {"y": 2}})
        self.assertNotIn("y", defaults["nested"])

    def test_read_write_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            payload = {"key": "value", "num": 42}
            write_json(path, payload)
            result = read_json(path)
            self.assertEqual(result, payload)

    def test_write_json_ends_with_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            write_json(path, {"x": 1})
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_ensure_json_file_creates_from_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "new.json"
            ensure_json_file(path, {"a": 1})
            self.assertEqual(read_json(path), {"a": 1})

    def test_ensure_json_file_merges_with_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "existing.json"
            write_json(path, {"a": 1, "custom": 99})
            ensure_json_file(path, {"a": 2, "b": 3})
            result = read_json(path)
            self.assertEqual(result["a"], 1)   # existing wins
            self.assertEqual(result["b"], 3)   # default added
            self.assertEqual(result["custom"], 99)  # custom preserved


# ---------------------------------------------------------------------------
# session_manager.py
# ---------------------------------------------------------------------------


class SessionManagerTests(unittest.TestCase):
    def _make_manager(self, root: Path) -> SessionManager:
        config = AppConfig.load(
            repo_root=root,
            env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / ".dev" / "sessions")},
        )
        return SessionManager(config, root / ".dev", root / ".dev" / "sessions")

    def test_normalize_session_id_strips_unsafe_chars(self) -> None:
        result = SessionManager.normalize_session_id("hello world/foo")
        self.assertNotIn(" ", result)
        self.assertNotIn("/", result)

    def test_normalize_session_id_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            SessionManager.normalize_session_id("   ---   ")

    def test_generated_session_id_is_unique_on_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            sessions_dir = root / ".dev" / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            manager = self._make_manager(root)

            ts = "2026-01-01T00:00:00+0000"
            first_id = manager.generated_session_id(ts)
            (sessions_dir / first_id).mkdir()
            second_id = manager.generated_session_id(ts)
            self.assertNotEqual(first_id, second_id)

    def test_current_session_id_reads_session_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.json"
            write_json(path, {"session_id": "my-session"})
            result = SessionManager.current_session_id(path)
            self.assertEqual(result, "my-session")

    def test_current_session_id_returns_none_for_missing_file(self) -> None:
        self.assertIsNone(SessionManager.current_session_id(Path("/nonexistent/session.json")))

    def test_read_active_session_id_reads_root_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            dev_dir = root / ".dev"
            dev_dir.mkdir()
            write_json(dev_dir / "session.json", {"session_id": "active-001"})
            manager = self._make_manager(root)
            self.assertEqual(manager.read_active_session_id(), "active-001")

    def test_list_sessions_returns_empty_when_no_sessions_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            manager = self._make_manager(root)
            self.assertEqual(manager.list_sessions(), [])

    def test_list_sessions_marks_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            dev_dir = root / ".dev"
            dev_dir.mkdir()
            sessions_dir = dev_dir / "sessions"

            for sid in ("sess-a", "sess-b"):
                sdir = sessions_dir / sid
                sdir.mkdir(parents=True)
                write_json(sdir / "session.json", {
                    "session_id": sid,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                    "bootstrap": {"goal": f"Goal for {sid}"},
                })

            write_json(dev_dir / "session.json", {"session_id": "sess-b"})

            manager = self._make_manager(root)
            sessions = manager.list_sessions()
            active = [s for s in sessions if s["is_active"]]
            inactive = [s for s in sessions if not s["is_active"]]
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["session_id"], "sess-b")
            self.assertEqual(len(inactive), 1)
            self.assertEqual(inactive[0]["session_id"], "sess-a")

    def test_migrate_legacy_root_snapshot_moves_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            dev_dir = root / ".dev"
            dev_dir.mkdir()
            sessions_dir = dev_dir / "sessions"
            sessions_dir.mkdir()

            write_json(dev_dir / "session.json", {
                "session_id": "legacy-001",
                "created_at": "2026-01-01T00:00:00",
            })
            write_json(dev_dir / "workflow_state.json", {"version": 1})
            (dev_dir / "DASHBOARD.md").write_text("# Dashboard\n", encoding="utf-8")
            (dev_dir / "PLAN.md").write_text("# Plan\n", encoding="utf-8")

            manager = self._make_manager(root)
            result_id = manager.migrate_legacy_root_snapshot(timestamp="2026-01-01T00:00:00+0000")
            self.assertEqual(result_id, "legacy-001")
            self.assertTrue((sessions_dir / "legacy-001" / "session.json").exists())

    def test_has_legacy_root_snapshot_detects_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            dev_dir = root / ".dev"
            dev_dir.mkdir()
            manager = self._make_manager(root)
            self.assertFalse(manager.has_legacy_root_snapshot())
            (dev_dir / "DASHBOARD.md").write_text("x", encoding="utf-8")
            self.assertTrue(manager.has_legacy_root_snapshot())

    def test_copy_state_snapshot_copies_core_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            target = Path(tmpdir) / "target"
            source.mkdir()
            write_json(source / "session.json", {"session_id": "x"})
            (source / "DASHBOARD.md").write_text("# D\n", encoding="utf-8")
            SessionManager.copy_state_snapshot(source, target)
            self.assertTrue((target / "session.json").exists())
            self.assertTrue((target / "DASHBOARD.md").exists())


if __name__ == "__main__":
    unittest.main()
