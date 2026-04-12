from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
from pathlib import Path
import select
import struct
import threading
import time
from typing import Callable, Final, Protocol

from dormammu.daemon.models import WatchConfig


EFFECTIVE_POLL_INTERVAL_SECONDS: Final[int] = 60


class PromptWatcher(Protocol):
    backend_name: str

    def start(self) -> None: ...

    def close(self) -> None: ...

    def wait_for_changes(self) -> list[Path]: ...


class PollingWatcher:
    backend_name = "polling"

    def __init__(
        self,
        prompt_dir: Path,
        watch_config: WatchConfig,
        *,
        event_logger: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.prompt_dir = prompt_dir
        self.watch_config = watch_config
        self._event_logger = event_logger
        self._stop_event = stop_event

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None

    def wait_for_changes(self) -> list[Path]:
        if self._stop_event is not None:
            # Block until the poll interval elapses OR the stop event fires,
            # whichever comes first.  This makes /shutdown respond immediately.
            self._stop_event.wait(timeout=self.watch_config.poll_interval_seconds)
        else:
            time.sleep(self.watch_config.poll_interval_seconds)
        paths = list(self.prompt_dir.iterdir()) if self.prompt_dir.exists() else []
        if self._event_logger is not None:
            self._event_logger(
                "daemon watcher event: backend=polling "
                f"interval={self.watch_config.poll_interval_seconds}s "
                f"candidates={len(paths)}"
            )
        return paths


class InotifyWatcher:
    backend_name = "inotify"
    _EVENT_STRUCT = struct.Struct("iIII")
    _IN_NONBLOCK = 0x800
    _IN_CLOEXEC = 0x80000
    _IN_MOVED_TO = 0x00000080
    _IN_CLOSE_WRITE = 0x00000008
    _IN_CREATE = 0x00000100
    _IN_DELETE = 0x00000200
    _IN_ATTRIB = 0x00000004
    _READY_MASK = _IN_MOVED_TO | _IN_CLOSE_WRITE
    _WATCH_MASK = _READY_MASK | _IN_CREATE | _IN_DELETE | _IN_ATTRIB
    _MASK_NAMES = {
        _IN_CREATE: "IN_CREATE",
        _IN_CLOSE_WRITE: "IN_CLOSE_WRITE",
        _IN_MOVED_TO: "IN_MOVED_TO",
        _IN_DELETE: "IN_DELETE",
        _IN_ATTRIB: "IN_ATTRIB",
    }

    def __init__(
        self,
        prompt_dir: Path,
        watch_config: WatchConfig,
        *,
        event_logger: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.prompt_dir = prompt_dir
        self.watch_config = watch_config
        self._event_logger = event_logger
        self._stop_event = stop_event
        self._fd: int | None = None
        # Wake-up pipe: a byte written to _wake_w makes select() return
        # immediately so that the shutdown signal is honoured without delay.
        self._wake_r: int | None = None
        self._wake_w: int | None = None
        libc_name = ctypes.util.find_library("c") or "libc.so.6"
        self._libc = ctypes.CDLL(libc_name, use_errno=True)

    @classmethod
    def is_available(cls) -> bool:
        return os.name == "posix" and "linux" in os.sys.platform

    def start(self) -> None:
        fd = self._libc.inotify_init1(self._IN_NONBLOCK | self._IN_CLOEXEC)
        if fd < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        self._fd = fd
        watch_descriptor = self._libc.inotify_add_watch(
            fd,
            os.fsencode(str(self.prompt_dir)),
            ctypes.c_uint32(self._WATCH_MASK),
        )
        if watch_descriptor < 0:
            err = ctypes.get_errno()
            os.close(fd)
            self._fd = None
            raise OSError(err, os.strerror(err))
        # Create the wake-up pipe for interrupt-driven shutdown.
        self._wake_r, self._wake_w = os.pipe()
        self._log_event(
            "daemon watcher event: backend=inotify "
            f"watching={self.prompt_dir} mask={self._format_mask(self._WATCH_MASK)}"
        )

    def _wake_up(self) -> None:
        """Write a single byte to the wake-up pipe to unblock select()."""
        if self._wake_w is not None:
            try:
                os.write(self._wake_w, b"\x00")
            except OSError:
                pass

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._wake_w is not None:
            try:
                os.close(self._wake_w)
            except OSError:
                pass
            self._wake_w = None
        if self._wake_r is not None:
            try:
                os.close(self._wake_r)
            except OSError:
                pass
            self._wake_r = None

    def wait_for_changes(self) -> list[Path]:
        if self._fd is None:
            raise RuntimeError("Inotify watcher has not been started.")
        while True:
            fds = [self._fd]
            if self._wake_r is not None:
                fds.append(self._wake_r)
            try:
                readable, _, _ = select.select(fds, [], [])
            except (OSError, ValueError):
                # fd was closed (e.g. during shutdown) — return empty
                return []
            # Wake-up pipe fired → shutdown requested; drain and return.
            if self._wake_r is not None and self._wake_r in readable:
                try:
                    os.read(self._wake_r, 256)
                except OSError:
                    pass
                return []
            if self._fd not in readable:
                continue
            try:
                payload = os.read(self._fd, 4096)
            except BlockingIOError:
                continue
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise
            if not payload:
                return []

            paths: list[Path] = []
            offset = 0
            while offset + self._EVENT_STRUCT.size <= len(payload):
                _, mask, _, name_len = self._EVENT_STRUCT.unpack_from(payload, offset)
                offset += self._EVENT_STRUCT.size
                name_bytes = payload[offset : offset + name_len]
                offset += name_len
                filename = name_bytes.rstrip(b"\0").decode("utf-8", errors="ignore")
                path = self.prompt_dir / filename if filename else self.prompt_dir
                self._log_event(
                    "daemon watcher event: backend=inotify "
                    f"mask={self._format_mask(mask)} path={path}"
                )
                if filename and mask & self._READY_MASK:
                    paths.append(path)
            if paths:
                return paths

    def _format_mask(self, mask: int) -> str:
        names = [name for bit, name in self._MASK_NAMES.items() if mask & bit]
        if not names:
            return hex(mask)
        return "|".join(names)

    def _log_event(self, message: str) -> None:
        if self._event_logger is not None:
            self._event_logger(message)


def build_watcher(
    prompt_dir: Path,
    watch_config: WatchConfig,
    *,
    event_logger: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> PromptWatcher:
    if watch_config.backend == "polling":
        return PollingWatcher(prompt_dir, watch_config, event_logger=event_logger, stop_event=stop_event)
    if watch_config.backend == "inotify":
        if not InotifyWatcher.is_available():
            raise RuntimeError("Inotify backend is not available on this platform.")
        return InotifyWatcher(prompt_dir, watch_config, event_logger=event_logger, stop_event=stop_event)
    if watch_config.backend == "auto":
        if InotifyWatcher.is_available():
            return InotifyWatcher(prompt_dir, watch_config, event_logger=event_logger, stop_event=stop_event)
        return PollingWatcher(prompt_dir, watch_config, event_logger=event_logger, stop_event=stop_event)
    raise RuntimeError(f"Unsupported watcher backend: {watch_config.backend}")
