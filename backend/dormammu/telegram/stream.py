from __future__ import annotations

import re
import threading
from collections import deque
from typing import Callable, TextIO

# DASHBOARD.md / PLAN.md section headers shown in dashboard mode.
_DASHBOARD_SECTION_HEADERS = frozenset(["=== DASHBOARD.md ===", "=== PLAN.md ==="])

# Loop boundary marker — signals the start of a new dormammu loop attempt.
_LOOP_BOUNDARY = "=== dormammu loop attempt ==="

# Pipeline role section header pattern: "=== pipeline <role> <kind> ==="
_PIPELINE_SECTION_RE = re.compile(r"^=== pipeline (\w+) (cli|stdout|stderr) ===$")

# Supervisor / escalation headers used by SkillTailFilter.
_SUPERVISOR_HEADER = "=== dormammu supervisor ==="
_ESCALATION_HEADER = "=== dormammu escalation ==="

# Framework headers that are always shown in dashboard mode.
_DASHBOARD_PASS_HEADERS = frozenset([
    "=== dormammu loop attempt ===",
    "=== dormammu command ===",
    "=== dormammu supervisor ===",
    "=== dormammu promise ===",
    "=== dormammu escalation ===",
])

# Verbose framework metadata lines suppressed inside known framework sections.
# Everything else (including agent output) is forwarded.
_FRAMEWORK_SUPPRESS_PREFIXES = (
    "workdir:",
    "cli path:",
    "cli:",
    "max iterations:",
    "target project:",
    "prompt mode:",
    "command:",
    "stdout log:",
    "stderr log:",
)


class DashboardLineFilter:
    """Stateful line-level filter for TelegramProgressStream dashboard mode.

    Shows DASHBOARD.md / PLAN.md section bodies in full under each loop attempt
    header, plus agent output and key metadata. Suppresses verbose framework
    internals (workdir, cli path, max iterations, stdout/stderr log paths),
    "Taking a short break" banners, empty lines, and unknown section bodies.

    Call ``should_include(line)`` with each complete line (including the
    trailing newline) to decide whether it should be forwarded to Telegram.
    """

    def __init__(self) -> None:
        self._in_dashboard_section = False   # DASHBOARD.md or PLAN.md — show all
        self._in_framework_section = False   # known framework section — show most
        self._in_unknown_section = False     # unknown section — suppress all

    def should_include(self, line: str) -> bool:
        stripped = line.rstrip("\n").strip()

        # === section header
        if stripped.startswith("===") and stripped.endswith("==="):
            if stripped in _DASHBOARD_SECTION_HEADERS:
                self._in_dashboard_section = True
                self._in_framework_section = False
                self._in_unknown_section = False
                return True  # include the header for clarity
            self._in_dashboard_section = False
            if stripped in _DASHBOARD_PASS_HEADERS:
                self._in_framework_section = True
                self._in_unknown_section = False
                return True
            # Unknown section — suppress header and body
            self._in_framework_section = False
            self._in_unknown_section = True
            return False

        # Inside an unknown section — suppress everything
        if self._in_unknown_section:
            return False

        # Inside DASHBOARD.md / PLAN.md — show everything
        if self._in_dashboard_section:
            return True

        # Inside a known framework section — show agent output and key metadata,
        # suppress verbose internals (paths, iteration counts, etc.)
        if self._in_framework_section:
            if not stripped:
                return False
            if stripped.startswith("Taking a short break"):
                return False
            lower = stripped.lower()
            for prefix in _FRAMEWORK_SUPPRESS_PREFIXES:
                if lower.startswith(prefix.lower()):
                    return False
            return True

        # Outside any section: agent stdout lines (non-empty, non-banner)
        if stripped and not stripped.startswith("Taking a short break"):
            return True

        return False


class _AgentCliOutputFilter:
    """Accept only lines emitted by the CLI agent subprocess itself.

    Tracks the ``=== dormammu command ===`` section (where agent subprocess
    stdout/stderr appears) and passes through non-verbose lines within it.
    All dormammu framework headers, metadata, dashboard/plan/supervisor/
    promise content, and blank lines are rejected.
    """

    def __init__(self) -> None:
        self._in_command_section = False

    def should_include(self, line: str) -> bool:
        stripped = line.rstrip("\n").strip()

        # Section boundary — update state, never include the header itself
        if stripped.startswith("===") and stripped.endswith("==="):
            self._in_command_section = (stripped == "=== dormammu command ===")
            return False

        if not self._in_command_section:
            return False

        if not stripped:
            return False
        if stripped.startswith("Taking a short break"):
            return False
        lower = stripped.lower()
        for prefix in _FRAMEWORK_SUPPRESS_PREFIXES:
            if lower.startswith(prefix.lower()):
                return False
        return True


class AgentDigestFilter:
    """Accumulates CLI agent subprocess output lines into a ring buffer.

    Only lines produced by the CLI agent itself (inside the
    ``=== dormammu command ===`` section, excluding verbose metadata) are
    buffered.  All dormammu framework headers, metadata, and
    supervisor/promise/escalation content are discarded.

    When a loop-boundary line (``=== dormammu loop attempt ===``) is received
    the buffer is snapshotted and returned so the caller can emit it as a
    single Telegram message, then the buffer is cleared for the next loop.
    Call ``collect_final()`` at the end to flush any remaining content.
    """

    def __init__(self, maxlines: int = 10) -> None:
        self._buf: deque[str] = deque(maxlen=maxlines)
        self._inner = _AgentCliOutputFilter()

    def add_line(self, line: str) -> str | None:
        """Process one complete line.

        Returns a snapshot string when a loop boundary is detected (covering
        the *previous* loop's buffered output), or ``None`` otherwise.
        """
        stripped = line.rstrip("\n").strip()

        if stripped == _LOOP_BOUNDARY:
            return self._snapshot_and_reset()

        if self._inner.should_include(line):
            self._buf.append(stripped)
        return None

    def collect_final(self) -> str | None:
        """Return remaining buffered lines as a snapshot, or ``None`` if empty."""
        return self._snapshot_and_reset()

    def _snapshot_and_reset(self) -> str | None:
        if not self._buf:
            return None
        text = "\n".join(self._buf)
        self._buf.clear()
        self._inner = _AgentCliOutputFilter()  # reset section state for next loop
        return text


class SkillTailFilter:
    """Smart filter for tail-on mode.

    Monitors the stream for pipeline role banners and loop-runner sections,
    then emits compact Telegram-friendly summaries:

    * ``▶️ *<role>*`` when a pipeline role starts (cli section).
    * ``📤 *<role>* output (last N lines):`` with a code block after the
      role's stdout/stderr section ends.
    * ``🧑‍⚖️ *Supervisor*:`` with a verdict snippet after supervisor sections.
    * ``🔄 Loop attempt`` on ``=== dormammu loop attempt ===`` boundaries.

    For plain loop-runner runs (no pipeline) the filter falls back to the
    same per-loop digest behaviour as :class:`AgentDigestFilter`.

    Call :meth:`add_line` for each complete line (with trailing ``\\n``).
    It returns either a formatted string to send to Telegram, or ``None``.
    Call :meth:`collect_final` when the session ends to flush any remaining
    buffered content.
    """

    _TAIL_MAXLINES: int = 8  # ring-buffer size for stdout/stderr/supervisor/digest

    def __init__(self) -> None:
        self._buf: deque[str] = deque(maxlen=self._TAIL_MAXLINES)
        self._current_role: str | None = None
        self._current_kind: str | None = None  # "cli" | "stdout" | "stderr" | "supervisor" | "digest"
        self._digest_inner = _AgentCliOutputFilter()  # for plain loop-runner output

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_line(self, line: str) -> str | None:
        """Process one complete line; return a Telegram message or None."""
        stripped = line.rstrip("\n").strip()

        # Pipeline section header
        m = _PIPELINE_SECTION_RE.match(stripped)
        if m:
            role, kind = m.group(1), m.group(2)
            msg = self._flush_section()
            self._current_role = role
            self._current_kind = kind
            self._buf.clear()
            if kind == "cli":
                # Announce the skill start; emit any previous flush first.
                start = f"▶️ *{role}*"
                return _join_msgs(msg, start)
            return msg  # stdout/stderr section starts silently; emit previous flush

        # Framework section headers
        if stripped.startswith("===") and stripped.endswith("==="):
            msg = self._flush_section()
            self._current_role = None
            self._current_kind = None
            self._buf.clear()

            if stripped == _SUPERVISOR_HEADER or stripped == _ESCALATION_HEADER:
                self._current_kind = "supervisor"
            elif stripped == _LOOP_BOUNDARY:
                # Flush digest buf from plain loop-runner run
                digest_snap = self._flush_digest()
                boundary = "🔄 Loop"
                combined = _join_msgs(msg, digest_snap, boundary)
                return combined if combined.strip() else None
            # Other headers (dormammu command, promise, …) — just flush
            return msg if (msg and msg.strip()) else None

        # Content routing
        if self._current_kind == "cli":
            # Skip cli metadata (command, cwd lines)
            return None

        if self._current_kind in ("stdout", "stderr"):
            if stripped and not _is_verbose(stripped):
                self._buf.append(stripped)
            return None

        if self._current_kind == "supervisor":
            if stripped and not _is_verbose(stripped):
                self._buf.append(stripped)
            return None

        # Plain loop-runner output (inside === dormammu command ===)
        snapshot = self._digest_inner.should_include(line)
        if snapshot:
            self._buf.append(stripped)
        return None

    def collect_final(self) -> str | None:
        """Flush any remaining buffered content at session end."""
        msg = self._flush_section()
        digest = self._flush_digest()
        return _join_msgs(msg, digest) or None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flush_section(self) -> str | None:
        """Emit buffered lines for the current section, then clear state."""
        if not self._buf:
            return None
        lines = list(self._buf)
        self._buf.clear()
        text = "\n".join(lines)
        n = len(lines)

        if self._current_kind in ("stdout", "stderr") and self._current_role:
            kind_label = self._current_kind
            return f"📤 *{self._current_role}* {kind_label} (last {n} lines):\n```\n{text}\n```"
        if self._current_kind == "supervisor":
            return f"🧑‍⚖️ *Supervisor*:\n```\n{text}\n```"
        return None

    def _flush_digest(self) -> str | None:
        """Flush the plain loop-runner digest ring buffer."""
        if not self._buf:
            return None
        lines = list(self._buf)
        self._buf.clear()
        text = "\n".join(lines)
        n = len(lines)
        return f"📡 Agent output (last {n} lines):\n```\n{text}\n```"


def _is_verbose(stripped: str) -> bool:
    lower = stripped.lower()
    for prefix in _FRAMEWORK_SUPPRESS_PREFIXES:
        if lower.startswith(prefix.lower()):
            return True
    return False


def _join_msgs(*parts: str | None) -> str:
    """Join non-empty message parts with a blank line separator."""
    return "\n\n".join(p for p in parts if p and p.strip())


class TelegramProgressStream:
    """TextIO-compatible stream wrapper that optionally forwards output to a Telegram chat.

    Wraps a base stream (e.g. sys.stderr or SessionProgressLogStream) and adds
    buffered Telegram streaming when enabled via enable_streaming().

    A background timer thread flushes the buffer every flush_interval_seconds so
    that small or infrequent writes are still delivered promptly.

    Session log delegation: reset_session_log and close_log are conditionally
    attached at construction time only when the base stream provides them.
    This preserves --debug file-logging behavior without the runner needing to
    know about Telegram.
    """

    encoding: str

    def __init__(
        self,
        base_stream: TextIO,
        *,
        chunk_size: int = 3000,
        flush_interval_seconds: float = 2.0,
    ) -> None:
        self._base = base_stream
        self._chunk_size = chunk_size
        self._flush_interval = flush_interval_seconds
        self._lock = threading.Lock()
        self._streaming_chat_id: int | None = None
        self._send_fn: Callable[[int, str], None] | None = None
        self._buffer: list[str] = []
        self._buffer_size = 0
        self._closed = False
        self.encoding = getattr(base_stream, "encoding", "utf-8")
        self._skill_filter: SkillTailFilter | None = None
        self._line_buf: str = ""  # partial-line accumulator for filter mode

        # Delegate session log methods only when the base supports them so that
        # hasattr(stream, 'reset_session_log') faithfully reflects whether
        # per-session log files are active (i.e. --debug was passed).
        if hasattr(base_stream, "reset_session_log"):
            self.reset_session_log = base_stream.reset_session_log  # type: ignore[attr-defined]
        if hasattr(base_stream, "close_log"):
            self.close_log = base_stream.close_log  # type: ignore[attr-defined]

        self._flush_timer: threading.Timer | None = None
        self._schedule_flush_timer()

    def _schedule_flush_timer(self) -> None:
        """Schedule the next periodic flush tick."""
        if self._closed:
            return
        self._flush_timer = threading.Timer(self._flush_interval, self._timer_flush)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _timer_flush(self) -> None:
        """Periodic flush callback: drain the buffer then reschedule."""
        chunks = self._collect_and_reset()
        self._send_chunks(chunks)
        self._schedule_flush_timer()

    # ------------------------------------------------------------------
    # Streaming control
    # ------------------------------------------------------------------

    def set_send_fn(self, send_fn: Callable[[int, str], None]) -> None:
        """Set the Telegram send function (called from bot thread after loop starts)."""
        with self._lock:
            self._send_fn = send_fn

    def enable_streaming(self, chat_id: int) -> None:
        """Start forwarding writes to the given Telegram chat.

        Uses :class:`SkillTailFilter` to emit compact, skill-aware summaries:
        role banners when each pipeline skill starts, a digest of the last few
        output lines when each skill finishes, and supervisor verdicts.
        For plain loop-runner runs the same digest logic applies per loop.
        """
        with self._lock:
            self._streaming_chat_id = chat_id
            self._skill_filter = SkillTailFilter()
            self._line_buf = ""

    def disable_streaming(self) -> None:
        """Flush buffer and stop forwarding to Telegram."""
        chunks = self._collect_and_reset()
        self._send_chunks(chunks)
        with self._lock:
            self._streaming_chat_id = None
            self._skill_filter = None
            self._line_buf = ""
            self._buffer.clear()
            self._buffer_size = 0

    def close(self) -> None:
        """Flush remaining buffer, stop the flush timer, and release resources."""
        self._closed = True
        if self._flush_timer is not None:
            self._flush_timer.cancel()
            self._flush_timer = None
        chunks = self._collect_and_reset()
        self._send_chunks(chunks)

    @property
    def streaming_chat_id(self) -> int | None:
        with self._lock:
            return self._streaming_chat_id

    # ------------------------------------------------------------------
    # TextIO protocol
    # ------------------------------------------------------------------

    def write(self, data: str) -> int:
        self._base.write(data)
        chunks: list[tuple[int, str]] = []
        with self._lock:
            if self._streaming_chat_id is not None and self._send_fn is not None:
                if self._skill_filter is not None:
                    self._write_skill_locked(data)
                    if self._buffer_size >= self._chunk_size:
                        chunks = self._collect_buffer_locked()
        self._send_chunks(chunks)
        return len(data)

    def _write_skill_locked(self, data: str) -> None:
        """Feed data into SkillTailFilter line-by-line and buffer emitted messages."""
        self._line_buf += data
        while "\n" in self._line_buf:
            line, self._line_buf = self._line_buf.split("\n", 1)
            full_line = line + "\n"
            if self._skill_filter is None:
                return
            msg = self._skill_filter.add_line(full_line)
            if msg:
                payload = msg + "\n"
                self._buffer.append(payload)
                self._buffer_size += len(payload)

    def flush(self) -> None:
        self._base.flush()
        chunks = self._collect_and_reset()
        self._send_chunks(chunks)

    def isatty(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _collect_buffer_locked(self) -> list[tuple[int, str]]:
        """Drain _buffer under the lock and return (chat_id, chunk) pairs to send.

        Does NOT flush _line_buf — call _collect_and_reset() for a full flush.
        """
        if not self._buffer or self._streaming_chat_id is None or self._send_fn is None:
            return []
        text = "".join(self._buffer)
        self._buffer.clear()
        self._buffer_size = 0
        chat_id = self._streaming_chat_id
        result = []
        for i in range(0, len(text), self._chunk_size):
            chunk = text[i : i + self._chunk_size]
            if chunk.strip():
                result.append((chat_id, chunk))
        return result

    def _collect_and_reset(self) -> list[tuple[int, str]]:
        """Flush both _line_buf and _buffer under the lock; return chunks to send.

        _line_buf content (partial line without trailing newline) is emitted as-is
        so that in-flight agent output is not lost on explicit flush() or close().
        For digest mode, any remaining buffered lines are snapshotted and emitted.
        """
        with self._lock:
            if self._streaming_chat_id is None or self._send_fn is None:
                return []
            if self._skill_filter is not None:
                # Flush any partial line then collect remaining buffered content.
                if self._line_buf:
                    msg = self._skill_filter.add_line(self._line_buf + "\n")
                    if msg:
                        payload = msg + "\n"
                        self._buffer.append(payload)
                        self._buffer_size += len(payload)
                    self._line_buf = ""
                final = self._skill_filter.collect_final()
                if final:
                    payload = final + "\n"
                    self._buffer.append(payload)
                    self._buffer_size += len(payload)
            elif self._line_buf:
                # Partial line without active filter — flush as-is.
                self._buffer.append(self._line_buf)
                self._buffer_size += len(self._line_buf)
                self._line_buf = ""
            return self._collect_buffer_locked()

    def _send_chunks(self, chunks: list[tuple[int, str]]) -> None:
        """Send pre-collected (chat_id, chunk) pairs outside the lock."""
        for chat_id, chunk in chunks:
            with self._lock:
                send_fn = self._send_fn
            if send_fn is None:
                break
            try:
                send_fn(chat_id, chunk)
            except Exception:
                pass
