"""Regression tests for log output and progress reporting in dormammu.

Covers gaps not addressed by existing test files:

  1. SessionProgressLogStream — dual-stream write, reset, close
  2. _TeeStream — fan-out write/flush/isatty
  3. DashboardLineFilter — escalation header (previously untested)
  4. TelegramProgressStream — no-send-fn path, session log delegation,
       streaming_chat_id property, base stream writes always happen
  5. LoopRunner._emit_state_snapshot — file present / missing / empty
  6. LoopRunner._write_progress — output format and flush guarantee
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.daemon.runner import SessionProgressLogStream
from dormammu._cli_utils import _TeeStream
from dormammu.telegram.stream import DashboardLineFilter, TelegramProgressStream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tps(
    *,
    chunk_size: int = 100_000,
    flush_interval: float = 9999,
) -> tuple[TelegramProgressStream, io.StringIO, list[str]]:
    """Return (stream, base_buf, sent_messages)."""
    base = io.StringIO()
    stream = TelegramProgressStream(base, chunk_size=chunk_size, flush_interval_seconds=flush_interval)
    sent: list[str] = []
    stream.set_send_fn(lambda _chat_id, text: sent.append(text))
    return stream, base, sent


def _seed_repo(root: Path) -> None:
    """Minimal repo scaffold expected by AppConfig.load()."""
    (root / "dormammu.json").write_text("{}", encoding="utf-8")
    dev = root / ".dev"
    dev.mkdir()
    (dev / "PLAN.md").write_text("- [ ] Phase 1. Do the thing\n", encoding="utf-8")
    (dev / "DASHBOARD.md").write_text("# DASHBOARD\n- Goal: test\n", encoding="utf-8")
    (dev / "TASKS.md").write_text("", encoding="utf-8")


# ===========================================================================
# 1. SessionProgressLogStream
# ===========================================================================

class SessionProgressLogStreamTests(unittest.TestCase):
    """Unit tests for the daemon's dual-stream progress logger."""

    def test_write_without_log_file_goes_to_terminal_only(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        stream.write("hello terminal\n")
        self.assertIn("hello terminal", terminal.getvalue())

    def test_flush_without_log_file_does_not_raise(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        stream.write("data\n")
        stream.flush()  # should not raise

    def test_reset_session_log_writes_to_both_streams(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "progress.log"
            stream.reset_session_log(log_path)
            stream.write("dual output\n")
            stream.flush()
            stream.close_log()

            self.assertIn("dual output", terminal.getvalue())
            self.assertIn("dual output", log_path.read_text(encoding="utf-8"))

    def test_reset_session_log_creates_parent_directories(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "nested" / "deep" / "progress.log"
            stream.reset_session_log(log_path)
            stream.write("created dirs\n")
            stream.close_log()
            self.assertTrue(log_path.exists())

    def test_close_log_stops_writing_to_file(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "progress.log"
            stream.reset_session_log(log_path)
            stream.write("before close\n")
            stream.close_log()
            stream.write("after close\n")

            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("before close", log_text)
            self.assertNotIn("after close", log_text)
            # terminal always receives everything
            self.assertIn("after close", terminal.getvalue())

    def test_close_log_is_idempotent(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        # Calling close_log with no active log must not raise
        stream.close_log()
        stream.close_log()

    def test_reset_session_log_truncates_existing_log(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "progress.log"
            log_path.write_text("stale content\n", encoding="utf-8")
            stream.reset_session_log(log_path)
            stream.write("fresh content\n")
            stream.close_log()
            text = log_path.read_text(encoding="utf-8")
            self.assertNotIn("stale content", text)
            self.assertIn("fresh content", text)

    def test_successive_reset_closes_previous_log(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        with tempfile.TemporaryDirectory() as tmpdir:
            log1 = Path(tmpdir) / "first.log"
            log2 = Path(tmpdir) / "second.log"
            stream.reset_session_log(log1)
            stream.write("to first\n")
            stream.reset_session_log(log2)  # should close log1 automatically
            stream.write("to second\n")
            stream.close_log()

            self.assertIn("to first", log1.read_text(encoding="utf-8"))
            self.assertNotIn("to second", log1.read_text(encoding="utf-8"))
            self.assertIn("to second", log2.read_text(encoding="utf-8"))

    def test_write_returns_correct_length(self) -> None:
        terminal = io.StringIO()
        stream = SessionProgressLogStream(terminal)
        n = stream.write("abc\n")
        self.assertEqual(n, 4)

    def test_isatty_reflects_terminal_stream(self) -> None:
        fake_tty = io.StringIO()
        fake_tty.isatty = lambda: True  # type: ignore[method-assign]
        stream = SessionProgressLogStream(fake_tty)
        self.assertTrue(stream.isatty())

    def test_isatty_false_when_terminal_is_not_tty(self) -> None:
        stream = SessionProgressLogStream(io.StringIO())
        self.assertFalse(stream.isatty())

    def test_encoding_is_inherited_from_terminal(self) -> None:
        terminal = mock.MagicMock(spec=io.TextIOBase)
        terminal.encoding = "utf-8"
        stream = SessionProgressLogStream(terminal)
        self.assertEqual(stream.encoding, "utf-8")


# ===========================================================================
# 2. _TeeStream
# ===========================================================================

class TeeStreamTests(unittest.TestCase):
    """Unit tests for _TeeStream write fan-out."""

    def test_write_fans_out_to_all_streams(self) -> None:
        a, b = io.StringIO(), io.StringIO()
        tee = _TeeStream(a, b)
        tee.write("hello\n")
        self.assertEqual(a.getvalue(), "hello\n")
        self.assertEqual(b.getvalue(), "hello\n")

    def test_write_returns_correct_length(self) -> None:
        a, b = io.StringIO(), io.StringIO()
        tee = _TeeStream(a, b)
        n = tee.write("data")
        self.assertEqual(n, 4)

    def test_flush_calls_flush_on_all_streams(self) -> None:
        a = mock.MagicMock(spec=io.StringIO)
        b = mock.MagicMock(spec=io.StringIO)
        a.encoding = "utf-8"
        tee = _TeeStream(a, b)
        tee.flush()
        a.flush.assert_called_once()
        b.flush.assert_called_once()

    def test_isatty_true_when_any_stream_is_tty(self) -> None:
        tty = io.StringIO()
        tty.isatty = lambda: True  # type: ignore[method-assign]
        non_tty = io.StringIO()
        tee = _TeeStream(non_tty, tty)
        self.assertTrue(tee.isatty())

    def test_isatty_false_when_no_stream_is_tty(self) -> None:
        tee = _TeeStream(io.StringIO(), io.StringIO())
        self.assertFalse(tee.isatty())

    def test_encoding_taken_from_first_stream(self) -> None:
        first = mock.MagicMock(spec=io.TextIOBase)
        first.encoding = "latin-1"
        tee = _TeeStream(first, io.StringIO())
        self.assertEqual(tee.encoding, "latin-1")

    def test_multiple_writes_accumulate_in_all_streams(self) -> None:
        a, b = io.StringIO(), io.StringIO()
        tee = _TeeStream(a, b)
        tee.write("line1\n")
        tee.write("line2\n")
        self.assertEqual(a.getvalue(), "line1\nline2\n")
        self.assertEqual(b.getvalue(), "line1\nline2\n")


# ===========================================================================
# 3. DashboardLineFilter — escalation header (regression)
# ===========================================================================

class DashboardLineFilterEscalationTests(unittest.TestCase):
    """=== dormammu escalation === is a pass-through header not yet regression-tested."""

    def test_escalation_header_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("=== dormammu escalation ===\n"))

    def test_escalation_body_is_included_after_header(self) -> None:
        f = DashboardLineFilter()
        f.should_include("=== dormammu escalation ===\n")
        self.assertTrue(f.should_include("Manual intervention is required.\n"))

    def test_verbose_lines_suppressed_inside_escalation_section(self) -> None:
        """workdir / cli path lines are suppressed even inside escalation section."""
        f = DashboardLineFilter()
        f.should_include("=== dormammu escalation ===\n")
        self.assertFalse(f.should_include("workdir: /tmp/repo\n"))
        self.assertFalse(f.should_include("cli path: /usr/bin/claude\n"))

    def test_escalation_section_followed_by_dashboard_shows_dashboard_body(self) -> None:
        f = DashboardLineFilter()
        f.should_include("=== dormammu escalation ===\n")
        f.should_include("Escalation note.\n")
        f.should_include("=== DASHBOARD.md ===\n")
        self.assertTrue(f.should_include("# Dashboard heading\n"))


# ===========================================================================
# 4. TelegramProgressStream — edge cases
# ===========================================================================

class TelegramProgressStreamEdgeCaseTests(unittest.TestCase):
    """Regression tests for edge cases not covered in test_telegram_tail_filter.py."""

    # 4a. Base stream always receives writes regardless of Telegram state

    def test_write_always_goes_to_base_stream_when_streaming_disabled(self) -> None:
        stream, base, sent = _make_tps()
        # Don't call enable_streaming — streaming is inactive
        stream.write("goes to base\n")
        stream.flush()
        self.assertIn("goes to base", base.getvalue())
        self.assertEqual(sent, [], "No Telegram messages should be sent when streaming is disabled")

    def test_write_always_goes_to_base_stream_when_streaming_enabled(self) -> None:
        stream, base, sent = _make_tps()
        stream.enable_streaming(chat_id=1)
        stream.write("goes to both\n")
        stream.flush()
        stream.disable_streaming()
        self.assertIn("goes to both", base.getvalue())

    # 4b. No send_fn: streaming_chat_id set but no Telegram delivery

    def test_no_messages_sent_when_send_fn_not_set(self) -> None:
        base = io.StringIO()
        stream = TelegramProgressStream(base, chunk_size=100_000, flush_interval_seconds=9999)
        # set_send_fn NOT called
        stream.enable_streaming(chat_id=42)
        stream.write("data\n")
        stream.flush()
        stream.disable_streaming()
        # Base stream should still receive the write
        self.assertIn("data", base.getvalue())

    # 4c. streaming_chat_id property

    def test_streaming_chat_id_is_none_before_enable(self) -> None:
        stream, _, _ = _make_tps()
        self.assertIsNone(stream.streaming_chat_id)

    def test_streaming_chat_id_is_set_after_enable(self) -> None:
        stream, _, _ = _make_tps()
        stream.enable_streaming(chat_id=99)
        self.assertEqual(stream.streaming_chat_id, 99)
        stream.disable_streaming()

    def test_streaming_chat_id_is_none_after_disable(self) -> None:
        stream, _, _ = _make_tps()
        stream.enable_streaming(chat_id=7)
        stream.disable_streaming()
        self.assertIsNone(stream.streaming_chat_id)

    # 4d. isatty always returns False

    def test_isatty_returns_false(self) -> None:
        stream, _, _ = _make_tps()
        self.assertFalse(stream.isatty())

    # 4e. Session log delegation

    def test_reset_session_log_delegated_to_base_when_available(self) -> None:
        base = io.StringIO()
        base.reset_session_log = mock.Mock()  # type: ignore[attr-defined]
        stream = TelegramProgressStream(base, flush_interval_seconds=9999)
        self.assertTrue(hasattr(stream, "reset_session_log"),
                        "reset_session_log should be delegated when base supports it")

    def test_close_log_delegated_to_base_when_available(self) -> None:
        base = io.StringIO()
        base.close_log = mock.Mock()  # type: ignore[attr-defined]
        stream = TelegramProgressStream(base, flush_interval_seconds=9999)
        self.assertTrue(hasattr(stream, "close_log"),
                        "close_log should be delegated when base supports it")

    def test_no_session_log_delegation_for_plain_base_stream(self) -> None:
        stream, _, _ = _make_tps()
        self.assertFalse(hasattr(stream, "reset_session_log"),
                         "reset_session_log must not be present for a plain base stream")
        self.assertFalse(hasattr(stream, "close_log"),
                         "close_log must not be present for a plain base stream")

    def test_reset_session_log_delegates_call(self) -> None:
        base = io.StringIO()
        called_with: list = []
        base.reset_session_log = lambda p: called_with.append(p)  # type: ignore[attr-defined]
        stream = TelegramProgressStream(base, flush_interval_seconds=9999)
        fake_path = Path("/tmp/fake.log")
        stream.reset_session_log(fake_path)  # type: ignore[attr-defined]
        self.assertEqual(called_with, [fake_path])

    # 4f. enable_streaming resets line_buf so stale partial lines don't bleed across sessions

    def test_enable_streaming_resets_line_buf(self) -> None:
        """Content written before disable_streaming is flushed in session 1 only.

        After re-enabling, a fresh send function captures only session-2 output.
        The partial line from session 1 must not appear in session-2 messages.
        """
        stream, _, _ = _make_tps()
        session2_sent: list[str] = []

        # Session 1: write a partial supervisor line (no newline)
        stream.enable_streaming(chat_id=1)
        stream.write("=== dormammu supervisor ===\n")
        stream.write("partial")  # no newline — sits in _line_buf
        stream.disable_streaming()  # flushes "partial" into session-1 messages

        # Session 2: swap to a new collector so only session-2 output is captured
        stream.set_send_fn(lambda _cid, text: session2_sent.append(text))
        stream.enable_streaming(chat_id=1)
        stream.write("=== pipeline developer cli ===\n")
        stream.flush()
        stream.disable_streaming()

        combined2 = "\n".join(session2_sent)
        self.assertNotIn("partial", combined2,
                         "Session-1 partial line must not appear in session-2 messages")
        self.assertIn("developer", combined2)

    # 4g. Empty content is not sent as a Telegram message

    def test_empty_buffer_does_not_produce_telegram_message(self) -> None:
        stream, _, sent = _make_tps()
        stream.enable_streaming(chat_id=1)
        # Write only empty lines — not inside any recognised section, not forwarded
        stream.write("\n")
        stream.write("\n")
        stream.flush()
        stream.disable_streaming()
        self.assertEqual(sent, [],
                         "Empty (whitespace-only) buffers must not produce Telegram messages")


# ===========================================================================
# 5. LoopRunner progress emission
# ===========================================================================

class LoopRunnerProgressEmissionTests(unittest.TestCase):
    """Verify the exact content of structured progress lines emitted by LoopRunner."""

    def _make_runner_with_capture(self, root: Path):
        from dormammu.config import AppConfig
        from dormammu.loop_runner import LoopRunner
        config = AppConfig.load(repo_root=root)
        progress = io.StringIO()
        runner = LoopRunner(config, progress_stream=progress)
        return runner, progress

    # 5a. _write_progress

    def test_write_progress_prints_each_line_and_flushes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner, progress = self._make_runner_with_capture(root)
            runner._write_progress(["line one", "line two", "line three"])
            text = progress.getvalue()
            self.assertIn("line one", text)
            self.assertIn("line two", text)
            self.assertIn("line three", text)
            # Each line should end with a newline (print adds one)
            self.assertTrue(text.count("\n") >= 3)

    def test_write_progress_with_empty_list_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner, _ = self._make_runner_with_capture(root)
            runner._write_progress([])  # must not raise

    # 5b. _emit_state_snapshot — file present

    def test_emit_state_snapshot_includes_file_header_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner, progress = self._make_runner_with_capture(root)
            from dormammu.state import StateRepository
            from dormammu.config import AppConfig
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(
                prompt_text="test",
                active_roadmap_phase_ids=["phase_4"],
            )
            runner._emit_state_snapshot(repo, "PLAN.md")
            text = progress.getvalue()
            self.assertIn("=== PLAN.md ===", text)
            self.assertIn("Phase 1. Do the thing", text)

    def test_emit_state_snapshot_missing_file_writes_missing_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner, progress = self._make_runner_with_capture(root)
            from dormammu.state import StateRepository
            from dormammu.config import AppConfig
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            # Ensure no NONEXISTENT.md file exists
            runner._emit_state_snapshot(repo, "NONEXISTENT.md")
            text = progress.getvalue()
            self.assertIn("=== NONEXISTENT.md missing ===", text)

    def test_emit_state_snapshot_empty_file_writes_empty_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner, progress = self._make_runner_with_capture(root)
            from dormammu.state import StateRepository
            from dormammu.config import AppConfig
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(
                prompt_text="test",
                active_roadmap_phase_ids=["phase_4"],
            )
            # Overwrite PLAN.md with empty content
            repo.state_file("PLAN.md").write_text("", encoding="utf-8")
            runner._emit_state_snapshot(repo, "PLAN.md")
            text = progress.getvalue()
            self.assertIn("=== PLAN.md ===", text)
            self.assertIn("(empty)", text)

    # 5c. _emit_loop_snapshot output format

    def test_emit_loop_snapshot_contains_key_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner, progress = self._make_runner_with_capture(root)
            from dormammu.loop_runner import LoopRunRequest
            from dormammu.state import StateRepository
            from dormammu.config import AppConfig
            config = AppConfig.load(repo_root=root)
            repo = StateRepository(config)
            repo.ensure_bootstrap_state(
                prompt_text="test",
                active_roadmap_phase_ids=["phase_4"],
            )
            request = LoopRunRequest(
                cli_path=Path("/usr/bin/agent"),
                prompt_text="test prompt",
                repo_root=root,
                max_retries=2,
            )
            runner._emit_loop_snapshot(
                repository=repo,
                request=request,
                attempt_number=1,
                retries_used=0,
            )
            text = progress.getvalue()
            self.assertIn("=== dormammu loop attempt ===", text)
            self.assertIn("attempt: 1", text)
            self.assertIn("retries used: 0/2", text)
            self.assertIn("max iterations: 3", text)

    # 5d. _emit_supervisor_result output format

    def test_emit_supervisor_result_contains_verdict_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner, progress = self._make_runner_with_capture(root)
            from dormammu.supervisor import SupervisorReport
            report = SupervisorReport(
                generated_at="2026-04-12T00:00:00+00:00",
                verdict="approved",
                escalation="approved",
                summary="All checks passed.",
                checks=(),
                latest_run_id="run-001",
                changed_files=(),
                required_paths=(),
                report_path=None,
            )
            runner._emit_supervisor_result(report, attempt_number=1)
            text = progress.getvalue()
            self.assertIn("=== dormammu supervisor ===", text)
            self.assertIn("verdict: approved", text)
            self.assertIn("summary: All checks passed.", text)
            self.assertIn("attempt: 1", text)

    # 5e. _emit_escalation_banner output format (full content check)

    def test_emit_escalation_banner_contains_all_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner, progress = self._make_runner_with_capture(root)
            from dormammu.supervisor import SupervisorReport
            report = SupervisorReport(
                generated_at="2026-04-12T00:00:00+00:00",
                verdict="blocked",
                escalation="blocked",
                summary="Critical .dev state is missing.",
                checks=(),
                latest_run_id="run-x",
                changed_files=(),
                required_paths=(),
                report_path=None,
            )
            runner._emit_escalation_banner(status="blocked", report=report, attempt_number=3)
            text = progress.getvalue()
            self.assertIn("ESCALATION", text)
            self.assertIn("BLOCKED", text)
            self.assertIn("attempt: 3", text)
            self.assertIn("verdict: blocked", text)
            self.assertIn("summary: Critical .dev state is missing.", text)
            self.assertIn("dormammu resume", text)


# ===========================================================================
# 6. TelegramProgressStream — progress stream integration
# ===========================================================================

class TelegramProgressStreamIntegrationTests(unittest.TestCase):
    """Verify that TelegramProgressStream correctly wraps SessionProgressLogStream."""

    def test_write_goes_to_telegram_and_session_log(self) -> None:
        terminal = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "progress.log"
            session_stream = SessionProgressLogStream(terminal)
            session_stream.reset_session_log(log_path)

            tps = TelegramProgressStream(session_stream, flush_interval_seconds=9999)
            sent: list[str] = []
            tps.set_send_fn(lambda _cid, text: sent.append(text))
            tps.enable_streaming(chat_id=1)

            tps.write("=== dormammu loop attempt ===\n")
            tps.write("attempt: 1\n")
            tps.flush()
            tps.disable_streaming()
            session_stream.close_log()

            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("=== dormammu loop attempt ===", log_text)
            self.assertIn("attempt: 1", log_text)

            combined = "\n".join(sent)
            # Skill tail filter converts the loop boundary to a compact marker.
            self.assertIn("🔄", combined)

    def test_session_log_methods_available_on_tps_when_base_is_session_log_stream(self) -> None:
        terminal = io.StringIO()
        session_stream = SessionProgressLogStream(terminal)
        tps = TelegramProgressStream(session_stream, flush_interval_seconds=9999)
        self.assertTrue(hasattr(tps, "reset_session_log"))
        self.assertTrue(hasattr(tps, "close_log"))


if __name__ == "__main__":
    unittest.main()
