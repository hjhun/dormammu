"""Regression tests for /tail prompt-only filtering in TelegramProgressStream.

Scenarios covered:
  1. PromptLineFilter unit tests — header / dump / metadata / agent output
  2. TelegramProgressStream prompt-only mode — only filtered lines reach buffer
  3. TelegramProgressStream full mode — all lines reach buffer (no regression)
  4. disable_streaming resets filter state
  5. Re-enabling in a different mode switches filter correctly
  6. Partial-line writes are reassembled before filtering
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

from dormammu.telegram.stream import PromptLineFilter, TelegramProgressStream


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
# 1. PromptLineFilter unit tests
# ---------------------------------------------------------------------------

class PromptLineFilterTests(unittest.TestCase):
    """Unit tests for the stateful line filter."""

    def test_dormammu_loop_header_is_included(self) -> None:
        f = PromptLineFilter()
        self.assertTrue(f.should_include("=== dormammu loop attempt ===\n"))

    def test_dormammu_command_header_is_included(self) -> None:
        f = PromptLineFilter()
        self.assertTrue(f.should_include("=== dormammu command ===\n"))

    def test_dormammu_supervisor_header_is_included(self) -> None:
        f = PromptLineFilter()
        self.assertTrue(f.should_include("=== dormammu supervisor ===\n"))

    def test_dormammu_promise_header_is_included(self) -> None:
        f = PromptLineFilter()
        self.assertTrue(f.should_include("=== dormammu promise ===\n"))

    def test_dashboard_header_is_excluded(self) -> None:
        f = PromptLineFilter()
        self.assertFalse(f.should_include("=== DASHBOARD.md ===\n"))

    def test_plan_header_is_excluded(self) -> None:
        f = PromptLineFilter()
        self.assertFalse(f.should_include("=== PLAN.md ===\n"))

    def test_dashboard_body_is_suppressed(self) -> None:
        f = PromptLineFilter()
        f.should_include("=== DASHBOARD.md ===\n")  # enter dump
        self.assertFalse(f.should_include("# DASHBOARD\n"))
        self.assertFalse(f.should_include("- Goal: Bootstrap test goal\n"))

    def test_plan_body_is_suppressed(self) -> None:
        f = PromptLineFilter()
        f.should_include("=== PLAN.md ===\n")  # enter dump
        self.assertFalse(f.should_include("# PLAN\n"))
        self.assertFalse(f.should_include("- [ ] Phase 1. Something\n"))

    def test_supervisor_header_after_dashboard_resets_dump(self) -> None:
        f = PromptLineFilter()
        f.should_include("=== DASHBOARD.md ===\n")
        f.should_include("# DASHBOARD\n")  # in dump
        # Next framework header resets dump state
        self.assertTrue(f.should_include("=== dormammu supervisor ===\n"))
        self.assertTrue(f.should_include("verdict: approved\n"))

    def test_attempt_metadata_is_included(self) -> None:
        f = PromptLineFilter()
        self.assertTrue(f.should_include("attempt: 1\n"))

    def test_verdict_metadata_is_included(self) -> None:
        f = PromptLineFilter()
        self.assertTrue(f.should_include("verdict: approved\n"))

    def test_summary_metadata_is_included(self) -> None:
        f = PromptLineFilter()
        self.assertTrue(f.should_include("summary: All checks passed.\n"))

    def test_run_id_metadata_is_included(self) -> None:
        f = PromptLineFilter()
        self.assertTrue(f.should_include("run id: 20260412-010101-agent-run\n"))

    def test_agent_output_is_included(self) -> None:
        f = PromptLineFilter()
        # Typical agent stdout lines
        self.assertTrue(f.should_include("Reading the PLAN.md file...\n"))
        self.assertTrue(f.should_include("Created done.txt\n"))
        self.assertTrue(f.should_include("<promise>COMPLETE</promise>\n"))

    def test_sleep_banner_is_excluded(self) -> None:
        f = PromptLineFilter()
        self.assertFalse(f.should_include("Taking a short break for 1 seconds before the next agent CLI call.\n"))

    def test_empty_line_is_excluded(self) -> None:
        f = PromptLineFilter()
        self.assertFalse(f.should_include("\n"))

    def test_sequential_dump_sections_both_suppressed(self) -> None:
        """DASHBOARD.md immediately followed by PLAN.md — both bodies suppressed."""
        f = PromptLineFilter()
        f.should_include("=== DASHBOARD.md ===\n")
        self.assertFalse(f.should_include("- Goal: test\n"))
        # PLAN.md header is itself a dump header → stays suppressed
        f.should_include("=== PLAN.md ===\n")
        self.assertFalse(f.should_include("# PLAN\n"))
        # Next non-dump header exits suppression
        self.assertTrue(f.should_include("=== dormammu command ===\n"))
        self.assertTrue(f.should_include("run id: abc\n"))


# ---------------------------------------------------------------------------
# 2. TelegramProgressStream prompt-only mode
# ---------------------------------------------------------------------------

class PromptOnlyStreamTests(unittest.TestCase):
    """Integration tests for prompt_only=True streaming."""

    def _write_typical_loop_output(self, stream: TelegramProgressStream) -> None:
        """Write the typical sequence produced by LoopRunner for one iteration."""
        lines = [
            "=== dormammu loop attempt ===\n",
            "attempt: 1\n",
            "retries used: 0/0\n",
            "max iterations: 2\n",
            "target project: /tmp/repo\n",
            "session: dormammu-20260412\n",
            "cli: /usr/bin/claude\n",
            "workdir: /tmp/repo\n",
            "=== DASHBOARD.md ===\n",
            "# DASHBOARD\n",
            "\n",
            "## Actual Progress\n",
            "\n",
            "- Goal: Implement feature X\n",
            "- Current workflow phase: develop\n",
            "\n",
            "=== PLAN.md ===\n",
            "# PLAN\n",
            "\n",
            "- [ ] Phase 1. Implement feature X\n",
            "\n",
            "=== dormammu command ===\n",
            "run id: 20260412-abc\n",
            "cli path: /usr/bin/claude\n",
            "workdir: /tmp/repo\n",
            "prompt mode: file\n",
            "command: /usr/bin/claude --prompt-file /tmp/p.txt\n",
            "stdout log: /tmp/out.log\n",
            "stderr log: /tmp/err.log\n",
            # Agent output
            "Analysing the codebase...\n",
            "Creating done.txt\n",
            "<promise>COMPLETE</promise>\n",
            "=== dormammu promise ===\n",
            "attempt: 1\n",
            "Agent emitted <promise>COMPLETE</promise> — treating as self-declared completion.\n",
        ]
        for line in lines:
            stream.write(line)
        stream.flush()

    def test_prompt_only_mode_suppresses_dashboard_and_plan_content(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1, prompt_only=True)
        self._write_typical_loop_output(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertNotIn("## Actual Progress", combined,
                         "DASHBOARD.md body must be suppressed in prompt-only mode")
        self.assertNotIn("- Goal: Implement feature X", combined,
                         "DASHBOARD.md body must be suppressed in prompt-only mode")
        self.assertNotIn("## Prompt-Derived", combined,
                         "PLAN.md body must be suppressed in prompt-only mode")
        self.assertNotIn("Phase 1. Implement feature X", combined,
                         "PLAN.md body must be suppressed in prompt-only mode")

    def test_prompt_only_mode_includes_attempt_info(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1, prompt_only=True)
        self._write_typical_loop_output(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("attempt: 1", combined)
        self.assertIn("session: dormammu-20260412", combined)

    def test_prompt_only_mode_includes_agent_output(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1, prompt_only=True)
        self._write_typical_loop_output(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("Analysing the codebase", combined)
        self.assertIn("Creating done.txt", combined)
        self.assertIn("<promise>COMPLETE</promise>", combined)

    def test_prompt_only_mode_includes_promise_section(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1, prompt_only=True)
        self._write_typical_loop_output(stream)
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("Agent emitted", combined)


# ---------------------------------------------------------------------------
# 3. Full mode — no regression
# ---------------------------------------------------------------------------

class FullModeStreamTests(unittest.TestCase):
    """Full streaming mode must forward everything unchanged."""

    def test_full_mode_includes_dashboard_content(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)  # full mode (default)
        stream.write("=== DASHBOARD.md ===\n")
        stream.write("## Actual Progress\n")
        stream.write("- Goal: Some goal\n")
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("## Actual Progress", combined)
        self.assertIn("- Goal: Some goal", combined)

    def test_full_mode_includes_plan_content(self) -> None:
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)
        stream.write("=== PLAN.md ===\n")
        stream.write("- [ ] Phase 1. Do the work\n")
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("Phase 1. Do the work", combined)


# ---------------------------------------------------------------------------
# 4. disable_streaming resets filter state
# ---------------------------------------------------------------------------

class StreamStateResetTests(unittest.TestCase):

    def test_disable_streaming_resets_filter_so_re_enable_full_works(self) -> None:
        """After disabling and re-enabling in full mode, no filter is active."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1, prompt_only=True)
        stream.disable_streaming()
        stream.enable_streaming(chat_id=1)  # full mode

        stream.write("=== DASHBOARD.md ===\n")
        stream.write("- Goal: Check filter reset\n")
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertIn("- Goal: Check filter reset", combined,
                      "Full mode must include dashboard content after re-enable")

    def test_disable_streaming_resets_filter_so_re_enable_prompt_works(self) -> None:
        """After disabling and re-enabling in prompt mode, filter resets its state."""
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1)  # full mode first
        stream.disable_streaming()
        stream.enable_streaming(chat_id=1, prompt_only=True)

        stream.write("=== DASHBOARD.md ===\n")
        stream.write("- Goal: Check filter reset\n")
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertNotIn("- Goal: Check filter reset", combined,
                         "Prompt mode must suppress dashboard content after re-enable")


# ---------------------------------------------------------------------------
# 5. Partial-line write reassembly
# ---------------------------------------------------------------------------

class PartialLineWriteTests(unittest.TestCase):
    """Lines split across multiple write() calls must be reassembled for filtering."""

    def test_partial_line_is_filtered_correctly(self) -> None:
        """A line split into two write() calls is treated as one line by the filter.

        The realistic sequence is:
          DASHBOARD.md dump (suppressed) → dormammu command header (resets dump) →
          agent output written in partial chunks (must be included).
        """
        stream, sent = _make_stream()
        stream.enable_streaming(chat_id=1, prompt_only=True)

        # DASHBOARD.md dump — body suppressed, split across writes
        stream.write("=== DASHBOARD.md ===\n")
        stream.write("- Goal: ")
        stream.write("partial test\n")

        # Framework header resets the dump state
        stream.write("=== dormammu command ===\n")

        # Agent output written as split writes — must be reassembled and included
        stream.write("Working on ")
        stream.write("the feature\n")
        stream.flush()
        stream.disable_streaming()

        combined = "\n".join(sent)
        self.assertNotIn("partial test", combined,
                         "Split DASHBOARD.md body line must be suppressed")
        self.assertIn("Working on the feature", combined,
                      "Split agent output line must be included after dump section exits")


if __name__ == "__main__":
    unittest.main()
