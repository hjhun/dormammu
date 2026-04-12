"""Tests for ANALYSIS.md improvement items:
BUG-01~03, DESIGN-01~04, UX-01~04, CODE-01~02, CODE-04.
"""
from __future__ import annotations

import contextlib
import io
import json
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.agent import cli_adapter as cli_adapter_module
from dormammu.config import AppConfig
from dormammu.continuation import _safe_artifact_ref, build_continuation_prompt
from dormammu.doctor import run_doctor
from dormammu.state import StateRepository
from dormammu.supervisor import SupervisorCheck, SupervisorReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_repo(root: Path) -> None:
    (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
    templates = root / "templates" / "dev"
    templates.mkdir(parents=True, exist_ok=True)
    (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
    (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")


def _write_fake_cli(root: Path, *, name: str = "fake-agent", exit_code: int = 0) -> Path:
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
                print("PROMPT::done")
                return {exit_code}

            raise SystemExit(main())
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_hanging_cli(root: Path, *, name: str = "hanging-agent") -> Path:
    """CLI that sleeps indefinitely to simulate a hung process."""
    script = root / name
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import time
            import sys

            def main() -> int:
                args = sys.argv[1:]
                if "--help" in args:
                    print("usage: {name} [--prompt-file PATH]")
                    return 0
                # Hang for a long time
                time.sleep(9999)
                return 0

            raise SystemExit(main())
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _make_report(
    *,
    verdict: str = "rework_required",
    checks: tuple = (),
    recommended_next_phase: str | None = None,
) -> SupervisorReport:
    return SupervisorReport(
        generated_at="2026-04-12T09:00:00+09:00",
        verdict=verdict,
        escalation=verdict,
        summary="Supervisor summary.",
        checks=checks,
        latest_run_id="run-001",
        changed_files=(),
        required_paths=(),
        report_path=None,
        recommended_next_phase=recommended_next_phase,
    )


# ---------------------------------------------------------------------------
# BUG-01: CLI Process Timeout
# ---------------------------------------------------------------------------

class CliAdapterTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self.sleep_mock = self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    def test_process_timeout_terminates_hanging_cli(self) -> None:
        """When process_timeout_seconds is set, a hung CLI is killed and timed_out=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            hanging_cli = _write_hanging_cli(root)

            config = AppConfig.load(repo_root=root).with_overrides(
                process_timeout_seconds=2,
            )
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=hanging_cli,
                    prompt_text="Simulate a hung agent.",
                    repo_root=root,
                    run_label="timeout-test",
                )
            )

            self.assertTrue(result.timed_out, "Expected timed_out=True for a hung process")
            self.assertEqual(result.exit_code, -1)
            stdout_text = result.stdout_path.read_text(encoding="utf-8")
            self.assertIn("timed out", stdout_text.lower())

    def test_no_timeout_when_process_timeout_seconds_is_none(self) -> None:
        """When process_timeout_seconds is None, normal processes complete without timed_out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            normal_cli = _write_fake_cli(root)

            config = AppConfig.load(repo_root=root).with_overrides(
                process_timeout_seconds=None,
            )
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=normal_cli,
                    prompt_text="Quick job.",
                    repo_root=root,
                    run_label="no-timeout-test",
                )
            )

            self.assertFalse(result.timed_out)
            self.assertEqual(result.exit_code, 0)

    def test_timeout_message_is_written_to_live_output_stream(self) -> None:
        """Timeout message is echoed to the live_output_stream (shell/Telegram)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            hanging_cli = _write_hanging_cli(root)

            config = AppConfig.load(repo_root=root).with_overrides(
                process_timeout_seconds=2,
            )
            live_stream = io.StringIO()
            with contextlib.redirect_stderr(live_stream):
                CliAdapter(config).run_once(
                    AgentRunRequest(
                        cli_path=hanging_cli,
                        prompt_text="Test live stream timeout.",
                        repo_root=root,
                        run_label="timeout-live-stream",
                    )
                )

            live_output = live_stream.getvalue()
            self.assertIn("timed out", live_output.lower())

    def test_timed_out_field_in_result_dict(self) -> None:
        """AgentRunResult.to_dict() includes timed_out field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            normal_cli = _write_fake_cli(root)

            config = AppConfig.load(repo_root=root)
            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=normal_cli,
                    prompt_text="Test dict.",
                    repo_root=root,
                )
            )

            d = result.to_dict()
            self.assertIn("timed_out", d)
            self.assertFalse(d["timed_out"])


# ---------------------------------------------------------------------------
# BUG-02: Continuation prompt path safety
# ---------------------------------------------------------------------------

class ContinuationPathSafetyTests(unittest.TestCase):
    def test_safe_artifact_ref_returns_path_when_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "artifact.txt"
            path.write_text("content", encoding="utf-8")
            self.assertEqual(_safe_artifact_ref(str(path)), str(path))

    def test_safe_artifact_ref_marks_missing_path(self) -> None:
        self.assertIn("(missing)", _safe_artifact_ref("/nonexistent/path/artifact.txt"))

    def test_safe_artifact_ref_returns_unknown_for_none(self) -> None:
        self.assertEqual(_safe_artifact_ref(None), "unknown")
        self.assertEqual(_safe_artifact_ref(""), "unknown")

    def test_continuation_prompt_marks_missing_artifact_paths(self) -> None:
        """When artifact files do not exist, continuation prompt marks them as (missing)."""
        report = _make_report()

        continuation = build_continuation_prompt(
            latest_run={
                "run_id": "r-missing",
                "artifacts": {
                    "prompt": "/tmp/nonexistent-prompt.txt",
                    "stdout": "/tmp/nonexistent-stdout.log",
                    "stderr": "/tmp/nonexistent-stderr.log",
                },
            },
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
        )

        self.assertIn("(missing)", continuation.text)

    def test_continuation_prompt_shows_valid_paths_without_missing_marker(self) -> None:
        """When artifact files exist, continuation prompt shows clean paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            prompt_path.write_text("Test prompt.", encoding="utf-8")

            report = _make_report()
            continuation = build_continuation_prompt(
                latest_run={
                    "run_id": "r-valid",
                    "artifacts": {
                        "prompt": str(prompt_path),
                        "stdout": "",
                        "stderr": "",
                    },
                },
                report=report,
                next_task="Continue",
                original_prompt_text="Do the work.",
            )

        # The existing prompt path should not be marked as missing
        self.assertNotIn(f"{prompt_path} (missing)", continuation.text)
        self.assertIn(str(prompt_path), continuation.text)


# ---------------------------------------------------------------------------
# BUG-03: PLAN.md mtime-based change detection
# ---------------------------------------------------------------------------

class PlanMtimeDetectionTests(unittest.TestCase):
    def test_sync_operator_state_records_plan_mtime(self) -> None:
        """After sync_operator_state, session.json contains plan_mtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(prompt_text="Write tests.", active_roadmap_phase_ids=["phase_3"])
            repo.sync_operator_state()

            # The active session repository should have plan_mtime recorded
            session_state = repo.read_session_state()
            self.assertIn("plan_mtime", session_state, "plan_mtime should be recorded in session.json")
            self.assertIsInstance(session_state["plan_mtime"], float)

    def test_sync_operator_state_emits_warning_on_external_modification(self) -> None:
        """When PLAN.md is externally modified, a warning is printed to stderr."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(prompt_text="Write tests.", active_roadmap_phase_ids=["phase_3"])
            repo.sync_operator_state()

            # Manually write a fake old mtime into session.json to simulate drift
            session_state = repo.read_session_state()
            # Inject an old mtime (1 day ago) to simulate external modification
            session_state["plan_mtime"] = session_state["plan_mtime"] - 86400.0
            repo.write_session_state(session_state)

            # Now modify PLAN.md externally
            active_session_id = session_state.get("active_session_id") or session_state.get("session_id")
            if active_session_id:
                plan_path = root / ".dev" / "sessions" / str(active_session_id) / "PLAN.md"
                if plan_path.exists():
                    plan_path.write_text(
                        plan_path.read_text(encoding="utf-8") + "\n<!-- manual edit -->\n",
                        encoding="utf-8",
                    )

            # sync_operator_state should warn about the mtime drift
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                repo.sync_operator_state()

            stderr_output = captured.getvalue()
            # Warning should mention mtime drift
            self.assertIn("Warning", stderr_output)


# ---------------------------------------------------------------------------
# DESIGN-01: blocked escalation banner
# ---------------------------------------------------------------------------

class BlockedEscalationTests(unittest.TestCase):
    def test_emit_escalation_banner_writes_blocked_notice(self) -> None:
        """LoopRunner writes a prominent BLOCKED banner when verdict is blocked."""
        from dormammu.loop_runner import LoopRunner
        from dormammu.config import AppConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            progress = io.StringIO()
            runner = LoopRunner(config, progress_stream=progress)

            report = SupervisorReport(
                generated_at="2026-04-12T09:00:00+09:00",
                verdict="blocked",
                escalation="blocked",
                summary="Critical .dev state is missing.",
                checks=(),
                latest_run_id="run-x",
                changed_files=(),
                required_paths=(),
                report_path=None,
            )
            runner._emit_escalation_banner(status="blocked", report=report, attempt_number=1)

        output = progress.getvalue()
        self.assertIn("ESCALATION", output)
        self.assertIn("BLOCKED", output)
        self.assertIn("Manual intervention", output)
        self.assertIn("dormammu resume", output)

    def test_emit_escalation_banner_writes_manual_review_notice(self) -> None:
        """LoopRunner writes a prominent banner when verdict is manual_review_needed."""
        from dormammu.loop_runner import LoopRunner

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            progress = io.StringIO()
            runner = LoopRunner(config, progress_stream=progress)

            report = SupervisorReport(
                generated_at="2026-04-12T09:00:00+09:00",
                verdict="manual_review_needed",
                escalation="manual_review_needed",
                summary="Git diff evidence could not be collected.",
                checks=(),
                latest_run_id="run-y",
                changed_files=(),
                required_paths=(),
                report_path=None,
            )
            runner._emit_escalation_banner(
                status="manual_review_needed", report=report, attempt_number=2
            )

        output = progress.getvalue()
        self.assertIn("ESCALATION", output)
        self.assertIn("MANUAL_REVIEW_NEEDED", output)


# ---------------------------------------------------------------------------
# DESIGN-02: fallback on nonzero exit
# ---------------------------------------------------------------------------

class FallbackOnNonzeroExitTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        cli_adapter_module._cli_calls_started = 0
        self._sleep_patcher = mock.patch.object(cli_adapter_module.time, "sleep", return_value=None)
        self.sleep_mock = self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()
        super().tearDown()

    def test_fallback_on_nonzero_exit_triggers_fallback_cli(self) -> None:
        """When fallback_on_nonzero_exit=True and primary fails, fallback CLI is used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            # Primary CLI always fails
            failing_cli = _write_fake_cli(root, name="failing-agent", exit_code=1)
            # Fallback CLI succeeds
            fallback_cli = _write_fake_cli(root, name="fallback-agent", exit_code=0)

            (root / "dormammu.json").write_text(
                json.dumps({
                    "active_agent_cli": str(failing_cli),
                    "fallback_agent_clis": [str(fallback_cli)],
                    "fallback_on_nonzero_exit": True,
                }),
                encoding="utf-8",
            )
            config = AppConfig.load(repo_root=root)

            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=failing_cli,
                    prompt_text="Test fallback.",
                    repo_root=root,
                    run_label="fallback-nonzero-test",
                )
            )

            # The result should come from the fallback CLI
            self.assertEqual(result.exit_code, 0)
            self.assertIn(str(fallback_cli), [str(p) for p in result.attempted_cli_paths])
            self.assertIsNotNone(result.fallback_trigger)
            self.assertIn("non-zero exit code", result.fallback_trigger)

    def test_fallback_on_nonzero_exit_disabled_by_default(self) -> None:
        """Without fallback_on_nonzero_exit, a non-token-exhaustion failure does not trigger fallback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            failing_cli = _write_fake_cli(root, name="failing-agent", exit_code=1)
            fallback_cli = _write_fake_cli(root, name="fallback-agent", exit_code=0)

            (root / "dormammu.json").write_text(
                json.dumps({
                    "active_agent_cli": str(failing_cli),
                    "fallback_agent_clis": [str(fallback_cli)],
                    # fallback_on_nonzero_exit defaults to False
                }),
                encoding="utf-8",
            )
            config = AppConfig.load(repo_root=root)

            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=failing_cli,
                    prompt_text="Test no fallback.",
                    repo_root=root,
                    run_label="no-fallback-nonzero-test",
                )
            )

            # Should stay with failing CLI (no fallback triggered)
            self.assertEqual(result.exit_code, 1)
            self.assertIsNone(result.fallback_trigger)

    def test_timed_out_process_does_not_trigger_nonzero_fallback(self) -> None:
        """A timed-out process should NOT trigger fallback_on_nonzero_exit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            hanging_cli = _write_hanging_cli(root)
            fallback_cli = _write_fake_cli(root, name="fallback-agent", exit_code=0)

            (root / "dormammu.json").write_text(
                json.dumps({
                    "active_agent_cli": str(hanging_cli),
                    "fallback_agent_clis": [str(fallback_cli)],
                    "fallback_on_nonzero_exit": True,
                    "process_timeout_seconds": 2,
                }),
                encoding="utf-8",
            )
            config = AppConfig.load(repo_root=root)

            result = CliAdapter(config).run_once(
                AgentRunRequest(
                    cli_path=hanging_cli,
                    prompt_text="Timeout no fallback.",
                    repo_root=root,
                    run_label="timeout-no-fallback",
                )
            )

            # Timed-out processes should NOT fall back to the next CLI
            self.assertTrue(result.timed_out)
            # Fallback trigger should be None (timeout is not a nonzero-exit trigger)
            self.assertIsNone(result.fallback_trigger)


# ---------------------------------------------------------------------------
# DESIGN-03: daemon prompt file deletion
# ---------------------------------------------------------------------------

class DaemonPromptDeletionTests(unittest.TestCase):
    def test_process_prompt_handles_deleted_prompt_file(self) -> None:
        """If prompt file is deleted before processing, DaemonRunner returns 'skipped'."""
        from dormammu.daemon.runner import DaemonRunner
        from dormammu.daemon.models import DaemonConfig, WatchConfig, QueueConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            prompt_path = root / "prompts"
            result_path = root / "results"
            prompt_path.mkdir()
            result_path.mkdir()

            config = AppConfig.load(repo_root=root)
            daemon_config = DaemonConfig(
                schema_version=1,
                config_path=root / "daemonize.json",
                prompt_path=prompt_path,
                result_path=result_path,
                watch=WatchConfig(),
                queue=QueueConfig(),
            )

            runner = DaemonRunner(config, daemon_config)

            # Create a prompt file then delete it
            prompt_file = prompt_path / "test_prompt.md"
            prompt_file.write_text("Do something.\n", encoding="utf-8")
            prompt_file.unlink()  # Delete before processing

            from dormammu.daemon.queue import prompt_sort_key
            sort_key = prompt_sort_key(prompt_file.name)
            result = runner._process_prompt(prompt_file, watcher_backend="polling")

            self.assertEqual(result.status, "skipped")
            self.assertIsNotNone(result.error)
            self.assertIn("deleted", result.error.lower())


# ---------------------------------------------------------------------------
# UX-01: Better error message for missing agent CLI
# ---------------------------------------------------------------------------

class AgentCliErrorMessageTests(unittest.TestCase):
    def test_resolve_agent_cli_error_message_includes_fix_instructions(self) -> None:
        """_resolve_agent_cli error message gives actionable guidance."""
        from dormammu.cli import _resolve_agent_cli

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root).with_overrides(active_agent_cli=None)

            with self.assertRaises(ValueError) as ctx:
                _resolve_agent_cli(config, None)

            error_msg = str(ctx.exception)
            self.assertIn("set-config", error_msg)
            self.assertIn("doctor", error_msg)


# ---------------------------------------------------------------------------
# UX-04: doctor configured_agent_cli check
# ---------------------------------------------------------------------------

class DoctorConfiguredAgentCliTests(unittest.TestCase):
    def test_doctor_reports_missing_active_agent_cli_config(self) -> None:
        """When active_agent_cli is not configured, doctor reports it as an issue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            report = run_doctor(
                repo_root=root,
                active_agent_cli_from_config=None,
            )

        check_names = {check.name for check in report.checks}
        self.assertIn("configured_agent_cli", check_names)
        configured_check = next(c for c in report.checks if c.name == "configured_agent_cli")
        self.assertFalse(configured_check.ok)
        self.assertIn("set-config", configured_check.summary)

    def test_doctor_reports_valid_configured_agent_cli(self) -> None:
        """When active_agent_cli is configured and valid, doctor check passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            fake_cli = _write_fake_cli(root)
            report = run_doctor(
                repo_root=root,
                active_agent_cli_from_config=fake_cli,
            )

        check_names = {check.name for check in report.checks}
        self.assertIn("configured_agent_cli", check_names)
        configured_check = next(c for c in report.checks if c.name == "configured_agent_cli")
        self.assertTrue(configured_check.ok)

    def test_doctor_reports_nonexistent_active_agent_cli(self) -> None:
        """When active_agent_cli points to nonexistent path, doctor check fails with clear message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            report = run_doctor(
                repo_root=root,
                active_agent_cli_from_config=Path("/nonexistent/path/to/agent"),
            )

        configured_check = next(c for c in report.checks if c.name == "configured_agent_cli")
        self.assertFalse(configured_check.ok)
        self.assertIn("does not exist", configured_check.summary)


# ---------------------------------------------------------------------------
# UX-02: resume state summary emission
# ---------------------------------------------------------------------------

class ResumeSummaryTests(unittest.TestCase):
    def test_emit_resume_state_summary_shows_key_fields(self) -> None:
        """_emit_resume_state_summary prints status, attempts, and verdict to stderr."""
        from dormammu.cli import _emit_resume_state_summary

        workflow_state = {"next_action": "workflow-level action"}
        loop_state = {
            "status": "failed",
            "attempts_completed": 3,
            "retries_used": 2,
            "max_retries": 10,
            "latest_supervisor_verdict": "rework_required",
            "next_action": "Fix the tests.",
            "latest_supervisor_report_path": ".dev/supervisor_report.md",
        }

        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            _emit_resume_state_summary(workflow_state, loop_state)

        output = captured.getvalue()
        self.assertIn("failed", output)
        self.assertIn("3", output)         # attempts_completed
        self.assertIn("rework_required", output)
        self.assertIn("Fix the tests.", output)

    def test_emit_resume_state_summary_handles_empty_loop_state(self) -> None:
        """_emit_resume_state_summary does not crash on empty dicts."""
        from dormammu.cli import _emit_resume_state_summary

        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            _emit_resume_state_summary({}, {})

        output = captured.getvalue()
        self.assertIn("=== dormammu resume state ===", output)


# ---------------------------------------------------------------------------
# UX-03: sessions list includes goal
# ---------------------------------------------------------------------------

class SessionsListGoalTests(unittest.TestCase):
    def test_list_sessions_includes_goal(self) -> None:
        """list_sessions includes the 'goal' field from bootstrap."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(
                goal="Implement the feature X",
                active_roadmap_phase_ids=["phase_3"],
            )

            sessions = repo.list_sessions()
            self.assertTrue(len(sessions) > 0)
            session = sessions[0]
            self.assertIn("goal", session)
            # Goal should contain the text (may be truncated)
            goal = session["goal"] or ""
            self.assertIn("Implement", goal)

    def test_list_sessions_includes_supervisor_verdict(self) -> None:
        """list_sessions includes 'supervisor_verdict' and 'attempts_completed'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_3"])

            sessions = repo.list_sessions()
            self.assertTrue(len(sessions) > 0)
            session = sessions[0]
            self.assertIn("supervisor_verdict", session)
            self.assertIn("attempts_completed", session)

    def test_list_sessions_truncates_long_goals(self) -> None:
        """Long goals are truncated to 120 chars with ellipsis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            long_goal = "A" * 200
            repo.ensure_bootstrap_state(
                goal=long_goal,
                active_roadmap_phase_ids=["phase_3"],
            )

            sessions = repo.list_sessions()
            self.assertTrue(len(sessions) > 0)
            goal = sessions[0]["goal"] or ""
            self.assertLessEqual(len(goal), 125)  # 120 + "..."


# ---------------------------------------------------------------------------
# Config: process_timeout_seconds and fallback_on_nonzero_exit loading
# ---------------------------------------------------------------------------

class AppConfigTimeoutAndFallbackTests(unittest.TestCase):
    def test_process_timeout_seconds_loaded_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            (root / "dormammu.json").write_text(
                json.dumps({"process_timeout_seconds": 300}),
                encoding="utf-8",
            )
            config = AppConfig.load(repo_root=root)
            self.assertEqual(config.process_timeout_seconds, 300)

    def test_process_timeout_seconds_defaults_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            self.assertIsNone(config.process_timeout_seconds)

    def test_fallback_on_nonzero_exit_loaded_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            (root / "dormammu.json").write_text(
                json.dumps({"fallback_on_nonzero_exit": True}),
                encoding="utf-8",
            )
            config = AppConfig.load(repo_root=root)
            self.assertTrue(config.fallback_on_nonzero_exit)

    def test_fallback_on_nonzero_exit_defaults_to_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            self.assertFalse(config.fallback_on_nonzero_exit)

    def test_config_to_dict_includes_new_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root).with_overrides(
                process_timeout_seconds=120,
                fallback_on_nonzero_exit=True,
            )
            d = config.to_dict()
            self.assertEqual(d["process_timeout_seconds"], 120)
            self.assertTrue(d["fallback_on_nonzero_exit"])


# ---------------------------------------------------------------------------
# DESIGN-04: Root .dev file locking (fcntl.flock)
# ---------------------------------------------------------------------------

class RootIndexLockTests(unittest.TestCase):
    def test_lock_file_created_on_write_root_index(self) -> None:
        """_write_root_index_for_session creates a .dev_lock file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_1"])

            lock_path = config.base_dev_dir / ".dev_lock"
            self.assertTrue(lock_path.exists(), ".dev_lock should be created by _write_root_index_for_session")

    def test_root_index_lock_is_reentrant_on_same_instance(self) -> None:
        """_root_index_lock can be acquired and released without deadlock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_1"])

            # Acquire and release lock twice to confirm no deadlock
            with repo._root_index_lock():
                pass
            with repo._root_index_lock():
                pass

    def test_concurrent_writes_do_not_corrupt_root_session_json(self) -> None:
        """Simulated concurrent writes to root session.json remain consistent under lock."""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_1"])

            errors: list[Exception] = []

            def _write_session(session_suffix: str) -> None:
                try:
                    with repo._root_index_lock():
                        session_path = config.base_dev_dir / "session.json"
                        if session_path.exists():
                            payload = json.loads(session_path.read_text(encoding="utf-8"))
                        else:
                            payload = {}
                        payload["test_marker"] = session_suffix
                        session_path.write_text(json.dumps(payload), encoding="utf-8")
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=_write_session, args=(f"t{i}",)) for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [], f"Lock write errors: {errors}")
            # Final state must be valid JSON
            payload = json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))
            self.assertIn("test_marker", payload)


# ---------------------------------------------------------------------------
# CODE-04: Supervisor worktree diff TTL cache
# ---------------------------------------------------------------------------

class SupervisorWorktreeDiffCacheTests(unittest.TestCase):
    def test_worktree_diff_cache_is_used_within_ttl(self) -> None:
        """Second call to _collect_worktree_diff within TTL returns cached result without running git."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)

            from dormammu.supervisor import Supervisor
            supervisor = Supervisor(config)

            call_count = 0
            original_run = __import__("subprocess").run

            def counting_run(cmd, *args, **kwargs):
                nonlocal call_count
                if "git" in cmd and "status" in cmd:
                    call_count += 1
                return original_run(cmd, *args, **kwargs)

            with mock.patch("dormammu.supervisor.subprocess.run", side_effect=counting_run):
                supervisor._collect_worktree_diff()
                supervisor._collect_worktree_diff()
                supervisor._collect_worktree_diff()

            # git status should only be called once — subsequent calls hit the cache
            self.assertEqual(call_count, 1, "git status should be called only once within TTL")

    def test_worktree_diff_cache_expires_after_ttl(self) -> None:
        """Cache is bypassed when TTL has expired."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)

            from dormammu.supervisor import Supervisor
            supervisor = Supervisor(config)
            supervisor._WORKTREE_DIFF_CACHE_TTL_SECONDS = 0.0  # immediate expiry

            call_count = 0
            original_run = __import__("subprocess").run

            def counting_run(cmd, *args, **kwargs):
                nonlocal call_count
                if "git" in cmd and "status" in cmd:
                    call_count += 1
                return original_run(cmd, *args, **kwargs)

            with mock.patch("dormammu.supervisor.subprocess.run", side_effect=counting_run):
                supervisor._collect_worktree_diff()
                supervisor._collect_worktree_diff()

            # Both calls should hit git because TTL=0 means immediate expiry
            self.assertGreaterEqual(call_count, 2, "git status should run on each call when TTL=0")

    def test_worktree_diff_result_is_consistent_with_cache(self) -> None:
        """Cached result matches fresh result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            from dormammu.supervisor import Supervisor
            import subprocess
            subprocess.run(["git", "init", str(root)], capture_output=True)
            config = AppConfig.load(repo_root=root)
            supervisor = Supervisor(config)

            first = supervisor._collect_worktree_diff()
            second = supervisor._collect_worktree_diff()  # from cache

            self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# CODE-01: CLI module split — _cli_utils and _cli_handlers are importable
# ---------------------------------------------------------------------------

class CliModuleSplitTests(unittest.TestCase):
    def test_cli_utils_importable(self) -> None:
        """dormammu._cli_utils module is importable and exposes expected helpers."""
        from dormammu import _cli_utils
        self.assertTrue(callable(_cli_utils._load_config))
        self.assertTrue(callable(_cli_utils._resolve_agent_cli))
        self.assertTrue(callable(_cli_utils._emit_resume_state_summary))
        self.assertTrue(callable(_cli_utils._emit_runtime_banner))

    def test_cli_handlers_importable(self) -> None:
        """dormammu._cli_handlers module is importable and exposes all _handle_* functions."""
        from dormammu import _cli_handlers
        for name in (
            "_handle_show_config",
            "_handle_set_config",
            "_handle_init_state",
            "_handle_run_once",
            "_handle_run_loop",
            "_handle_resume_loop",
            "_handle_doctor",
            "_handle_daemonize",
        ):
            self.assertTrue(callable(getattr(_cli_handlers, name)), f"{name} should be callable")

    def test_cli_re_exports_backward_compat_names(self) -> None:
        """dormammu.cli still exports functions that tests and scripts relied on."""
        from dormammu.cli import (
            _resolve_agent_cli,
            _emit_resume_state_summary,
            _TeeStream,
            _project_log_capture,
        )
        self.assertTrue(callable(_resolve_agent_cli))
        self.assertTrue(callable(_emit_resume_state_summary))
        self.assertTrue(callable(_project_log_capture))

    def test_cli_py_line_count_reduced(self) -> None:
        """cli.py should be substantially smaller after the split (< 600 lines)."""
        cli_path = Path(__file__).resolve().parents[1] / "backend" / "dormammu" / "cli.py"
        line_count = len(cli_path.read_text(encoding="utf-8").splitlines())
        self.assertLess(line_count, 600, f"cli.py has {line_count} lines — should be < 600 after split")


# ---------------------------------------------------------------------------
# CODE-02: state/tasks.py has docstrings
# ---------------------------------------------------------------------------

class TasksModuleDocstringTests(unittest.TestCase):
    def test_module_has_docstring(self) -> None:
        """state/tasks.py should have a module-level docstring."""
        from dormammu.state import tasks as tasks_module
        self.assertIsNotNone(tasks_module.__doc__)
        self.assertGreater(len((tasks_module.__doc__ or "").strip()), 0)

    def test_parse_tasks_document_has_docstring(self) -> None:
        """parse_tasks_document function has a docstring."""
        from dormammu.state.tasks import parse_tasks_document
        self.assertIsNotNone(parse_tasks_document.__doc__)
        self.assertGreater(len((parse_tasks_document.__doc__ or "").strip()), 0)

    def test_parsed_tasks_document_class_has_docstring(self) -> None:
        """ParsedTasksDocument dataclass has a docstring."""
        from dormammu.state.tasks import ParsedTasksDocument
        self.assertIsNotNone(ParsedTasksDocument.__doc__)


if __name__ == "__main__":
    unittest.main()
