from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
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

            session_state = repository.read_session_state()
            session_state["active_phase"] = "develop"
            repository.write_session_state(session_state)

            workflow_state = repository.read_workflow_state()
            workflow_state["workflow"]["active_phase"] = "plan"
            repository.write_workflow_state(workflow_state)

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

        payload = {
            "run_id": "seed-run",
            "cli_path": str(root / "fake-agent"),
            "workdir": str(root),
            "prompt_mode": "file",
            "command": [str(root / "fake-agent"), "--prompt-file", str(prompt_path)],
            "exit_code": 0,
            "started_at": "2026-04-08T00:00:00+09:00",
            "completed_at": "2026-04-08T00:00:01+09:00",
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
        if not plan_path.exists():
            session_id = repository.read_session_state().get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                plan_path = repository.for_session(session_id).state_file("PLAN.md")
        rewritten_lines = [
            line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
            for line in plan_path.read_text(encoding="utf-8").splitlines()
        ]
        plan_path.write_text("\n".join(rewritten_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
