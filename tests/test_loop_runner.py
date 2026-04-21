from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.agent import cli_adapter as cli_adapter_module
from dormammu.agent.permissions import (
    AgentPermissionPolicy,
    PermissionDecision,
    WorktreePermissionPolicy,
)
from dormammu.agent.profiles import AgentProfile
from dormammu.loop_runner import LoopRunRequest, LoopRunner
from dormammu.recovery import RecoveryManager
from dormammu.state import StateRepository
from dormammu.worktree import WorktreeRepositoryError


class LoopRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    def test_resolve_agent_profile_uses_request_role_instead_of_assuming_developer(self) -> None:
        config = mock.Mock()
        config.resolve_agent_profile.return_value = AgentProfile(
            name="reviewer",
            description="Reviews changed code for regressions, bugs, and missing coverage.",
        )
        runner = LoopRunner(
            config,
            repository=mock.Mock(),
            adapter=mock.Mock(),
            supervisor=mock.Mock(),
        )

        profile = runner.resolve_agent_profile(
            LoopRunRequest(
                cli_path=Path("codex"),
                prompt_text="Review the active slice.",
                repo_root=Path("/tmp/repo"),
                agent_role="reviewer",
            )
        )

        config.resolve_agent_profile.assert_called_once_with("reviewer")
        self.assertEqual(profile.name, "reviewer")

    def test_run_completes_after_retry_and_writes_continuation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="loop-test",
                    max_retries=1,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempts_completed, 2)
            self.assertEqual(result.retries_used, 1)
            self.assertTrue((root / "done.txt").exists())
            session_id = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            self.assertTrue(
                (config.sessions_dir / session_id / "continuation_prompt.txt").exists()
            )
            self.assertTrue((config.sessions_dir / session_id / "PLAN.md").exists())
            continuation_text = (
                config.sessions_dir / session_id / "continuation_prompt.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("Work inside the current repository and its active workdir by default.", continuation_text)
            self.assertIn("Do not inspect or modify unrelated paths outside the repository", continuation_text)
            self.assertIn("leave planning mode now and make the required repository edits directly", continuation_text)

    def test_retry_prompt_keeps_original_prompt_instead_of_nesting_previous_retry_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=3)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Build a /proc-based memory CLI and create the marker file.",
                    repo_root=root,
                    run_label="loop-original-prompt-test",
                    max_retries=2,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            session_id = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            prompt_dir = config.sessions_dir / session_id / "logs"
            prompt_paths = sorted(prompt_dir.glob("*.prompt.txt"))
            self.assertEqual(len(prompt_paths), 3)
            third_prompt = prompt_paths[-1].read_text(encoding="utf-8")
            self.assertEqual(third_prompt.count("Original prompt:"), 1)
            self.assertIn("Build a /proc-based memory CLI and create the marker file.", third_prompt)

    def test_loop_snapshot_and_state_include_runtime_skill_visibility_for_custom_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            (root / "agents" / "skills" / "designing-agent").mkdir(parents=True, exist_ok=True)
            (root / "agents" / "skills" / "designing-agent" / "SKILL.md").write_text(
                """---
schema_version: 1
name: designing-agent
description: Project designing skill
---

# designing-agent

Use this skill in loop runner tests.
""",
                encoding="utf-8",
            )
            fake_cli = self._write_loop_cli(root, success_attempt=1)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            progress = io.StringIO()
            result = LoopRunner(
                config,
                repository=repository,
                progress_stream=progress,
            ).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="runtime-skills-log-test",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertIn("runtime skills: visible=", progress.getvalue())
            session_state = repository.read_session_state()
            self.assertEqual(session_state["runtime_skills"]["active_role"], "developer")
            self.assertEqual(
                session_state["runtime_skills"]["latest"]["summary"]["custom_visible_count"],
                1,
            )

    def test_run_persists_lifecycle_events_for_successful_loop_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="lifecycle-loop-test",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            lifecycle = repository.read_session_state()["lifecycle"]
            event_types = [entry["event_type"] for entry in lifecycle["history"]]
            self.assertIn("run.requested", event_types)
            self.assertIn("run.started", event_types)
            self.assertIn("stage.queued", event_types)
            self.assertIn("stage.started", event_types)
            self.assertIn("artifact.persisted", event_types)
            self.assertIn("stage.completed", event_types)
            self.assertIn("run.finished", event_types)
            self.assertEqual(
                lifecycle["latest_event"]["event_type"],
                "run.finished",
            )

    def test_resume_continues_failed_loop_from_saved_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            runner = LoopRunner(config, repository=repository)
            first_result = runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="resume-test",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(first_result.status, "failed")
            session_id = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            self.assertTrue(
                (config.sessions_dir / session_id / "continuation_prompt.txt").exists()
            )

            resumed = RecoveryManager(
                config,
                repository=repository,
                loop_runner=runner,
            ).resume(max_retries_override=1)

            self.assertEqual(resumed.status, "completed")
            self.assertTrue((root / "done.txt").exists())

    def test_resume_can_restore_an_archived_session_before_continuing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            repository.start_new_session(
                goal="Session A",
                active_roadmap_phase_ids=["phase_4"],
                session_id="session-a",
            )
            runner = LoopRunner(config, repository=repository)
            first_result = runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="archived-resume-test",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(first_result.status, "failed")
            repository.start_new_session(
                goal="Session B",
                active_roadmap_phase_ids=["phase_7"],
                session_id="session-b",
            )

            resumed = RecoveryManager(
                config,
                repository=repository,
                loop_runner=runner,
            ).resume(session_id="session-a", max_retries_override=1)

            self.assertEqual(resumed.status, "completed")
            self.assertEqual(repository.read_session_state()["session_id"], "session-a")
            self.assertTrue((root / "done.txt").exists())

    def test_infinite_retry_setting_allows_eventual_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=3)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="infinite-retry-test",
                    max_retries=-1,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempts_completed, 3)
            self.assertEqual(result.retries_used, 2)
            self.assertEqual(result.max_iterations, -1)

    def test_run_stops_after_first_success_even_when_max_iteration_budget_is_large(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="early-exit-on-approval",
                    max_retries=49,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempts_completed, 1)
            self.assertEqual(result.max_iterations, 50)

    def test_run_uses_managed_worktree_when_enabled_for_developer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            (root / "dormammu.json").write_text(
                json.dumps({"worktree": {"enabled": True, "root_dir": "./managed-worktrees"}}),
                encoding="utf-8",
            )
            fake_cli = self._write_cwd_loop_cli(root, name="fake-cwd-worktree-agent")
            self._commit_repo_state(root, message="seed managed worktree repo")

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            runner = LoopRunner(config, repository=repository)
            runner.resolve_agent_profile = mock.Mock(
                return_value=AgentProfile(
                    name="developer",
                    description="Implements the active product-code slice under supervisor control.",
                    permission_policy=AgentPermissionPolicy(
                        worktree=WorktreePermissionPolicy(default=PermissionDecision.ALLOW),
                    ),
                )
            )

            result = runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file in the active checkout.",
                    repo_root=root,
                    workdir=root,
                    run_label="worktree-loop-test",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertFalse((root / "done.txt").exists())

            session_worktrees = repository.read_session_worktree_state()
            self.assertFalse(session_worktrees.is_empty)
            self.assertIsNotNone(session_worktrees.active_worktree_id)
            managed_worktree = session_worktrees.managed[0]
            self.assertTrue((managed_worktree.isolated_path / "done.txt").exists())

            latest_run = repository.read_session_state()["latest_run"]
            self.assertEqual(
                latest_run["workdir"],
                str(managed_worktree.isolated_path),
            )
            self.assertEqual(
                (managed_worktree.isolated_path / "cwd.txt").read_text(encoding="utf-8").strip(),
                str(managed_worktree.isolated_path),
            )
            lifecycle = repository.read_session_state()["lifecycle"]
            event_types = [entry["event_type"] for entry in lifecycle["history"]]
            self.assertIn("worktree.prepared", event_types)
            self.assertIn("worktree.released", event_types)
            self.assertLess(
                event_types.index("worktree.prepared"),
                event_types.index("worktree.released"),
            )

    def test_run_keeps_primary_checkout_when_worktree_is_not_permitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            (root / "dormammu.json").write_text(
                json.dumps({"worktree": {"enabled": True, "root_dir": "./managed-worktrees"}}),
                encoding="utf-8",
            )
            fake_cli = self._write_cwd_loop_cli(root, name="fake-cwd-primary-agent")

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            runner = LoopRunner(config, repository=repository)
            runner.resolve_agent_profile = mock.Mock(
                return_value=AgentProfile(
                    name="developer",
                    description="Implements the active product-code slice under supervisor control.",
                )
            )

            result = runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file in the active checkout.",
                    repo_root=root,
                    workdir=root,
                    run_label="primary-loop-test",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertTrue((root / "done.txt").exists())
            self.assertTrue(repository.read_session_worktree_state().is_empty)
            latest_run = repository.read_session_state()["latest_run"]
            self.assertEqual(latest_run["workdir"], str(root.resolve()))

    def test_run_blocks_when_managed_worktree_setup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            (root / "dormammu.json").write_text(
                json.dumps({"worktree": {"enabled": True, "root_dir": "./managed-worktrees"}}),
                encoding="utf-8",
            )
            fake_cli = self._write_cwd_loop_cli(root, name="fake-cwd-blocked-agent")
            self._commit_repo_state(root, message="seed managed worktree repo")

            config = AppConfig.load(
                repo_root=root,
                env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")},
            )
            repository = StateRepository(config)
            runner = LoopRunner(config, repository=repository)
            runner.resolve_agent_profile = mock.Mock(
                return_value=AgentProfile(
                    name="developer",
                    description="Implements the active product-code slice under supervisor control.",
                    permission_policy=AgentPermissionPolicy(
                        worktree=WorktreePermissionPolicy(default=PermissionDecision.ALLOW),
                    ),
                )
            )

            with mock.patch(
                "dormammu.loop_runner.WorktreeService.ensure_worktree",
                side_effect=WorktreeRepositoryError("simulated worktree setup failure"),
            ):
                result = runner.run(
                    LoopRunRequest(
                        cli_path=fake_cli,
                        prompt_text="Create the required marker file in the active checkout.",
                        repo_root=root,
                        workdir=root,
                        run_label="blocked-worktree-loop-test",
                        max_retries=0,
                        required_paths=("done.txt",),
                        expected_roadmap_phase_id="phase_4",
                    )
                )

            self.assertEqual(result.status, "blocked")
            self.assertTrue(repository.read_session_worktree_state().is_empty)
            self.assertIsNone(repository.read_session_state().get("latest_run"))

    def test_run_retries_until_plan_items_are_marked_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1, plan_completion_attempt=2)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file and finish the plan.",
                    repo_root=root,
                    run_label="plan-gated-loop-test",
                    max_retries=1,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempts_completed, 2)
            self.assertTrue((root / "done.txt").exists())
            self.assertEqual((root / ".attempt-count").read_text(encoding="utf-8").strip(), "2")

    def test_run_completes_when_agent_marks_active_root_plan_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(
                root,
                success_attempt=1,
                plan_completion_attempt=1,
                mark_root_plan=True,
            )

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file and finish the plan.",
                    repo_root=root,
                    run_label="root-plan-mirror-completion",
                    max_retries=3,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempts_completed, 1)
            self.assertEqual((root / ".attempt-count").read_text(encoding="utf-8").strip(), "1")

    def test_run_completes_when_agent_marks_only_plan_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(
                root,
                success_attempt=1,
                plan_completion_attempt=1,
                mark_tasks=False,
            )

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file and finish the plan.",
                    repo_root=root,
                    run_label="plan-only-completion",
                    max_retries=1,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempts_completed, 1)
            self.assertEqual((root / ".attempt-count").read_text(encoding="utf-8").strip(), "1")

    def test_failed_final_verification_sets_resume_phase_to_develop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1, plan_completion_attempt=1)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="final-verification-failure",
                    max_retries=0,
                    required_paths=("done.txt", "missing.txt"),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "failed")
            session_id = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            workflow_state = (
                config.sessions_dir / session_id / "workflow_state.json"
            ).read_text(encoding="utf-8")
            payload = json.loads(workflow_state)
            self.assertEqual(payload["workflow"]["resume_from_phase"], "develop")
            continuation_text = (
                config.sessions_dir / session_id / "continuation_prompt.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("Recommended resume phase: develop", continuation_text)

    def test_resume_does_not_run_again_when_total_iteration_budget_is_already_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            runner = LoopRunner(config, repository=repository)
            first_result = runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="max-iteration-stop",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(first_result.status, "failed")
            resumed = RecoveryManager(
                config,
                repository=repository,
                loop_runner=runner,
            ).resume(max_retries_override=0)

            self.assertEqual(resumed.status, "failed")
            self.assertEqual(resumed.attempts_completed, 1)
            self.assertEqual(resumed.max_iterations, 1)
            self.assertEqual((root / ".attempt-count").read_text(encoding="utf-8").strip(), "1")

    def test_run_uses_fallback_cli_without_consuming_retry_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            primary_cli = self._write_exhausted_cli(root, name="primary-agent", message="usage limit exceeded")
            fallback_cli = self._write_loop_cli(root, success_attempt=1, name="fallback-loop-agent")
            (root / "dormammu.json").write_text(
                textwrap.dedent(
                    f"""\
                    {{
                      "fallback_agent_clis": [
                        "{fallback_cli}"
                      ]
                    }}
                    """
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=primary_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="fallback-loop-test",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempts_completed, 1)
            self.assertEqual(result.retries_used, 0)
            latest_run = repository.read_workflow_state()["latest_run"]
            self.assertEqual(latest_run["requested_cli_path"], str(primary_cli.resolve()))
            self.assertEqual(latest_run["cli_path"], str(fallback_cli.resolve()))
            self.assertTrue((root / "done.txt").exists())

    def test_run_blocks_when_all_configured_clis_report_token_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            primary_cli = self._write_exhausted_cli(root, name="primary-agent", message="usage limit exceeded")
            fallback_cli = self._write_exhausted_cli(root, name="fallback-agent", message="quota exceeded")
            (root / "dormammu.json").write_text(
                textwrap.dedent(
                    f"""\
                    {{
                      "fallback_agent_clis": [
                        "{fallback_cli}"
                      ]
                    }}
                    """
                ),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=primary_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="blocked-fallback-loop-test",
                    max_retries=-1,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.attempts_completed, 1)
            self.assertEqual(result.retries_used, 0)
            workflow_state = repository.read_workflow_state()
            self.assertEqual(workflow_state["loop"]["status"], "blocked")

    def test_progress_stream_is_routed_to_adapter_live_output(self) -> None:
        """Regression: CliAdapter.live_output_stream must use the LoopRunner progress_stream,
        not the hardcoded sys.stderr, so TelegramProgressStream (and any custom stream)
        receives subprocess stdout/stderr from the agent CLI."""
        import io

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)

            captured = io.StringIO()
            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            runner = LoopRunner(config, repository=repository, progress_stream=captured)

            # The adapter created inside LoopRunner must carry the progress_stream.
            self.assertIs(runner.adapter.live_output_stream, captured)

            result = runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="stream-routing-test",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )
            self.assertEqual(result.status, "completed")
            # Agent CLI prints "ATTEMPT::1" to stdout, which _mirror_pipe routes to
            # live_output_stream.  Verify it landed in our captured stream.
            self.assertIn("ATTEMPT::1", captured.getvalue())

    def test_loop_completes_when_agent_emits_promise_complete_signal(self) -> None:
        """Agent emitting <promise>COMPLETE</promise> in stdout triggers immediate completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_promise_cli(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Implement the feature and signal completion.",
                    repo_root=root,
                    run_label="promise-complete-test",
                    max_retries=0,
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.supervisor_verdict, "promise_complete")
            self.assertEqual(result.attempts_completed, 1)

    def test_promise_signal_stops_loop_without_supervisor_validation(self) -> None:
        """Promise signal bypasses supervisor even when required_paths is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_promise_cli(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Implement the feature.",
                    repo_root=root,
                    run_label="promise-bypass-supervisor",
                    max_retries=5,
                    required_paths=("never_created.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            # Even though required_paths file was not created, the promise exits the loop.
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.supervisor_verdict, "promise_complete")
            self.assertEqual(result.attempts_completed, 1)

    def test_loop_completes_when_agent_commits_changes(self) -> None:
        """Regression: supervisor prompt-outcome-alignment must count files from recent
        git commits as progress evidence so that an agent that commits its work does not
        trigger an infinite rework_required loop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            # Configure git identity so the fake CLI can commit.
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@test.com"], check=True
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Test"], check=True
            )
            fake_cli = self._write_committing_loop_cli(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Implement the required marker file.",
                    repo_root=root,
                    run_label="commit-progress-test",
                    max_retries=1,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.attempts_completed, 1)

    def _seed_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
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
        (templates / "patterns.md.tmpl").write_text(
            "\n".join(
                [
                    "# Codebase Patterns",
                    "",
                    "This file accumulates reusable patterns discovered during agent runs.",
                    "",
                    "## Patterns",
                    "",
                    "(no patterns recorded yet — add entries as you discover them)",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def _commit_repo_state(self, root: Path, *, message: str) -> None:
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Dormammu Tests"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "tests@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)

    def _write_loop_cli(
        self,
        root: Path,
        *,
        success_attempt: int,
        plan_completion_attempt: int | None = None,
        name: str = "fake-loop-agent",
        mark_root_plan: bool = False,
        mark_tasks: bool = True,
    ) -> Path:
        script = root / name
        effective_plan_completion_attempt = (
            success_attempt if plan_completion_attempt is None else plan_completion_attempt
        )
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                ROOT = Path({str(root)!r})
                SUCCESS_ATTEMPT = {success_attempt}
                PLAN_COMPLETION_ATTEMPT = {effective_plan_completion_attempt}
                MARK_ROOT_PLAN = {mark_root_plan!r}
                MARK_TASKS = {mark_tasks!r}
                COUNTER_PATH = ROOT / ".attempt-count"
                TARGET_PATH = ROOT / "done.txt"
                import os
                _base_dev_dir = os.environ.get("DORMAMMU_BASE_DEV_DIR", "").strip()
                BASE_DEV_DIR = Path(_base_dev_dir) if _base_dev_dir else ROOT / ".dev"
                SESSION_PATH = BASE_DEV_DIR / "session.json"

                def mark_complete(path: Path) -> None:
                    if not path.exists():
                        return
                    lines = path.read_text(encoding="utf-8").splitlines()
                    rewritten = [
                        line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                        for line in lines
                    ]
                    path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

                def mark_plan_complete() -> None:
                    if MARK_ROOT_PLAN:
                        mark_complete(BASE_DEV_DIR / "PLAN.md")
                        if MARK_TASKS:
                            mark_complete(BASE_DEV_DIR / "TASKS.md")
                        return
                    if not SESSION_PATH.exists():
                        return
                    import json
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    _sdir = os.environ.get("DORMAMMU_SESSIONS_DIR", "").strip()
                    sessions_dir = Path(_sdir) if _sdir else BASE_DEV_DIR / "sessions"
                    mark_complete(sessions_dir / str(session_id) / "PLAN.md")
                    if MARK_TASKS:
                        mark_complete(sessions_dir / str(session_id) / "TASKS.md")

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-loop-agent [--prompt-file PATH]")
                        return 0

                    if COUNTER_PATH.exists():
                        attempt = int(COUNTER_PATH.read_text(encoding="utf-8").strip()) + 1
                    else:
                        attempt = 1
                    COUNTER_PATH.write_text(str(attempt), encoding="utf-8")

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    print(f"ATTEMPT::{{attempt}}")
                    print(f"PROMPT::{{prompt.strip()}}")

                    if attempt >= SUCCESS_ATTEMPT:
                        TARGET_PATH.write_text("done\\n", encoding="utf-8")
                    if attempt >= PLAN_COMPLETION_ATTEMPT:
                        mark_plan_complete()

                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_cwd_loop_cli(self, root: Path, *, name: str) -> Path:
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import json
                import os
                import sys

                ROOT = Path({str(root)!r})
                _base_dev_dir = os.environ.get("DORMAMMU_BASE_DEV_DIR", "").strip()
                BASE_DEV_DIR = Path(_base_dev_dir) if _base_dev_dir else ROOT / ".dev"
                SESSION_PATH = BASE_DEV_DIR / "session.json"

                def mark_complete(path: Path) -> None:
                    if not path.exists():
                        return
                    lines = path.read_text(encoding="utf-8").splitlines()
                    rewritten = [
                        line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                        for line in lines
                    ]
                    path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

                def mark_plan_complete() -> None:
                    if not SESSION_PATH.exists():
                        return
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    _sdir = os.environ.get("DORMAMMU_SESSIONS_DIR", "").strip()
                    sessions_dir = Path(_sdir) if _sdir else BASE_DEV_DIR / "sessions"
                    mark_complete(sessions_dir / str(session_id) / "PLAN.md")
                    mark_complete(sessions_dir / str(session_id) / "TASKS.md")

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: {name} [--prompt-file PATH]")
                        return 0

                    cwd = Path.cwd()
                    (cwd / "done.txt").write_text("done\\n", encoding="utf-8")
                    (cwd / "cwd.txt").write_text(str(cwd), encoding="utf-8")
                    mark_plan_complete()
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_promise_cli(self, root: Path, *, name: str = "fake-promise-agent") -> Path:
        """Fake CLI that emits <promise>COMPLETE</promise> in stdout to signal self-completion."""
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                args = sys.argv[1:]
                if "--help" in args:
                    print("usage: {name} [--prompt-file PATH]")
                    raise SystemExit(0)

                print("Implementing the feature...")
                print("<promise>COMPLETE</promise>")
                raise SystemExit(0)
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_committing_loop_cli(self, root: Path, *, name: str = "fake-committing-agent") -> Path:
        """Fake CLI that creates done.txt, marks PLAN/TASKS complete, then git-commits everything.

        This simulates an agent that commits its changes so the worktree is clean
        when the supervisor runs.  The supervisor must detect the commit as progress
        evidence instead of returning rework_required.
        """
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import json, os, subprocess, sys
                from pathlib import Path

                ROOT = Path({str(root)!r})
                TARGET_PATH = ROOT / "done.txt"
                _base_dev_dir = os.environ.get("DORMAMMU_BASE_DEV_DIR", "").strip()
                BASE_DEV_DIR = Path(_base_dev_dir) if _base_dev_dir else ROOT / ".dev"
                SESSION_PATH = BASE_DEV_DIR / "session.json"

                def mark_complete(path: Path) -> None:
                    if not path.exists():
                        return
                    lines = path.read_text(encoding="utf-8").splitlines()
                    rewritten = [
                        line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                        for line in lines
                    ]
                    path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

                def mark_plan_complete() -> None:
                    if not SESSION_PATH.exists():
                        return
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    _sdir = os.environ.get("DORMAMMU_SESSIONS_DIR", "").strip()
                    sessions_dir = Path(_sdir) if _sdir else BASE_DEV_DIR / "sessions"
                    mark_complete(sessions_dir / str(session_id) / "PLAN.md")
                    mark_complete(sessions_dir / str(session_id) / "TASKS.md")

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: {name} [--prompt-file PATH]")
                        return 0

                    TARGET_PATH.write_text("done\\n", encoding="utf-8")
                    mark_plan_complete()

                    # Commit all changes so the worktree is clean when supervisor runs.
                    subprocess.run(
                        ["git", "-C", str(ROOT), "add", "-A"], check=True, capture_output=True
                    )
                    subprocess.run(
                        ["git", "-C", str(ROOT), "commit", "-m", "agent: implement marker file"],
                        check=True, capture_output=True,
                    )
                    print("COMMITTED::done.txt")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _write_exhausted_cli(self, root: Path, *, name: str, message: str) -> Path:
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: {name} [--prompt-file PATH]")
                        return 0

                    print({message!r}, file=sys.stderr)
                    return 2

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script


    # ── stagnation / hard-cap tests ──────────────────────────────────────────

    def test_stagnation_blocks_loop_when_pending_tasks_never_change(self) -> None:
        """Loop must stop with 'blocked' when the same pending task repeats
        _STAGNATION_WINDOW consecutive times — even with max_retries=-1."""
        from dormammu.loop_runner import _STAGNATION_WINDOW

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            # This CLI never marks plan items complete and never creates done.txt,
            # so the supervisor always returns rework_required.
            stuck_cli = self._write_stuck_cli(root)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=stuck_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="stagnation-test",
                    max_retries=-1,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "blocked")
            # Loop ran exactly _STAGNATION_WINDOW attempts before detecting stagnation.
            self.assertEqual(result.attempts_completed, _STAGNATION_WINDOW)

    def test_hard_iteration_cap_stops_infinite_retry_mode(self) -> None:
        """max_retries=-1 must not run past _HARD_ITERATION_CAP iterations.

        This test uses a CLI that succeeds only on attempt > cap, which
        would loop forever without the ceiling.  We patch _HARD_ITERATION_CAP
        to a small value so the test completes quickly.
        """
        from dormammu import loop_runner as lr_module

        original_cap = lr_module._HARD_ITERATION_CAP
        original_window = lr_module._STAGNATION_WINDOW
        try:
            lr_module._HARD_ITERATION_CAP = 4
            # Disable stagnation detection so the hard cap is the active guard.
            lr_module._STAGNATION_WINDOW = 999

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self._seed_repo(root)
                stuck_cli = self._write_stuck_cli(root)

                config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
                repository = StateRepository(config)
                result = LoopRunner(config, repository=repository).run(
                    LoopRunRequest(
                        cli_path=stuck_cli,
                        prompt_text="Create the required marker file.",
                        repo_root=root,
                        run_label="hard-cap-test",
                        max_retries=-1,
                        required_paths=("done.txt",),
                        expected_roadmap_phase_id="phase_4",
                    )
                )

                self.assertEqual(result.status, "failed")
                # Cap of 4 means 1 original + 3 retries = 4 total attempts.
                self.assertEqual(result.attempts_completed, 4)
        finally:
            lr_module._HARD_ITERATION_CAP = original_cap
            lr_module._STAGNATION_WINDOW = original_window

    def test_continuation_prompt_instructs_both_plan_and_tasks(self) -> None:
        """Continuation prompt must tell agents to mark BOTH PLAN.md and TASKS.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            # Use a 2-attempt CLI so a continuation prompt is written after attempt 1.
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
            repository = StateRepository(config)
            LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="dual-checklist-prompt-test",
                    max_retries=1,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )
            session_id = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            continuation_text = (
                config.sessions_dir / session_id / "continuation_prompt.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("PLAN.md", continuation_text)
            self.assertIn("TASKS.md", continuation_text)

    def _write_stuck_cli(self, root: Path, *, name: str = "fake-stuck-agent") -> Path:
        """Fake CLI that never creates done.txt and never marks plan items complete.

        Used to trigger stagnation detection and the hard iteration cap.
        """
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import sys

                args = sys.argv[1:]
                if "--help" in args:
                    print("usage: {name} [--prompt-file PATH]")
                    raise SystemExit(0)

                print("Thinking about it...")
                raise SystemExit(0)
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script


if __name__ == "__main__":
    unittest.main()
