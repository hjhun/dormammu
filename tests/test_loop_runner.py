from __future__ import annotations

import json
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
from dormammu.loop_runner import LoopRunRequest, LoopRunner
from dormammu.recovery import RecoveryManager
from dormammu.state import StateRepository


class LoopRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    def test_run_completes_after_retry_and_writes_continuation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            config = AppConfig.load(repo_root=root)
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
            session_id = json.loads((root / ".dev" / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            self.assertTrue(
                (root / ".dev" / "sessions" / session_id / "continuation_prompt.txt").exists()
            )
            self.assertTrue((root / ".dev" / "sessions" / session_id / "PLAN.md").exists())
            continuation_text = (
                root / ".dev" / "sessions" / session_id / "continuation_prompt.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("Work inside the current repository and its active workdir by default.", continuation_text)
            self.assertIn("Do not inspect or modify unrelated paths outside the repository", continuation_text)
            self.assertIn("leave planning mode now and make the required repository edits directly", continuation_text)

    def test_retry_prompt_keeps_original_prompt_instead_of_nesting_previous_retry_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=3)

            config = AppConfig.load(repo_root=root)
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
            session_id = json.loads((root / ".dev" / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            prompt_dir = root / ".dev" / "sessions" / session_id / "logs"
            prompt_paths = sorted(prompt_dir.glob("*.prompt.txt"))
            self.assertEqual(len(prompt_paths), 3)
            third_prompt = prompt_paths[-1].read_text(encoding="utf-8")
            self.assertEqual(third_prompt.count("Original prompt:"), 1)
            self.assertIn("Build a /proc-based memory CLI and create the marker file.", third_prompt)

    def test_resume_continues_failed_loop_from_saved_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            config = AppConfig.load(repo_root=root)
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
            session_id = json.loads((root / ".dev" / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            self.assertTrue(
                (root / ".dev" / "sessions" / session_id / "continuation_prompt.txt").exists()
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

            config = AppConfig.load(repo_root=root)
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

            config = AppConfig.load(repo_root=root)
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

            config = AppConfig.load(repo_root=root)
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
            self.assertEqual((root / ".attempt-count").read_text(encoding="utf-8").strip(), "1")

    def test_run_retries_until_plan_items_are_marked_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1, plan_completion_attempt=2)

            config = AppConfig.load(repo_root=root)
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

            config = AppConfig.load(repo_root=root)
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

    def test_failed_final_verification_sets_resume_phase_to_develop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=1, plan_completion_attempt=1)

            config = AppConfig.load(repo_root=root)
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
            session_id = json.loads((root / ".dev" / "session.json").read_text(encoding="utf-8"))[
                "active_session_id"
            ]
            workflow_state = (
                root / ".dev" / "sessions" / session_id / "workflow_state.json"
            ).read_text(encoding="utf-8")
            payload = json.loads(workflow_state)
            self.assertEqual(payload["workflow"]["resume_from_phase"], "develop")
            continuation_text = (
                root / ".dev" / "sessions" / session_id / "continuation_prompt.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("Recommended resume phase: develop", continuation_text)

    def test_resume_does_not_run_again_when_total_iteration_budget_is_already_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_loop_cli(root, success_attempt=2)

            config = AppConfig.load(repo_root=root)
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

            config = AppConfig.load(repo_root=root)
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

            config = AppConfig.load(repo_root=root)
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
            config = AppConfig.load(repo_root=root)
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

            config = AppConfig.load(repo_root=root)
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

            config = AppConfig.load(repo_root=root)
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

            config = AppConfig.load(repo_root=root)
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

    def _write_loop_cli(
        self,
        root: Path,
        *,
        success_attempt: int,
        plan_completion_attempt: int | None = None,
        name: str = "fake-loop-agent",
        mark_root_plan: bool = False,
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
                COUNTER_PATH = ROOT / ".attempt-count"
                TARGET_PATH = ROOT / "done.txt"
                SESSION_PATH = ROOT / ".dev" / "session.json"

                def mark_plan_complete() -> None:
                    if MARK_ROOT_PLAN:
                        plan_path = ROOT / ".dev" / "PLAN.md"
                        if not plan_path.exists():
                            return
                        lines = plan_path.read_text(encoding="utf-8").splitlines()
                        rewritten = [
                            line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                            for line in lines
                        ]
                        plan_path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")
                        return
                    if not SESSION_PATH.exists():
                        return
                    import json
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    plan_path = ROOT / ".dev" / "sessions" / str(session_id) / "PLAN.md"
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
        """Fake CLI that creates done.txt, marks PLAN complete, then git-commits everything.

        This simulates an agent that commits its changes so the worktree is clean
        when the supervisor runs.  The supervisor must detect the commit as progress
        evidence instead of returning rework_required.
        """
        script = root / name
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import json, subprocess, sys
                from pathlib import Path

                ROOT = Path({str(root)!r})
                TARGET_PATH = ROOT / "done.txt"
                SESSION_PATH = ROOT / ".dev" / "session.json"

                def mark_plan_complete() -> None:
                    if not SESSION_PATH.exists():
                        return
                    payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    session_id = payload.get("active_session_id") or payload.get("session_id")
                    if not session_id:
                        return
                    plan_path = ROOT / ".dev" / "sessions" / str(session_id) / "PLAN.md"
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


if __name__ == "__main__":
    unittest.main()
