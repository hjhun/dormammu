"""Tests for Telegram tail streaming filters.

Scenarios covered:
  1. DashboardLineFilter unit tests — header / section body / metadata / agent output
  2. AgentDigestFilter unit tests — ring buffer, loop boundary, verbose suppression
  3. SkillTailFilter unit tests — role banners, stdout digest, supervisor verdict
  4. TelegramProgressStream with prompt/stage tail — prompt identity and stage transitions
  5. disable_streaming resets state
  6. Partial-line writes reassembled correctly
  7. Flush / close correctness
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.telegram.stream import (
    AgentDigestFilter,
    DashboardLineFilter,
    SkillTailFilter,
    TelegramProgressStream,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stream() -> tuple[TelegramProgressStream, list[str]]:
    """Return a stream and a list that collects every message sent to Telegram."""
    base = io.StringIO()
    stream = TelegramProgressStream(base, chunk_size=100_000, flush_interval_seconds=9999)
    sent: list[str] = []

    def _send(chat_id: int, text: str) -> None:
        sent.append(text)

    stream.set_send_fn(_send)
    return stream, sent


# ---------------------------------------------------------------------------
# 1. DashboardLineFilter unit tests
# ---------------------------------------------------------------------------

class DashboardLineFilterTests(unittest.TestCase):
    """Unit tests for the stateful line filter."""

    def test_dormammu_loop_header_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("=== dormammu loop attempt ===\n"))

    def test_dormammu_command_header_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("=== dormammu command ===\n"))

    def test_dormammu_supervisor_header_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("=== dormammu supervisor ===\n"))

    def test_dormammu_promise_header_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("=== dormammu promise ===\n"))

    def test_dashboard_header_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("=== DASHBOARD.md ===\n"))

    def test_plan_header_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("=== PLAN.md ===\n"))

    def test_dashboard_body_is_included(self) -> None:
        f = DashboardLineFilter()
        f.should_include("=== DASHBOARD.md ===\n")  # enter section
        self.assertTrue(f.should_include("# DASHBOARD\n"))
        self.assertTrue(f.should_include("- Goal: Bootstrap test goal\n"))

    def test_plan_body_is_included(self) -> None:
        f = DashboardLineFilter()
        f.should_include("=== PLAN.md ===\n")  # enter section
        self.assertTrue(f.should_include("# PLAN\n"))
        self.assertTrue(f.should_include("- [ ] Phase 1. Something\n"))

    def test_supervisor_header_after_dashboard_resets_to_framework_section(self) -> None:
        f = DashboardLineFilter()
        f.should_include("=== DASHBOARD.md ===\n")
        f.should_include("# DASHBOARD\n")  # in dashboard section
        # Next framework header exits dashboard section
        self.assertTrue(f.should_include("=== dormammu supervisor ===\n"))
        self.assertTrue(f.should_include("verdict: approved\n"))

    def test_attempt_metadata_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("attempt: 1\n"))

    def test_verdict_metadata_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("verdict: approved\n"))

    def test_summary_metadata_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("summary: All checks passed.\n"))

    def test_run_id_metadata_is_included(self) -> None:
        f = DashboardLineFilter()
        self.assertTrue(f.should_include("run id: 20260412-010101-agent-run\n"))

    def test_agent_output_is_included(self) -> None:
        f = DashboardLineFilter()
        # Typical agent stdout lines outside any section
        self.assertTrue(f.should_include("Reading the PLAN.md file...\n"))
        self.assertTrue(f.should_include("Created done.txt\n"))
        self.assertTrue(f.should_include("<promise>COMPLETE</promise>\n"))

    def test_sleep_banner_is_excluded(self) -> None:
        f = DashboardLineFilter()
        self.assertFalse(f.should_include("Taking a short break for 1 seconds before the next agent CLI call.\n"))

    def test_empty_line_is_excluded(self) -> None:
        f = DashboardLineFilter()
        self.assertFalse(f.should_include("\n"))

    def test_unknown_section_header_is_excluded(self) -> None:
        f = DashboardLineFilter()
        self.assertFalse(f.should_include("=== some unknown section ===\n"))

    def test_unknown_section_body_is_excluded(self) -> None:
        f = DashboardLineFilter()
        f.should_include("=== some unknown section ===\n")
        self.assertFalse(f.should_include("content inside unknown section\n"))

    def test_verbose_framework_metadata_is_excluded(self) -> None:
        """Lines like 'workdir:', 'cli path:', 'max iterations:' are suppressed."""
        f = DashboardLineFilter()
        f.should_include("=== dormammu command ===\n")
        self.assertFalse(f.should_include("workdir: /tmp/repo\n"))
        self.assertFalse(f.should_include("cli path: /usr/bin/claude\n"))
        self.assertFalse(f.should_include("stdout log: /tmp/out.log\n"))

    def test_sequential_sections_each_included(self) -> None:
        """DASHBOARD.md immediately followed by PLAN.md — both bodies included."""
        f = DashboardLineFilter()
        f.should_include("=== DASHBOARD.md ===\n")
        self.assertTrue(f.should_include("- Goal: test\n"))
        f.should_include("=== PLAN.md ===\n")
        self.assertTrue(f.should_include("# PLAN\n"))
        # Next non-dashboard header exits dashboard section
        self.assertTrue(f.should_include("=== dormammu command ===\n"))
        self.assertTrue(f.should_include("run id: abc\n"))
        self.assertFalse(f.should_include("workdir: /tmp\n"))


# ---------------------------------------------------------------------------
# 2. AgentDigestFilter unit tests
# ---------------------------------------------------------------------------

class AgentDigestFilterTests(unittest.TestCase):
    """Unit tests for the ring-buffer digest filter."""

    def test_snapshot_on_loop_boundary(self) -> None:
        f = AgentDigestFilter(maxlines=10)
        f.add_line("=== dormammu command ===\n")
        f.add_line("line A\n")
        f.add_line("line B\n")
        snap = f.add_line("=== dormammu loop attempt ===\n")
        self.assertIsNotNone(snap)
        assert snap is not None
        self.assertIn("line A", snap)
        self.assertIn("line B", snap)

    def test_verbose_lines_excluded(self) -> None:
        f = AgentDigestFilter(maxlines=10)
        f.add_line("=== dormammu command ===\n")
        f.add_line("workdir: /tmp\n")
        f.add_line("cli path: /usr/bin/claude\n")
        f.add_line("real output\n")
        snap = f.add_line("=== dormammu loop attempt ===\n")
        assert snap is not None
        self.assertNotIn("workdir", snap)
        self.assertIn("real output", snap)

    def test_maxlines_respected(self) -> None:
        f = AgentDigestFilter(maxlines=3)
        f.add_line("=== dormammu command ===\n")
        for i in range(10):
            f.add_line(f"line {i}\n")
        snap = f.add_line("=== dormammu loop attempt ===\n")
        assert snap is not None
        self.assertIn("line 9", snap)
        self.assertIn("line 8", snap)
        self.assertIn("line 7", snap)
        self.assertNotIn("line 0", snap)

    def test_collect_final_returns_remaining(self) -> None:
        f = AgentDigestFilter(maxlines=10)
        f.add_line("=== dormammu command ===\n")
        f.add_line("last line\n")
        snap = f.collect_final()
        self.assertIsNotNone(snap)
        assert snap is not None
        self.assertIn("last line", snap)

    def test_collect_final_none_when_empty(self) -> None:
        f = AgentDigestFilter(maxlines=10)
        self.assertIsNone(f.collect_final())


# ---------------------------------------------------------------------------
# 3. SkillTailFilter unit tests
# ---------------------------------------------------------------------------

class SkillTailFilterTests(unittest.TestCase):
    """Unit tests for the skill-aware tail filter."""

    def test_pipeline_cli_section_emits_role_banner(self) -> None:
        f = SkillTailFilter()
        msg = f.add_line("=== pipeline developer cli ===\n")
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("developer", msg)
        self.assertIn("▶️", msg)

    def test_pipeline_stdout_content_buffered_and_emitted_on_next_section(self) -> None:
        f = SkillTailFilter()
        f.add_line("=== pipeline developer stdout ===\n")
        f.add_line("output line A\n")
        f.add_line("output line B\n")
        # Next section triggers flush of previous stdout buffer
        msg = f.add_line("=== pipeline tester cli ===\n")
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("output line A", msg)
        self.assertIn("output line B", msg)
        self.assertIn("developer", msg)

    def test_pipeline_stdout_verbose_lines_excluded(self) -> None:
        f = SkillTailFilter()
        f.add_line("=== pipeline developer stdout ===\n")
        f.add_line("workdir: /tmp/repo\n")
        f.add_line("cli path: /usr/bin/claude\n")
        f.add_line("real developer output\n")
        msg = f.add_line("=== pipeline tester cli ===\n")
        assert msg is not None
        self.assertNotIn("workdir", msg)
        self.assertIn("real developer output", msg)

    def test_supervisor_section_content_emitted(self) -> None:
        f = SkillTailFilter()
        f.add_line("=== dormammu supervisor ===\n")
        f.add_line("verdict: approved\n")
        f.add_line("summary: All checks passed.\n")
        # Flush via collect_final
        msg = f.collect_final()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("verdict: approved", msg)
        self.assertIn("🧑‍⚖️", msg)

    def test_loop_boundary_emits_loop_marker(self) -> None:
        f = SkillTailFilter()
        msg = f.add_line("=== dormammu loop attempt ===\n")
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("🔄", msg)

    def test_collect_final_flushes_buffered_stdout(self) -> None:
        f = SkillTailFilter()
        f.add_line("=== pipeline committer stdout ===\n")
        f.add_line("Commit created successfully.\n")
        msg = f.collect_final()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("Commit created successfully", msg)
        self.assertIn("committer", msg)

    def test_cli_section_body_not_forwarded(self) -> None:
        """Command / cwd lines inside a cli section must be silently dropped."""
        f = SkillTailFilter()
        f.add_line("=== pipeline planner cli ===\n")
        msg = f.add_line("command: /usr/bin/claude --prompt /tmp/p.txt\n")
        self.assertIsNone(msg)

    def test_empty_stdout_produces_no_message(self) -> None:
        """An empty stdout section must not produce an output message."""
        f = SkillTailFilter()
        f.add_line("=== pipeline planner stdout ===\n")
        msg = f.add_line("=== pipeline tester cli ===\n")
        # msg may contain the tester start banner but must not have an empty stdout block
        if msg:
            self.assertNotIn("planner stdout", msg)


# ---------------------------------------------------------------------------
# 4. TelegramProgressStream with prompt/stage tail
# ---------------------------------------------------------------------------

class SkillTailStreamTests(unittest.TestCase):
    """Integration tests for TelegramProgressStream in prompt/stage mode."""

    def _write_pipeline_run(self, stream: TelegramProgressStream) -> None:
        """Write a minimal pipeline sequence through the stream."""
        lines = [
            "daemon prompt detected: 001-fix-logs.md (sort_key=(0, '001-fix-logs.md'), watcher=polling, result=001-fix-logs_RESULT.md)\n",
            "daemon prompt summary: Fix noisy operator logging\n",
            "=== pipeline developer cli ===\n",
            "command: claude --prompt /tmp/p.txt\n",
            "cwd: /tmp/repo\n",
            "=== pipeline developer stdout ===\n",
            "Analysing the codebase...\n",
            "Created done.txt\n",
            "<promise>COMPLETE</promise>\n",
            "=== pipeline developer stderr ===\n",
            "(empty)\n",
            "=== pipeline tester cli ===\n",
            "command: claude --prompt /tmp/t.txt\n",
            "=== pipeline tester stdout ===\n",
            "All tests passed.\n",
            "=== dormammu supervisor ===\n",
            "verdict: approved\n",
            "summary: Tests passed.\n",
        ]
        for line in lines:
            stream.write(line)
        stream.flush()

    def test_tail_shows_prompt_summary(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)
        self._write_pipeline_run(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("Fix noisy operator logging", combined)

    def test_tail_shows_developer_stage(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)
        self._write_pipeline_run(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("stage: developer", combined)
        self.assertIn("developing-agent", combined)

    def test_tail_shows_tester_stage(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)
        self._write_pipeline_run(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("stage: tester", combined)

    def test_tail_shows_supervisor_stage(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)
        self._write_pipeline_run(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("stage: supervisor verification", combined)

    def test_tail_omits_raw_agent_output_and_verbose_metadata(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)
        self._write_pipeline_run(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertNotIn("cwd:", combined)
        self.assertNotIn("command:", combined)
        self.assertNotIn("Analysing the codebase", combined)
        self.assertNotIn("All tests passed.", combined)


# ---------------------------------------------------------------------------
# 5. disable_streaming resets state
# ---------------------------------------------------------------------------

class StreamStateResetTests(unittest.TestCase):

    def test_disable_streaming_stops_sending(self) -> None:
        """After disabling, writes must not reach Telegram."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)
        stream.disable_streaming()

        # Write pipeline output after disable — must not appear
        stream.write("=== pipeline developer cli ===\n")
        stream.write("should not be sent\n")
        stream.flush()

        combined = "\n".join(sent)
        # Any content written after disable_streaming must not appear in sent
        # (content from before disable may appear if flushed)
        for msg in sent:
            self.assertNotIn("should not be sent", msg)

    def test_reenable_after_disable_works(self) -> None:
        """Re-enabling after disable resumes delivery."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)
        stream.disable_streaming()
        stream.enable_streaming(chat_id=1)

        stream.write("=== pipeline planner cli ===\n")
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("planner", combined)


# ---------------------------------------------------------------------------
# 6. Partial-line write reassembly
# ---------------------------------------------------------------------------

class PartialLineWriteTests(unittest.TestCase):
    """Lines split across multiple write() calls must be reassembled for filtering."""

    def test_partial_role_banner_line_is_processed(self) -> None:
        """A pipeline section header split across writes is handled correctly."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)

        stream.write("=== pipeline developer ")
        stream.write("cli ===\n")
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("developer", combined)

    def test_partial_output_line_is_buffered(self) -> None:
        """Prompt summary split across writes still appears after flush."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)

        stream.write("daemon prompt summary: partial ")
        stream.write("prompt line\n")
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("partial prompt line", combined)


# ---------------------------------------------------------------------------
# 7. Flush / close correctness
# ---------------------------------------------------------------------------

class FlushCorrectnessTests(unittest.TestCase):
    """flush() and close() must not lose buffered or partial-line content."""

    def test_explicit_flush_drains_partial_supervisor_line(self) -> None:
        """A partial prompt-summary line (no \\n) is sent on flush()."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)

        stream.write("daemon prompt summary: partial prompt")  # no \n — sits in _line_buf
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("partial prompt", combined)

    def test_close_flushes_remaining_skill_buffer(self) -> None:
        """close() must send any content still waiting in the line buffer."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)

        stream.write("daemon prompt summary: Last prompt before close\n")
        # Do NOT call flush — rely on close() to do it
        stream.close()

        combined = "\n".join(sent)
        self.assertIn("Last prompt before close", combined)

    def test_close_flushes_partial_line(self) -> None:
        """close() must send a partial line that was never terminated with \\n."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)

        stream.write("daemon prompt summary: Unterminated prompt")  # no \n
        stream.close()

        combined = "\n".join(sent)
        self.assertIn("Unterminated prompt", combined)


if __name__ == "__main__":
    unittest.main()
