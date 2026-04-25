from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.results import StageResult
from dormammu.state import StateRepository
from dormammu.supervisor import Supervisor, SupervisorRequest


class SupervisorTests(unittest.TestCase):
    def test_validate_reports_state_mismatch_as_rework_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_4"])
            self._seed_latest_run(root, repository)

            session_repo = repository.for_session(repository.read_session_state()["session_id"])
            session_state = session_repo.read_session_state()
            session_state["active_phase"] = "develop"
            session_repo.state_file("session.json").write_text(
                json.dumps(session_state, indent=2),
                encoding="utf-8",
            )

            workflow_state = session_repo.read_workflow_state()
            workflow_state["workflow"]["active_phase"] = "plan"
            session_repo.state_file("workflow_state.json").write_text(
                json.dumps(workflow_state, indent=2),
                encoding="utf-8",
            )

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "rework_required")
            self.assertTrue(any(check.name == "phase-pointer" and not check.ok for check in report.checks))

    def test_validate_requires_progress_for_action_oriented_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(
                active_roadmap_phase_ids=["phase_4"],
                prompt_text="Implement the missing retry loop handling.",
            )
            self._seed_latest_run(
                root,
                repository,
                prompt_text="Implement the missing retry loop handling.\n",
                stdout_text="What should happen if the supervisor disagrees?\n",
            )
            self._mark_plan_complete(repository)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "rework_required")
            self.assertTrue(
                any(check.name == "prompt-outcome-alignment" and not check.ok for check in report.checks)
            )

    def test_validate_allows_read_only_prompt_without_worktree_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(
                active_roadmap_phase_ids=["phase_4"],
                prompt_text="Summarize the current repository layout and call out the loop entrypoints.",
            )
            self._seed_latest_run(
                root,
                repository,
                prompt_text="Summarize the current repository layout and call out the loop entrypoints.\n",
                stdout_text="The main loop lives in backend/dormammu/loop_runner.py.\n",
            )
            self._mark_plan_complete(repository)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "approved")
            self.assertTrue(
                any(check.name == "prompt-outcome-alignment" and check.ok for check in report.checks)
            )

    def test_validate_accepts_action_prompt_when_meaningful_changes_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(
                active_roadmap_phase_ids=["phase_4"],
                prompt_text="Fix the resume command so it restores the saved prompt.",
            )
            (root / "feature.txt").write_text("implemented\n", encoding="utf-8")
            self._seed_latest_run(
                root,
                repository,
                prompt_text="Fix the resume command so it restores the saved prompt.\n",
                stdout_text="Implemented the resume-path fix.\n",
            )
            self._mark_plan_complete(repository)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "approved")
            self.assertTrue(
                any(check.name == "prompt-outcome-alignment" and check.ok for check in report.checks)
            )

    def test_validate_requires_plan_completion_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(
                active_roadmap_phase_ids=["phase_4"],
                prompt_text="Fix the resume command so it restores the saved prompt.",
            )
            (root / "feature.txt").write_text("implemented\n", encoding="utf-8")
            self._seed_latest_run(
                root,
                repository,
                prompt_text="Fix the resume command so it restores the saved prompt.\n",
                stdout_text="Implemented the resume-path fix.\n",
            )

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "rework_required")
            self.assertTrue(
                any(check.name == "plan-completion" and not check.ok for check in report.checks)
            )

    def test_validate_final_verification_failure_recommends_returning_to_develop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(
                active_roadmap_phase_ids=["phase_4"],
                prompt_text="Create the required marker file.",
            )
            self._seed_latest_run(
                root,
                repository,
                prompt_text="Create the required marker file.\n",
                stdout_text="Implemented the change.\n",
            )
            self._mark_plan_complete(repository)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(report.verdict, "rework_required")
            self.assertEqual(report.recommended_next_phase, "develop")
            self.assertTrue(
                any(check.name == "final-operation-verification" and not check.ok for check in report.checks)
            )
            self.assertIn("Recommended next phase: develop", report.to_markdown())

    def test_validate_prefers_clean_stage_results_over_stale_plan_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(
                active_roadmap_phase_ids=["phase_4"],
                prompt_text="Implement the missing retry loop handling.",
            )
            self._seed_latest_run(
                root,
                repository,
                prompt_text="Implement the missing retry loop handling.\n",
                stdout_text="Implemented and validated the retry loop handling.\n",
            )
            self._seed_execution_stage_results(
                repository,
                (
                    StageResult(role="developer", stage_name="developer", verdict="approved"),
                    StageResult(role="tester", stage_name="tester", verdict="pass"),
                    StageResult(role="reviewer", stage_name="reviewer", verdict="approved"),
                ),
            )

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "approved")
            self.assertEqual(
                report.to_dict()["decision_basis"]["decision_source"],
                "structured_stage_results",
            )
            self.assertTrue(
                any(check.name == "plan-completion" and not check.ok for check in report.checks)
            )
            self.assertTrue(
                any(
                    check.name == "structured-stage-evidence" and check.ok
                    for check in report.checks
                )
            )

    def test_validate_rejects_negative_stage_results_even_when_markdown_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(
                active_roadmap_phase_ids=["phase_4"],
                prompt_text="Implement the missing retry loop handling.",
            )
            self._seed_latest_run(
                root,
                repository,
                prompt_text="Implement the missing retry loop handling.\n",
                stdout_text="All checklist items are complete.\n",
            )
            self._mark_plan_complete(repository)
            self._write_workflows_md(repository, all_complete=True)
            self._seed_execution_stage_results(
                repository,
                (
                    StageResult(role="developer", stage_name="developer", verdict="approved"),
                    StageResult(role="tester", stage_name="tester", verdict="pass"),
                    StageResult(role="reviewer", stage_name="reviewer", verdict="needs_work"),
                ),
            )

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "rework_required")
            self.assertEqual(
                report.to_dict()["decision_basis"]["primary_evidence"],
                "structured_stage_results",
            )
            self.assertTrue(
                any(
                    check.name == "structured-stage-evidence" and not check.ok
                    for check in report.checks
                )
            )

    def _seed_latest_run(
        self,
        root: Path,
        repository: StateRepository,
        *,
        prompt_text: str = "phase 4 seed prompt\n",
        stdout_text: str = "ok\n",
        stderr_text: str = "",
    ) -> None:
        logs_dir = root / ".dev" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = logs_dir / "seed.prompt.txt"
        stdout_path = logs_dir / "seed.stdout.log"
        stderr_path = logs_dir / "seed.stderr.log"
        metadata_path = logs_dir / "seed.meta.json"

        prompt_path.write_text(prompt_text, encoding="utf-8")
        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text(stderr_text, encoding="utf-8")
        started_at = datetime.now(timezone.utc) + timedelta(seconds=2)
        completed_at = started_at + timedelta(seconds=1)

        payload = {
            "run_id": "seed-run",
            "cli_path": str(root / "fake-agent"),
            "workdir": str(root),
            "prompt_mode": "file",
            "command": [str(root / "fake-agent"), "--prompt-file", str(prompt_path)],
            "exit_code": 0,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "artifacts": {
                "prompt": str(prompt_path),
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
                "metadata": str(metadata_path),
            },
            "capabilities": {
                "help_flag": "--help",
                "prompt_file_flag": "--prompt-file",
                "prompt_arg_flag": "--prompt",
                "workdir_flag": None,
                "help_exit_code": 0,
            },
        }
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        session_state = repository.read_session_state()
        workflow_state = repository.read_workflow_state()
        session_state["latest_run"] = payload
        workflow_state["latest_run"] = payload
        repository.write_session_state(session_state)
        repository.write_workflow_state(workflow_state)

    def _seed_execution_stage_results(
        self,
        repository: StateRepository,
        stage_results: tuple[StageResult, ...],
        *,
        status: str = "completed",
    ) -> None:
        stage_payloads = [stage.to_dict(include_output=False) for stage in stage_results]
        latest_by_stage = {stage.key: stage.to_dict(include_output=False) for stage in stage_results}
        execution = {
            "latest_run_id": "structured-run",
            "latest_execution_id": "structured-run",
            "current_run": None,
            "latest_run": {
                "run_id": "structured-run",
                "execution_run_id": "structured-run",
                "latest_run_id": "seed-run",
                "status": status,
                "stage_results": stage_payloads,
            },
            "stage_results": latest_by_stage,
            "latest_stage_result": stage_payloads[-1] if stage_payloads else None,
        }
        session_state = repository.read_session_state()
        workflow_state = repository.read_workflow_state()
        session_state["execution"] = execution
        workflow_state["execution"] = execution
        repository.write_state_pair(
            session_payload=session_state,
            workflow_payload=workflow_state,
        )

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
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Dormammu Tests"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "tests@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "seed"], check=True)

    def _mark_plan_complete(self, repository: StateRepository) -> None:
        plan_path = repository.state_file("PLAN.md")
        tasks_path = repository.state_file("TASKS.md")
        if not plan_path.exists() or not tasks_path.exists():
            session_id = repository.read_session_state().get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                session_repository = repository.for_session(session_id)
                plan_path = session_repository.state_file("PLAN.md")
                tasks_path = session_repository.state_file("TASKS.md")
        for path in (plan_path, tasks_path):
            rewritten_lines = [
                line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            path.write_text("\n".join(rewritten_lines) + "\n", encoding="utf-8")

    def _write_workflows_md(self, repository: StateRepository, *, all_complete: bool) -> None:
        """Write a WORKFLOWS.md with phases either all done or with one pending."""
        dev_dir = repository.state_file("WORKFLOWS.md").parent
        dev_dir.mkdir(parents=True, exist_ok=True)
        if all_complete:
            content = "\n".join([
                "# Workflows",
                "",
                "## Task: test task",
                "",
                "[O] Phase 0. Refine — refining-agent",
                "[O] Phase 1. Plan — planning-agent",
                "[O] Phase 2. Develop — developing-agent",
                "[O] Phase 3. Commit — committing-agent",
                "",
            ])
        else:
            content = "\n".join([
                "# Workflows",
                "",
                "## Task: test task",
                "",
                "[O] Phase 0. Refine — refining-agent",
                "[O] Phase 1. Plan — planning-agent",
                "[ ] Phase 2. Develop — developing-agent",
                "[ ] Phase 3. Commit — committing-agent",
                "",
            ])
        repository.state_file("WORKFLOWS.md").write_text(content, encoding="utf-8")


class SupervisorWorkflowsCompletionSmokeTests(unittest.TestCase):
    """Smoke tests for the WORKFLOWS.md-based completion signal added to the supervisor."""

    def _setup(self, root: Path, *, prompt_text: str = "Implement X.", stdout_text: str = "Done.\n") -> tuple:
        """Bootstrap a minimal repo, seed a latest run, and return (config, repository)."""
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n${task_items}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Dormammu Tests"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "tests@dormammu.test"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "seed"], check=True)

        config = AppConfig.load(repo_root=root)
        repository = StateRepository(config)
        repository.ensure_bootstrap_state(
            active_roadmap_phase_ids=["phase_4"],
            prompt_text=prompt_text,
        )

        logs_dir = root / ".dev" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timedelta, timezone
        started_at = datetime.now(timezone.utc) + timedelta(seconds=2)
        completed_at = started_at + timedelta(seconds=1)
        prompt_path = logs_dir / "seed.prompt.txt"
        stdout_path = logs_dir / "seed.stdout.log"
        stderr_path = logs_dir / "seed.stderr.log"
        metadata_path = logs_dir / "seed.meta.json"
        prompt_path.write_text(prompt_text + "\n", encoding="utf-8")
        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        payload = {
            "run_id": "smoke-run",
            "cli_path": str(root / "fake-agent"),
            "workdir": str(root),
            "prompt_mode": "file",
            "command": [str(root / "fake-agent")],
            "exit_code": 0,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "artifacts": {
                "prompt": str(prompt_path),
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
                "metadata": str(metadata_path),
            },
            "capabilities": {},
        }
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        session_state = repository.read_session_state()
        workflow_state = repository.read_workflow_state()
        session_state["latest_run"] = payload
        workflow_state["latest_run"] = payload
        repository.write_session_state(session_state)
        repository.write_workflow_state(workflow_state)
        return config, repository

    def _write_workflows(self, repository: StateRepository, *, all_complete: bool) -> None:
        dev_dir = repository.state_file("WORKFLOWS.md").parent
        dev_dir.mkdir(parents=True, exist_ok=True)
        if all_complete:
            content = (
                "# Workflows\n\n## Task: smoke\n\n"
                "[O] Phase 0. Refine\n"
                "[O] Phase 1. Plan\n"
                "[O] Phase 2. Develop\n"
                "[O] Phase 3. Commit\n"
            )
        else:
            content = (
                "# Workflows\n\n## Task: smoke\n\n"
                "[O] Phase 0. Refine\n"
                "[O] Phase 1. Plan\n"
                "[ ] Phase 2. Develop\n"
                "[ ] Phase 3. Commit\n"
            )
        repository.state_file("WORKFLOWS.md").write_text(content, encoding="utf-8")

    def _write_workflows_with_pending_commit_only(self, repository: StateRepository) -> None:
        dev_dir = repository.state_file("WORKFLOWS.md").parent
        dev_dir.mkdir(parents=True, exist_ok=True)
        content = (
            "# Workflows\n\n## Task: smoke\n\n"
            "[O] Phase 0. Refine\n"
            "[O] Phase 1. Plan\n"
            "[O] Phase 2. Design\n"
            "[O] Phase 3. Develop\n"
            "[O] Phase 4. Test and Review\n"
            "[O] Phase 5. Final Verify\n"
            "[ ] Phase 6. Commit\n"
        )
        repository.state_file("WORKFLOWS.md").write_text(content, encoding="utf-8")

    def _write_status_style_workflows_with_deferred_commit(self, repository: StateRepository) -> None:
        dev_dir = repository.state_file("WORKFLOWS.md").parent
        dev_dir.mkdir(parents=True, exist_ok=True)
        content = (
            "# WORKFLOWS\n\n"
            "## Adaptive Phase Sequence\n\n"
            "### Stage 0. Refine\n\n"
            "- Status: completed\n\n"
            "### Stage 1. Plan\n\n"
            "- Status: completed\n\n"
            "### Stage 2. Develop\n\n"
            "- Status: completed\n\n"
            "### Stage 3. Test And Review\n\n"
            "- Status: completed\n\n"
            "### Stage 4. Commit\n\n"
            "- Status: deferred\n\n"
            "### Stage 5. Evaluate\n\n"
            "- Status: completed\n"
        )
        repository.state_file("WORKFLOWS.md").write_text(content, encoding="utf-8")

    def _mark_plan_complete(self, repository: StateRepository) -> None:
        for name in ("PLAN.md", "TASKS.md"):
            path = repository.state_file(name)
            if path.exists():
                rewritten = [
                    line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                    for line in path.read_text(encoding="utf-8").splitlines()
                ]
                path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    # ── smoke test 1 ──────────────────────────────────────────────────────────
    def test_approved_when_workflows_all_complete_no_question(self) -> None:
        """WORKFLOWS.md all [O] + clean run + no questions → approved.

        This is the primary regression guard for the infinite-loop fix:
        an action-oriented prompt whose agent work only touches .dev/ files
        should not block completion once all workflow phases are checked off.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Improve the implementation.",
                stdout_text="All phases complete. No further action needed.\n",
            )
            self._mark_plan_complete(repository)
            self._write_workflows(repository, all_complete=True)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(
                report.verdict,
                "approved",
                f"Expected approved but got {report.verdict!r}. "
                f"Failing checks: {[c.name for c in report.checks if not c.ok]}",
            )
            self.assertTrue(
                any(check.name == "workflows-completion" and check.ok for check in report.checks),
                "workflows-completion check should be present and OK",
            )

    # ── smoke test 2 ──────────────────────────────────────────────────────────
    def test_rework_required_when_workflows_complete_but_agent_asked_question(self) -> None:
        """WORKFLOWS.md all [O] but agent output ends with a clarifying question → rework.

        Even when the checklist looks done, an unresolved question signals that
        the agent stalled and may have marked phases prematurely.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Improve the implementation.",
                stdout_text="How should I proceed?\n",
            )
            self._mark_plan_complete(repository)
            self._write_workflows(repository, all_complete=True)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(
                report.verdict,
                "rework_required",
                "Agent ended with a question — should require rework even if workflows look complete.",
            )

    # ── smoke test 3 ──────────────────────────────────────────────────────────
    def test_rework_required_when_workflows_still_pending(self) -> None:
        """WORKFLOWS.md has pending [ ] phases → rework_required."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Implement X.",
                stdout_text="Started the implementation.\n",
            )
            self._write_workflows(repository, all_complete=False)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "rework_required")
            self.assertTrue(
                any(check.name == "workflows-completion" and not check.ok for check in report.checks),
                "workflows-completion check should be present and FAIL",
            )

    # ── smoke test 4 ──────────────────────────────────────────────────────────
    def test_approved_when_workflows_complete_required_paths_satisfied(self) -> None:
        """WORKFLOWS.md all [O] + required output file exists → approved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Create done.txt.",
                stdout_text="Created done.txt.\n",
            )
            (root / "done.txt").write_text("done\n", encoding="utf-8")
            self._mark_plan_complete(repository)
            self._write_workflows(repository, all_complete=True)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(report.verdict, "approved")

    def test_approved_when_only_commit_is_pending_for_manual_run(self) -> None:
        """Manual runs may stop after final verification without forcing a commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Implement X.",
                stdout_text="Implementation and validation are complete.\n",
            )
            self._mark_plan_complete(repository)
            self._write_workflows_with_pending_commit_only(repository)

            session_state = repository.read_session_state()
            workflow_state = repository.read_workflow_state()
            session_state["active_phase"] = "commit"
            workflow_state["workflow"]["active_phase"] = "commit"
            repository.write_session_state(session_state)
            repository.write_workflow_state(workflow_state)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "approved")
            self.assertTrue(
                any(check.name == "workflows-completion" and check.ok for check in report.checks),
                "workflows-completion should accept a pending commit for manual runs",
            )
            self.assertTrue(
                any(
                    check.name == "workflows-completion"
                    and check.summary == "WORKFLOWS.md is complete enough for approval with only Commit pending."
                    for check in report.checks
                ),
                "manual-run approval should describe the pending-commit exception accurately",
            )

    def test_approved_when_status_style_workflows_complete_and_commit_deferred(self) -> None:
        """Status-style WORKFLOWS.md should not force rework after PLAN completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Implement X.",
                stdout_text=(
                    "Clarification was required during intake.\n"
                    "- Exit condition: requirements are explicit enough to plan without a clarification loop.\n"
                    "Implementation and validation are complete.\n"
                ),
            )
            self._mark_plan_complete(repository)
            self._write_status_style_workflows_with_deferred_commit(repository)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(
                report.verdict,
                "approved",
                f"Expected approved but got {report.verdict!r}. "
                f"Failing checks: {[c.name for c in report.checks if not c.ok]}",
            )
            self.assertTrue(
                any(check.name == "workflows-completion" and check.ok for check in report.checks),
                "status-style WORKFLOWS.md with only deferred commit should pass",
            )

    def test_approved_when_workflows_use_bullet_prefixed_checkboxes(self) -> None:
        """Bullet-prefixed workflow checklist lines should count as completed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Implement X.",
                stdout_text="Implementation and validation are complete.\n",
            )
            self._mark_plan_complete(repository)

            repository.state_file("WORKFLOWS.md").write_text(
                "# Workflows\n\n## Task: smoke\n\n"
                "- [O] Phase 0. Refine\n"
                "- [O] Phase 1. Plan\n"
                "- [O] Phase 2. Design\n"
                "- [O] Phase 3. Develop\n"
                "- [O] Phase 4. Test and Review\n"
                "- [O] Phase 5. Final Verify\n",
                encoding="utf-8",
            )

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "approved")
            self.assertTrue(
                any(check.name == "workflows-completion" and check.ok for check in report.checks),
                "workflows-completion should accept bullet-prefixed completed phases",
            )

    def test_rework_required_when_commit_prompt_leaves_commit_pending(self) -> None:
        """A prompt that explicitly asks for a commit must not pass with commit still pending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Prepare a commit for the completed implementation.",
                stdout_text="Implementation and validation are complete.\n",
            )
            self._mark_plan_complete(repository)
            self._write_workflows_with_pending_commit_only(repository)

            session_state = repository.read_session_state()
            workflow_state = repository.read_workflow_state()
            session_state["active_phase"] = "commit"
            workflow_state["workflow"]["active_phase"] = "commit"
            repository.write_session_state(session_state)
            repository.write_workflow_state(workflow_state)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "rework_required")
            self.assertTrue(
                any(check.name == "workflows-completion" and not check.ok for check in report.checks),
                "workflows-completion should still fail when the prompt explicitly requested a commit",
            )

    def test_approved_when_guidance_wrapper_mentions_commit_but_task_does_not(self) -> None:
        """Guidance text mentioning commit must not disable the pending-commit manual-run exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Implement X.",
                stdout_text="Implementation and validation are complete.\n",
            )
            self._mark_plan_complete(repository)
            self._write_workflows_with_pending_commit_only(repository)

            wrapped_prompt = (
                "Follow the guidance files below before making changes.\n"
                "AGENTS.md says use the committing skill only after validation or on explicit commit request.\n"
                "Original prompt:\n"
                "Treat repository state as authoritative.\n"
                "Task prompt:\n"
                "Implement X.\n"
            )
            wrapped_prompt_path = root / ".dev" / "logs" / "wrapped.prompt.txt"
            wrapped_prompt_path.write_text(wrapped_prompt, encoding="utf-8")

            session_state = repository.read_session_state()
            workflow_state = repository.read_workflow_state()
            session_state["active_phase"] = "commit"
            session_state["bootstrap"]["prompt_path"] = str(wrapped_prompt_path)
            workflow_state["workflow"]["active_phase"] = "commit"
            workflow_state["bootstrap"]["prompt_path"] = str(wrapped_prompt_path)
            repository.write_session_state(session_state)
            repository.write_workflow_state(workflow_state)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(expected_roadmap_phase_id="phase_4")
            )

            self.assertEqual(report.verdict, "approved")
            self.assertTrue(
                any(check.name == "workflows-completion" and check.ok for check in report.checks),
                "guidance-level commit mentions should not block the manual-run commit exception",
            )

    # ── smoke test 5 ──────────────────────────────────────────────────────────
    def test_rework_required_when_workflows_complete_but_required_path_missing(self) -> None:
        """WORKFLOWS.md all [O] but a required output path is still missing → rework."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config, repository = self._setup(
                root,
                prompt_text="Create done.txt.",
                stdout_text="Created done.txt.\n",
            )
            # done.txt intentionally NOT created
            self._mark_plan_complete(repository)
            self._write_workflows(repository, all_complete=True)

            report = Supervisor(config, repository=repository).validate(
                SupervisorRequest(
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(report.verdict, "rework_required")
            self.assertTrue(
                any(check.name == "required-paths" and not check.ok for check in report.checks),
            )


class PipelineRunnerNoStageDirSmokeTests(unittest.TestCase):
    """Smoke tests verifying that refiner and planner do not create numbered stage dirs."""

    def _seed_git_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        rules_dir = root / "agents" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        for name in ("refiner-runtime.md", "planner-runtime.md"):
            (rules_dir / name).write_text(f"# {name}\nDo the task.\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.test"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "seed"], check=True)

    def _make_adapter_result(self, tmpdir: Path, stdout: str = "", stderr: str = "") -> Any:
        """Create a mock AgentRunResult with real temp files for stdout/stderr."""
        out_dir = tmpdir / "_adapter_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        from unittest.mock import MagicMock
        result = MagicMock()
        stdout_file = out_dir / "stdout.txt"
        stderr_file = out_dir / "stderr.txt"
        stdout_file.write_text(stdout, encoding="utf-8")
        stderr_file.write_text(stderr, encoding="utf-8")
        result.stdout_path = stdout_file
        result.stderr_path = stderr_file
        return result

    # ── smoke test 6 ──────────────────────────────────────────────────────────
    def test_call_once_save_doc_false_creates_no_directory(self) -> None:
        """_call_once with save_doc=False must not create any numbered stage directory."""
        import sys as _sys
        BACKEND = Path(__file__).resolve().parents[1] / "backend"
        if str(BACKEND) not in _sys.path:
            _sys.path.insert(0, str(BACKEND))

        from unittest.mock import MagicMock, patch
        from dormammu.daemon.pipeline_runner import PipelineRunner
        from dormammu.config import AppConfig
        from dormammu.agent.role_config import AgentsConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_git_repo(root)

            config = AppConfig.load(repo_root=root)
            agents = MagicMock(spec=AgentsConfig)

            runner = PipelineRunner(config, agents)

            fake_cli = root / "fake-agent"
            fake_cli.write_text("#!/bin/sh\necho 'ok'\n", encoding="utf-8")
            fake_cli.chmod(0o755)

            with patch("dormammu.agent.cli_adapter.CliAdapter.run_once") as mock_run:
                mock_run.return_value = self._make_adapter_result(root, stdout="done\n")

                runner._call_once(
                    role="refiner",
                    cli=fake_cli,
                    model=None,
                    prompt="Refine this.",
                    stem="test",
                    date_str="20260415",
                    save_doc=False,
                )

            logs_dir = config.logs_dir
            self.assertFalse(
                logs_dir.exists(),
                f".dev/logs/ must NOT be created when save_doc=False, but found {logs_dir}",
            )

    # ── smoke test 7 ──────────────────────────────────────────────────────────
    def test_call_once_save_doc_true_creates_directory(self) -> None:
        """_call_once with save_doc=True (default) creates .dev/logs/ (regression guard)."""
        import sys as _sys
        BACKEND = Path(__file__).resolve().parents[1] / "backend"
        if str(BACKEND) not in _sys.path:
            _sys.path.insert(0, str(BACKEND))

        from unittest.mock import MagicMock, patch
        from dormammu.daemon.pipeline_runner import PipelineRunner
        from dormammu.config import AppConfig
        from dormammu.agent.role_config import AgentsConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_git_repo(root)

            config = AppConfig.load(repo_root=root)
            agents = MagicMock(spec=AgentsConfig)

            runner = PipelineRunner(config, agents)

            fake_cli = root / "fake-agent"
            fake_cli.write_text("#!/bin/sh\necho 'ok'\n", encoding="utf-8")
            fake_cli.chmod(0o755)

            with patch("dormammu.agent.cli_adapter.CliAdapter.run_once") as mock_run:
                mock_run.return_value = self._make_adapter_result(root, stdout="done\n")

                runner._call_once(
                    role="tester",
                    cli=fake_cli,
                    model=None,
                    prompt="Run tests.",
                    stem="test",
                    date_str="20260415",
                    save_doc=True,
                )

            logs_dir = config.logs_dir
            self.assertTrue(
                logs_dir.exists(),
                ".dev/logs/ should be created when save_doc=True",
            )
            doc = logs_dir / "20260415_tester_test.md"
            self.assertTrue(
                doc.exists(),
                f"Expected document {doc} to exist in .dev/logs/",
            )


if __name__ == "__main__":
    unittest.main()
