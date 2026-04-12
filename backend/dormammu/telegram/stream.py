from __future__ import annotations

import threading
from typing import Callable, TextIO


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
        with self._lock:
            self._flush_locked()
        self._schedule_flush_timer()

    # ------------------------------------------------------------------
    # Streaming control
    # ------------------------------------------------------------------

    def set_send_fn(self, send_fn: Callable[[int, str], None]) -> None:
        """Set the Telegram send function (called from bot thread after loop starts)."""
        with self._lock:
            self._send_fn = send_fn

    def enable_streaming(self, chat_id: int) -> None:
        """Start forwarding writes to the given Telegram chat."""
        with self._lock:
            self._streaming_chat_id = chat_id

    def disable_streaming(self) -> None:
        """Flush buffer and stop forwarding to Telegram."""
        with self._lock:
            self._flush_locked()
            self._streaming_chat_id = None
            self._buffer.clear()
            self._buffer_size = 0

    def close(self) -> None:
        """Stop the flush timer and release resources."""
        self._closed = True
        if self._flush_timer is not None:
            self._flush_timer.cancel()
            self._flush_timer = None

    @property
    def streaming_chat_id(self) -> int | None:
        with self._lock:
            return self._streaming_chat_id

    # ------------------------------------------------------------------
    # TextIO protocol
    # ------------------------------------------------------------------

    def write(self, data: str) -> int:
        self._base.write(data)
        with self._lock:
            if self._streaming_chat_id is not None and self._send_fn is not None:
                self._buffer.append(data)
                self._buffer_size += len(data)
                if self._buffer_size >= self._chunk_size:
                    self._flush_locked()
        return len(data)

    def flush(self) -> None:
        self._base.flush()
        with self._lock:
            self._flush_locked()

    def isatty(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush_locked(self) -> None:
        if not self._buffer or self._streaming_chat_id is None or self._send_fn is None:
            return
        text = "".join(self._buffer)
        self._buffer.clear()
        self._buffer_size = 0
        chat_id = self._streaming_chat_id
        send_fn = self._send_fn
        for i in range(0, len(text), self._chunk_size):
            chunk = text[i : i + self._chunk_size].strip()
            if chunk:
                try:
                    send_fn(chat_id, chunk)
                except Exception:
                    pass
