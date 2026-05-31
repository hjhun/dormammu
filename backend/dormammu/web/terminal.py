from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import queue
import re
import shlex
import shutil
import subprocess
import time
import uuid
from typing import Iterator


class TerminalAccessError(ValueError):
    """Raised when a requested terminal cwd is outside the configured roots."""


class TerminalRuntimeError(RuntimeError):
    """Raised when tmux cannot create or operate a terminal session."""


TMUX_SESSION_PREFIX = "dormammu-"
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


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


def tmux_session_name(session_id: str) -> str:
    if not _SESSION_ID_RE.match(session_id):
        raise TerminalRuntimeError(f"Invalid terminal session id: {session_id}")
    return f"{TMUX_SESSION_PREFIX}{session_id}"


def session_id_from_tmux_name(name: str) -> str | None:
    if not name.startswith(TMUX_SESSION_PREFIX):
        return None
    session_id = name[len(TMUX_SESSION_PREFIX):]
    return session_id if _SESSION_ID_RE.match(session_id) else None


def require_tmux() -> str:
    tmux = shutil.which("tmux")
    if not tmux:
        raise TerminalRuntimeError("tmux is required for persistent web terminal sessions")
    return tmux


def _iso_from_epoch(raw: str) -> str:
    try:
        value = int(raw)
    except ValueError:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _run_tmux(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [require_tmux(), *args]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "tmux command failed").strip()
        raise TerminalRuntimeError(detail)
    return result


@dataclass(frozen=True, slots=True)
class TerminalSessionSnapshot:
    id: str
    cwd: Path
    command: tuple[str, ...]
    created_at: str
    pid: int
    running: bool
    exit_code: int | None
    runtime: str = "tmux"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "cwd": str(self.cwd),
            "command": list(self.command),
            "created_at": self.created_at,
            "pid": self.pid,
            "running": self.running,
            "exit_code": self.exit_code,
            "runtime": self.runtime,
        }


class TerminalSession:
    def __init__(self, *, session_id: str) -> None:
        self.id = session_id
        self.name = tmux_session_name(session_id)
        self.target = f"{self.name}:0.0"

    @property
    def running(self) -> bool:
        return _run_tmux(["has-session", "-t", self.name], check=False).returncode == 0

    @property
    def exit_code(self) -> int | None:
        return None if self.running else 0

    def snapshot(self) -> TerminalSessionSnapshot:
        if not self.running:
            raise KeyError(self.id)
        created = _run_tmux(["display-message", "-p", "-t", self.name, "#{session_created}"]).stdout.strip()
        cwd = _run_tmux(["display-message", "-p", "-t", self.target, "#{pane_current_path}"]).stdout.strip()
        command = _run_tmux(["display-message", "-p", "-t", self.target, "#{pane_current_command}"]).stdout.strip()
        pid_raw = _run_tmux(["display-message", "-p", "-t", self.target, "#{pane_pid}"]).stdout.strip()
        try:
            pid = int(pid_raw)
        except ValueError:
            pid = 0
        return TerminalSessionSnapshot(
            id=self.id,
            cwd=Path(cwd).expanduser().resolve(),
            command=(command or "tmux",),
            created_at=_iso_from_epoch(created),
            pid=pid,
            running=True,
            exit_code=None,
        )

    def capture(self, *, start: int = -2000) -> str:
        result = _run_tmux(
            ["capture-pane", "-p", "-e", "-t", self.target, "-S", str(start)],
            check=False,
        )
        if result.returncode != 0:
            raise KeyError(self.id)
        return result.stdout

    def write(self, data: str) -> None:
        if not self.running:
            return
        for key_or_text, literal in _tmux_key_sequence(data):
            if not key_or_text:
                continue
            if literal:
                _run_tmux(["send-keys", "-t", self.target, "-l", key_or_text])
            else:
                _run_tmux(["send-keys", "-t", self.target, key_or_text])

    def resize(self, *, cols: int, rows: int) -> None:
        cols = max(1, int(cols or 80))
        rows = max(1, int(rows or 24))
        _run_tmux(["resize-pane", "-t", self.target, "-x", str(cols), "-y", str(rows)], check=False)

    @contextmanager
    def subscribe(self) -> Iterator[queue.Queue[bytes | None]]:
        subscriber: queue.Queue[bytes | None] = queue.Queue()
        stop = False

        def poll() -> None:
            previous = object()
            while not stop:
                if not self.running:
                    subscriber.put(None)
                    return
                try:
                    current = self.capture()
                except KeyError:
                    subscriber.put(None)
                    return
                if current != previous:
                    previous = current
                    subscriber.put(current.encode("utf-8", errors="replace"))
                time.sleep(0.35)

        import threading

        thread = threading.Thread(target=poll, name=f"dormammu-tmux-terminal-{self.id}", daemon=True)
        thread.start()
        try:
            yield subscriber
        finally:
            stop = True
            thread.join(timeout=1)

    def close(self) -> None:
        _run_tmux(["kill-session", "-t", self.name], check=False)


def _tmux_key_sequence(data: str) -> Iterator[tuple[str, bool]]:
    i = 0
    literal: list[str] = []

    def flush_literal() -> Iterator[tuple[str, bool]]:
        nonlocal literal
        if literal:
            value = "".join(literal)
            literal = []
            yield value, True

    special = {
        "\r": "Enter",
        "\n": "Enter",
        "\t": "Tab",
        "\x03": "C-c",
        "\x04": "C-d",
        "\x7f": "BSpace",
    }
    arrows = {
        "\x1b[A": "Up",
        "\x1b[B": "Down",
        "\x1b[C": "Right",
        "\x1b[D": "Left",
    }
    while i < len(data):
        matched = False
        for sequence, key in arrows.items():
            if data.startswith(sequence, i):
                yield from flush_literal()
                yield key, False
                i += len(sequence)
                matched = True
                break
        if matched:
            continue
        char = data[i]
        if char in special:
            yield from flush_literal()
            yield special[char], False
        else:
            literal.append(char)
        i += 1
    yield from flush_literal()


class TerminalSessionManager:
    def __init__(self, *, allowed_roots: tuple[Path, ...]) -> None:
        self.allowed_roots = tuple(path.expanduser().resolve() for path in allowed_roots)

    def create_session(
        self,
        *,
        cwd: str | Path,
        cols: int = 120,
        rows: int = 32,
        command: tuple[str, ...] | None = None,
    ) -> TerminalSessionSnapshot:
        resolved_cwd = resolve_allowed_cwd(cwd, self.allowed_roots)
        shell = command or (shutil.which("bash") or "/bin/bash",)
        session_id = uuid.uuid4().hex[:12]
        name = tmux_session_name(session_id)
        command_text = shlex.join(str(item) for item in shell)
        result = _run_tmux(
            [
                "new-session",
                "-d",
                "-s",
                name,
                "-c",
                str(resolved_cwd),
                "-x",
                str(max(1, int(cols or 120))),
                "-y",
                str(max(1, int(rows or 32))),
                command_text,
            ],
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "failed to create tmux session").strip()
            raise TerminalRuntimeError(detail)
        return TerminalSession(session_id=session_id).snapshot()

    def list_sessions(self) -> tuple[TerminalSessionSnapshot, ...]:
        result = _run_tmux(["list-sessions", "-F", "#{session_name}"], check=False)
        if result.returncode != 0:
            return ()
        snapshots: list[TerminalSessionSnapshot] = []
        for name in result.stdout.splitlines():
            session_id = session_id_from_tmux_name(name.strip())
            if not session_id:
                continue
            try:
                snapshot = TerminalSession(session_id=session_id).snapshot()
            except KeyError:
                continue
            try:
                resolve_allowed_cwd(snapshot.cwd, self.allowed_roots)
            except TerminalAccessError:
                continue
            snapshots.append(snapshot)
        return tuple(sorted(snapshots, key=lambda item: item.created_at, reverse=True))

    def get(self, session_id: str) -> TerminalSession:
        session = TerminalSession(session_id=session_id)
        if not session.running:
            raise KeyError(session_id)
        return session

    def delete(self, session_id: str) -> bool:
        session = TerminalSession(session_id=session_id)
        if not session.running:
            return False
        session.close()
        return True

    def close_all(self) -> None:
        for snapshot in self.list_sessions():
            self.delete(snapshot.id)
