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
from dormammu.worktree import (
    ManagedWorktree,
    WorktreeLifecycleStatus,
    WorktreeOwner,
    WorktreeService,
    WorktreeServiceConfig,
)


class WorktreeModelTests(unittest.TestCase):
    def test_managed_worktree_creation_normalizes_identity_and_serializes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            owner = WorktreeOwner(
                session_id="session-001",
                run_id="run-001",
                agent_role="developer",
            )

            record = ManagedWorktree(
                worktree_id=" Phase 4 / Developer ",
                source_repo_root=root / "repo",
                isolated_path=root / "worktrees" / "phase-4",
                owner=owner,
                status=WorktreeLifecycleStatus.ACTIVE,
            )

            self.assertEqual(record.worktree_id, "phase-4-developer")
            self.assertEqual(record.owner.session_id, "session-001")
            self.assertEqual(record.status, WorktreeLifecycleStatus.ACTIVE)
            self.assertEqual(
                record.to_dict(),
                {
                    "worktree_id": "phase-4-developer",
                    "source_repo_root": str((root / "repo").resolve()),
                    "isolated_path": str((root / "worktrees" / "phase-4").resolve()),
                    "owner": owner.to_dict(),
                    "status": "active",
                },
            )

    def test_worktree_owner_requires_session_or_run_metadata(self) -> None:
        with self.assertRaises(ValueError):
            WorktreeOwner()

    def test_managed_worktree_rejects_shared_or_relative_paths(self) -> None:
        owner = WorktreeOwner(session_id="session-001")

        with self.assertRaises(ValueError):
            ManagedWorktree(
                worktree_id="phase-4",
                source_repo_root=Path("repo"),
                isolated_path=Path("/tmp/worktree"),
                owner=owner,
            )

        with self.assertRaises(ValueError):
            ManagedWorktree(
                worktree_id="phase-4",
                source_repo_root=Path("/tmp/repo"),
                isolated_path=Path("/tmp/repo"),
                owner=owner,
            )


class WorktreeConfigTests(unittest.TestCase):
    def test_service_config_requires_explicit_root_dir(self) -> None:
        with self.assertRaises(TypeError):
            WorktreeServiceConfig()

    def test_service_config_rejects_non_boolean_enabled_on_direct_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "enabled must be a boolean"):
                WorktreeServiceConfig(
                    enabled="false",
                    root_dir=Path(tmpdir).resolve(),
                )

    def test_service_config_rejects_non_boolean_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "enabled must be a boolean"):
                WorktreeServiceConfig.from_dict(
                    {
                        "enabled": "false",
                        "root_dir": str(Path(tmpdir).resolve()),
                    }
                )

    def test_app_config_defaults_worktree_isolation_to_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = AppConfig.load(repo_root=root, env={"HOME": str(root)})

            self.assertFalse(config.worktree.enabled)
            self.assertEqual(
                config.worktree.root_dir,
                (config.workspace_project_root / "worktrees").resolve(),
            )
            self.assertEqual(
                config.to_dict()["worktree"],
                {
                    "enabled": False,
                    "root_dir": str((config.workspace_project_root / "worktrees").resolve()),
                },
            )

    def test_app_config_reads_worktree_override_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dormammu.json").write_text(
                json.dumps(
                    {
                        "worktree": {
                            "enabled": True,
                            "root_dir": "./runtime-worktrees",
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root, env={"HOME": str(root)})

            self.assertTrue(config.worktree.enabled)
            self.assertEqual(
                config.worktree.root_dir,
                (root / "runtime-worktrees").resolve(),
            )


class WorktreeServiceTests(unittest.TestCase):
    def test_disabled_service_returns_fallback_execution_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            repo_root.mkdir()
            service = WorktreeService(
                WorktreeServiceConfig(
                    enabled=False,
                    root_dir=root / "managed-worktrees",
                )
            )

            target = service.resolve_execution_target(
                repo_root=repo_root,
                fallback_workdir=repo_root,
                isolation_requested=True,
                owner=WorktreeOwner(session_id="session-001", run_id="run-001"),
                label="developer",
            )

            self.assertFalse(target.isolation_active)
            self.assertIsNone(target.worktree)
            self.assertEqual(target.workdir, repo_root)

    def test_enabled_service_plans_managed_worktree_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            repo_root.mkdir()
            worktree_root = root / "managed-worktrees"
            service = WorktreeService(
                WorktreeServiceConfig(
                    enabled=True,
                    root_dir=worktree_root,
                )
            )

            target = service.resolve_execution_target(
                repo_root=repo_root,
                isolation_requested=True,
                owner=WorktreeOwner(
                    session_id="session-001",
                    run_id="run-001",
                    agent_role="developer",
                ),
                label="phase-4",
            )

            self.assertTrue(target.isolation_active)
            self.assertIsNotNone(target.worktree)
            self.assertEqual(target.repo_root, target.worktree.isolated_path)
            self.assertEqual(target.workdir, target.worktree.isolated_path)
            self.assertEqual(target.worktree.source_repo_root, repo_root)
            self.assertEqual(
                target.worktree.isolated_path,
                (worktree_root / "session-001-run-001-phase-4").resolve(),
            )

    def test_enabled_service_requires_owner_when_isolation_is_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            repo_root.mkdir()
            service = WorktreeService(
                WorktreeServiceConfig(
                    enabled=True,
                    root_dir=root / "managed-worktrees",
                )
            )

            with self.assertRaises(ValueError):
                service.resolve_execution_target(
                    repo_root=repo_root,
                    isolation_requested=True,
                )
