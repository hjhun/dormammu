from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.worktree import (
    ManagedWorktree,
    WorktreeCollisionError,
    WorktreeGitCommandError,
    WorktreeLifecycleStatus,
    WorktreeOwner,
    WorktreeRepositoryError,
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


class WorktreeLifecycleTests(unittest.TestCase):
    def test_ensure_worktree_creates_registered_managed_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            self._seed_git_repo(repo_root)
            service = self._service(root)

            worktree = service.ensure_worktree(
                source_repo_root=repo_root,
                owner=self._owner(),
                label="phase-4",
            )

            self.assertEqual(worktree.status, WorktreeLifecycleStatus.ACTIVE)
            self.assertTrue(worktree.isolated_path.exists())
            self.assertIn(worktree.isolated_path, self._list_worktree_paths(repo_root))

    def test_ensure_worktree_reuses_existing_registered_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            self._seed_git_repo(repo_root)
            service = self._service(root)

            first = service.ensure_worktree(
                source_repo_root=repo_root,
                owner=self._owner(),
                label="phase-4",
            )
            second = service.ensure_worktree(
                source_repo_root=repo_root,
                owner=self._owner(),
                label="phase-4",
            )

            self.assertEqual(first.isolated_path, second.isolated_path)
            self.assertEqual(self._list_worktree_paths(repo_root).count(first.isolated_path), 1)

    def test_ensure_worktree_recreates_prunable_registered_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            self._seed_git_repo(repo_root)
            service = self._service(root)

            first = service.ensure_worktree(
                source_repo_root=repo_root,
                owner=self._owner(),
                label="phase-4",
            )
            self._remove_path(first.isolated_path)

            self.assertIn(
                "prunable",
                self._git_output(repo_root, "worktree", "list", "--porcelain"),
            )

            recreated = service.ensure_worktree(
                source_repo_root=repo_root,
                owner=self._owner(),
                label="phase-4",
            )

            self.assertEqual(recreated.status, WorktreeLifecycleStatus.ACTIVE)
            self.assertEqual(recreated.isolated_path, first.isolated_path)
            self.assertTrue(recreated.isolated_path.exists())
            self.assertEqual(self._list_worktree_paths(repo_root).count(recreated.isolated_path), 1)
            self.assertNotIn(
                "prunable",
                self._git_output(repo_root, "worktree", "list", "--porcelain"),
            )

    def test_ensure_worktree_rejects_unmanaged_path_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            self._seed_git_repo(repo_root)
            service = self._service(root)

            planned = service.plan_worktree(
                source_repo_root=repo_root,
                owner=self._owner(),
                label="phase-4",
            )
            planned.isolated_path.mkdir(parents=True, exist_ok=True)

            with self.assertRaisesRegex(WorktreeCollisionError, "already exists"):
                service.ensure_worktree(
                    source_repo_root=repo_root,
                    owner=self._owner(),
                    label="phase-4",
                )

    def test_reset_worktree_restores_tracked_files_and_removes_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            self._seed_git_repo(repo_root)
            service = self._service(root)
            worktree = service.ensure_worktree(
                source_repo_root=repo_root,
                owner=self._owner(),
                label="phase-4",
            )

            tracked_path = worktree.isolated_path / "tracked.txt"
            untracked_path = worktree.isolated_path / "scratch.txt"
            ignored_dir = worktree.isolated_path / "build"
            ignored_path = ignored_dir / "artifact.cache"
            tracked_path.write_text("changed\n", encoding="utf-8")
            untracked_path.write_text("scratch\n", encoding="utf-8")
            ignored_dir.mkdir(parents=True, exist_ok=True)
            ignored_path.write_text("artifact\n", encoding="utf-8")

            reset_worktree = service.reset_worktree(worktree)

            self.assertEqual(reset_worktree.status, WorktreeLifecycleStatus.ACTIVE)
            self.assertEqual(tracked_path.read_text(encoding="utf-8"), "seed\n")
            self.assertFalse(untracked_path.exists())
            self.assertFalse(ignored_path.exists())
            self.assertEqual(self._git_output(worktree.isolated_path, "status", "--short"), "")

    def test_remove_worktree_cleans_up_registered_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            self._seed_git_repo(repo_root)
            service = self._service(root)
            worktree = service.ensure_worktree(
                source_repo_root=repo_root,
                owner=self._owner(),
                label="phase-4",
            )

            removed = service.remove_worktree(worktree)

            self.assertEqual(removed.status, WorktreeLifecycleStatus.REMOVED)
            self.assertFalse(worktree.isolated_path.exists())
            self.assertNotIn(worktree.isolated_path, self._list_worktree_paths(repo_root))

    def test_ensure_worktree_rejects_non_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            repo_root.mkdir()
            service = self._service(root)

            with self.assertRaisesRegex(WorktreeRepositoryError, "usable git repository"):
                service.ensure_worktree(
                    source_repo_root=repo_root,
                    owner=self._owner(),
                    label="phase-4",
                )

    def test_ensure_worktree_surfaces_git_command_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            repo_root = root / "repo"
            self._seed_git_repo(repo_root)

            def git_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
                if "worktree" in command and "add" in command:
                    return subprocess.CompletedProcess(
                        args=list(command),
                        returncode=128,
                        stdout="",
                        stderr="simulated add failure\n",
                    )
                return subprocess.run(
                    list(command),
                    capture_output=True,
                    text=True,
                    check=False,
                )

            service = WorktreeService(
                WorktreeServiceConfig(
                    enabled=True,
                    root_dir=root / "managed-worktrees",
                ),
                git_runner=git_runner,
            )

            with self.assertRaisesRegex(WorktreeGitCommandError, "simulated add failure"):
                service.ensure_worktree(
                    source_repo_root=repo_root,
                    owner=self._owner(),
                    label="phase-4",
                )

    def _service(self, root: Path) -> WorktreeService:
        return WorktreeService(
            WorktreeServiceConfig(
                enabled=True,
                root_dir=root / "managed-worktrees",
            )
        )

    def _owner(self) -> WorktreeOwner:
        return WorktreeOwner(
            session_id="session-001",
            run_id="run-001",
            agent_role="developer",
        )

    def _seed_git_repo(self, repo_root: Path) -> None:
        repo_root.mkdir(parents=True, exist_ok=True)
        self._run_git(repo_root, "init", "-q")
        self._run_git(repo_root, "config", "user.name", "Dormammu Tests")
        self._run_git(repo_root, "config", "user.email", "tests@example.com")
        (repo_root / ".gitignore").write_text("build/\n", encoding="utf-8")
        (repo_root / "tracked.txt").write_text("seed\n", encoding="utf-8")
        self._run_git(repo_root, "add", ".gitignore", "tracked.txt")
        self._run_git(repo_root, "commit", "-qm", "seed")

    def _list_worktree_paths(self, repo_root: Path) -> list[Path]:
        output = self._git_output(repo_root, "worktree", "list", "--porcelain")
        paths: list[Path] = []
        for line in output.splitlines():
            if line.startswith("worktree "):
                paths.append(Path(line.split(" ", 1)[1]).resolve())
        return paths

    def _git_output(self, repo_root: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    def _run_git(self, repo_root: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def _remove_path(self, path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
