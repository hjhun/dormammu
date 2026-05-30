from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import pty
import queue
import select
import signal
import struct
import subprocess
import termios
import threading
import uuid
from typing import Iterator


class TerminalAccessError(ValueError):
    """Raised when a requested terminal cwd is outside the configured roots."""


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_allowed_cwd(cwd: str | Path, allowed_roots: tuple[Path, ...]) -> Path:
    candidate = Path(cwd).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise TerminalAccessError(f"Terminal directory does not exist: {candidate}")
    allowed = tuple(root.expanduser().resolve() for root in allowed_roots)
    if not allowed:
        raise TerminalAccessError("No web.allowed_roots entries are configured.")
    if not any(candidate == root or _is_relative_to(candidate, root) for root in allowed):
        roots = ", ".join(str(root) for root in allowed)
        raise TerminalAccessError(f"Terminal directory is outside allowed roots: {candidate}. Allowed: {roots}")
    return candidate


@dataclass(frozen=True, slots=True)
class TerminalSessionSnapshot:
    id: str
    cwd: Path
    command: tuple[str, ...]
    created_at: str
    pid: int
    running: bool
    exit_code: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "cwd": str(self.cwd),
            "command": list(self.command),
            "created_at": self.created_at,
            "pid": self.pid,
            "running": self.running,
            "exit_code": self.exit_code,
        }


class TerminalSession:
    def __init__(
        self,
        *,
        session_id: str,
        cwd: Path,
        command: tuple[str, ...],
        cols: int,
        rows: int,
    ) -> None:
        self.id = session_id
        self.cwd = cwd
        self.command = command
        self.created_at = datetime.now(timezone.utc).isoformat()
        self._master_fd, slave_fd = pty.openpty()
        self._subscribers: set[queue.Queue[bytes | None]] = set()
        self._subscribers_lock = threading.Lock()
        self._closed = threading.Event()
        self._set_winsize(cols=cols, rows=rows)
        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        self._process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave_fd)
        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"dormammu-web-terminal-{self.id}",
            daemon=True,
        )
        self._reader.start()

    @property
    def running(self) -> bool:
        return self._process.poll() is None

    @property
    def exit_code(self) -> int | None:
        return self._process.poll()

    def snapshot(self) -> TerminalSessionSnapshot:
        return TerminalSessionSnapshot(
            id=self.id,
            cwd=self.cwd,
            command=self.command,
            created_at=self.created_at,
            pid=self._process.pid,
            running=self.running,
            exit_code=self.exit_code,
        )

    def write(self, data: str) -> None:
        if self._closed.is_set():
            return
        os.write(self._master_fd, data.encode("utf-8", errors="ignore"))

    def resize(self, *, cols: int, rows: int) -> None:
        self._set_winsize(cols=cols, rows=rows)

    @contextmanager
    def subscribe(self) -> Iterator[queue.Queue[bytes | None]]:
        subscriber: queue.Queue[bytes | None] = queue.Queue()
        with self._subscribers_lock:
            self._subscribers.add(subscriber)
        try:
            yield subscriber
        finally:
            with self._subscribers_lock:
                self._subscribers.discard(subscriber)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        if self.running:
            try:
                os.killpg(self._process.pid, signal.SIGTERM)
            except OSError:
                pass
        try:
            os.close(self._master_fd)
        except OSError:
            pass
        self._broadcast(None)

    def _set_winsize(self, *, cols: int, rows: int) -> None:
        rows = max(1, int(rows or 24))
        cols = max(1, int(cols or 80))
        fcntl.ioctl(
            self._master_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            try:
                readable, _, _ = select.select([self._master_fd], [], [], 0.1)
                if not readable:
                    if not self.running:
                        break
                    continue
                chunk = os.read(self._master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            self._broadcast(chunk)
        self._closed.set()
        self._broadcast(None)

    def _broadcast(self, chunk: bytes | None) -> None:
        with self._subscribers_lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(chunk)
            except queue.Full:
                pass


class TerminalSessionManager:
    def __init__(self, *, allowed_roots: tuple[Path, ...]) -> None:
        self.allowed_roots = tuple(path.expanduser().resolve() for path in allowed_roots)
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        *,
        cwd: str | Path,
        cols: int = 120,
        rows: int = 32,
        command: tuple[str, ...] | None = None,
    ) -> TerminalSessionSnapshot:
        resolved_cwd = resolve_allowed_cwd(cwd, self.allowed_roots)
        shell = os.environ.get("SHELL") or "/bin/bash"
        session = TerminalSession(
            session_id=uuid.uuid4().hex[:12],
            cwd=resolved_cwd,
            command=command or (shell,),
            cols=cols,
            rows=rows,
        )
        with self._lock:
            self._sessions[session.id] = session
        return session.snapshot()

    def list_sessions(self) -> tuple[TerminalSessionSnapshot, ...]:
        with self._lock:
            sessions = tuple(self._sessions.values())
        return tuple(session.snapshot() for session in sessions)

    def get(self, session_id: str) -> TerminalSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.close()
        return True

    def close_all(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
