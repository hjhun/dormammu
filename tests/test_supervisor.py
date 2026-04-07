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

    def _seed_latest_run(self, root: Path, repository: StateRepository) -> None:
        logs_dir = root / ".dev" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = logs_dir / "seed.prompt.txt"
        stdout_path = logs_dir / "seed.stdout.log"
        stderr_path = logs_dir / "seed.stderr.log"
        metadata_path = logs_dir / "seed.meta.json"

        prompt_path.write_text("phase 4 seed prompt\n", encoding="utf-8")
        stdout_path.write_text("ok\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")

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
