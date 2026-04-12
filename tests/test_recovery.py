from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.agent import cli_adapter as cli_adapter_module
from dormammu.config import AppConfig
from dormammu.loop_runner import LoopRunRequest, LoopRunner
from dormammu.recovery import RecoveryManager
from dormammu.state import StateRepository


class RecoveryManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(
            cli_adapter_module.time, "sleep", return_value=None
        )
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    def _write_loop_cli(
        self,
        root: Path,
        *,
        success_attempt: int,
        name: str = "fake-loop-agent",
    ) -> Path:
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import json, os, sys

                ROOT = Path({str(root)!r})
                SUCCESS_ATTEMPT = {success_attempt}
                COUNTER_PATH = ROOT / ".attempt-count"
                TARGET_PATH = ROOT / "done.txt"
                SESSION_PATH = ROOT / ".dev" / "session.json"
                _sdir = os.environ.get("DORMAMMU_SESSIONS_DIR", "").strip()
                sessions_dir = Path(_sdir) if _sdir else ROOT / ".dev" / "sessions"

                def mark_plan_complete() -> None:
                    if not SESSION_PATH.exists():
                        return
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    plan_path = sessions_dir / str(session_id) / "PLAN.md"
                    if not plan_path.exists():
                        return
                    lines = plan_path.read_text(encoding="utf-8").splitlines()
                    rewritten = [
                        line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                        for line in lines
                    ]
                    plan_path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

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
                        mark_plan_complete()

                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def _make_runner(self, root: Path) -> tuple[AppConfig, StateRepository, LoopRunner]:
        import os
        config = AppConfig.load(repo_root=root, env={**os.environ, "DORMAMMU_SESSIONS_DIR": str(root / "sessions")})
        repository = StateRepository(config)
        runner = LoopRunner(config, repository=repository)
        return config, repository, runner

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_resume_raises_when_no_loop_state_exists(self) -> None:
        """RecoveryManager.resume() must raise RuntimeError when no saved loop state is present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config, repository, runner = self._make_runner(root)
            repository.ensure_bootstrap_state()

            with self.assertRaises(RuntimeError) as ctx:
                RecoveryManager(config, repository=repository, loop_runner=runner).resume()

            self.assertIn("No saved loop state", str(ctx.exception))

    def test_resume_raises_on_blocked_supervisor_verdict(self) -> None:
        """RecoveryManager.resume() raises RuntimeError when the supervisor returns blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)
            config, repository, runner = self._make_runner(root)

            runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="blocked-resume",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            # Corrupt the workflow_state so the supervisor sees broken state
            session_json = root / ".dev" / "session.json"
            session_id = json.loads(session_json.read_text(encoding="utf-8"))["active_session_id"]
            ws_path = config.sessions_dir / session_id / "workflow_state.json"
            ws = json.loads(ws_path.read_text(encoding="utf-8"))
            ws["latest_run"] = None  # force supervisor "blocked" verdict
            ws_path.write_text(json.dumps(ws), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                RecoveryManager(config, repository=repository, loop_runner=runner).resume(
                    max_retries_override=1
                )

    def test_resume_continues_failed_loop_with_retries_override(self) -> None:
        """Resuming with max_retries_override=1 should retry and succeed on the second attempt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)
            config, repository, runner = self._make_runner(root)

            first = runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="retry-override",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )
            self.assertEqual(first.status, "failed")

            resumed = RecoveryManager(
                config, repository=repository, loop_runner=runner
            ).resume(max_retries_override=1)

            self.assertEqual(resumed.status, "completed")
            self.assertTrue((root / "done.txt").exists())

    def test_resume_restores_archived_session_before_continuing(self) -> None:
        """resume(session_id=...) should restore an archived session and continue from it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)
            config, repository, runner = self._make_runner(root)

            repository.start_new_session(
                goal="Session A",
                active_roadmap_phase_ids=["phase_4"],
                session_id="session-a",
            )
            first = runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="archived-retry",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )
            self.assertEqual(first.status, "failed")

            # Move to a different active session
            repository.start_new_session(
                goal="Session B",
                active_roadmap_phase_ids=["phase_7"],
                session_id="session-b",
            )

            resumed = RecoveryManager(
                config, repository=repository, loop_runner=runner
            ).resume(session_id="session-a", max_retries_override=1)

            self.assertEqual(resumed.status, "completed")
            self.assertEqual(repository.read_session_state()["session_id"], "session-a")

    def test_resume_returns_failed_when_iteration_budget_exhausted(self) -> None:
        """resume with max_retries_override=0 should return failed without running if budget is used up."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=3)
            config, repository, runner = self._make_runner(root)

            runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="budget-exhausted",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            resumed = RecoveryManager(
                config, repository=repository, loop_runner=runner
            ).resume(max_retries_override=0)

            self.assertEqual(resumed.status, "failed")
            self.assertEqual(resumed.attempts_completed, 1)
            # The fake CLI was only invoked once (during the original run)
            self.assertEqual(
                (root / ".attempt-count").read_text(encoding="utf-8").strip(), "1"
            )

    def test_resume_raises_when_loop_state_key_is_absent(self) -> None:
        """resume() must raise RuntimeError when the 'loop' key is missing from workflow_state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1)
            config, repository, runner = self._make_runner(root)

            runner.run(
                LoopRunRequest(
                    cli_path=fake_cli,
                    prompt_text="Create the required marker file.",
                    repo_root=root,
                    run_label="no-loop-key",
                    max_retries=0,
                    required_paths=("done.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            # Remove the 'loop' key from workflow_state so resume cannot reconstruct the request
            session_json = root / ".dev" / "session.json"
            session_id = json.loads(session_json.read_text(encoding="utf-8"))["active_session_id"]
            ws_path = config.sessions_dir / session_id / "workflow_state.json"
            ws = json.loads(ws_path.read_text(encoding="utf-8"))
            ws.pop("loop", None)
            ws_path.write_text(json.dumps(ws), encoding="utf-8")

            with self.assertRaises(RuntimeError) as ctx:
                RecoveryManager(config, repository=repository, loop_runner=runner).resume(
                    max_retries_override=1
                )

            self.assertIn("No saved loop state", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
