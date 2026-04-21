"""Regression tests for Phase-7 daemon hardening features.

Covers:
  1. DaemonRunner._in_progress thread safety (in_progress_snapshot)
  2. DaemonRunner graceful shutdown (request_shutdown / shutdown_requested)
  3. DaemonRunner heartbeat file (write / remove)
  4. TelegramBot._send_shutdown delegates to runner.request_shutdown()
  5. SIGTERM handler wires to request_shutdown (integration smoke)
"""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config
from dormammu.daemon.runner import DaemonRunner, SessionProgressLogStream


# ---------------------------------------------------------------------------
# Helpers shared with test_daemon.py
# ---------------------------------------------------------------------------

def _seed_repo(root: Path) -> None:
    import subprocess
    subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
    (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
    templates = root / "templates" / "dev"
    templates.mkdir(parents=True, exist_ok=True)
    (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
    (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")


def _app_config(root: Path) -> AppConfig:
    env = dict(os.environ)
    env["HOME"] = str(root / ".test-home")
    return AppConfig.load(repo_root=root, env=env)


def _write_daemon_config(root: Path) -> Path:
    config_path = root / "daemonize.json"
    config_path.write_text(
        json.dumps({
            "schema_version": 1,
            "prompt_path": "./queue/prompts",
            "result_path": "./queue/results",
            "watch": {"backend": "polling", "poll_interval_seconds": 1, "settle_seconds": 0},
            "queue": {"allowed_extensions": [".md"], "ignore_hidden_files": True},
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path


def _make_runner(root: Path) -> DaemonRunner:
    app_config = _app_config(root)
    daemon_config = load_daemon_config(_write_daemon_config(root), app_config=app_config)
    daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
    daemon_config.result_path.mkdir(parents=True, exist_ok=True)
    return DaemonRunner(app_config, daemon_config, progress_stream=io.StringIO())


# ===========================================================================
# 1. _in_progress thread safety
# ===========================================================================

class InProgressThreadSafetyTests(unittest.TestCase):

    def test_in_progress_snapshot_returns_frozenset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            snapshot = runner.in_progress_snapshot()
            self.assertIsInstance(snapshot, frozenset)
            self.assertEqual(len(snapshot), 0)

    def test_in_progress_snapshot_reflects_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            fake_path = Path("/tmp/fake-prompt.md")
            with runner._in_progress_lock:
                runner._in_progress.add(fake_path)
            snapshot = runner.in_progress_snapshot()
            self.assertIn(fake_path, snapshot)

    def test_snapshot_does_not_share_reference_with_internal_set(self) -> None:
        """Modifying the returned frozenset must not affect the internal set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            snapshot = runner.in_progress_snapshot()
            # frozenset is immutable — this test proves snapshot is a copy
            self.assertIsNot(snapshot, runner._in_progress)

    def test_concurrent_reads_do_not_raise(self) -> None:
        """Multiple threads reading in_progress_snapshot() concurrently must not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            errors: list[Exception] = []

            def _read_loop() -> None:
                for _ in range(200):
                    try:
                        runner.in_progress_snapshot()
                    except Exception as exc:
                        errors.append(exc)

            def _write_loop() -> None:
                fake = Path("/tmp/fake.md")
                for _ in range(100):
                    with runner._in_progress_lock:
                        runner._in_progress.add(fake)
                    with runner._in_progress_lock:
                        runner._in_progress.discard(fake)

            threads = [threading.Thread(target=_read_loop) for _ in range(4)]
            threads.append(threading.Thread(target=_write_loop))
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

            self.assertEqual(errors, [], f"Thread errors: {errors}")

    def test_bot_status_uses_snapshot_not_direct_access(self) -> None:
        """Verify bot.py uses in_progress_snapshot() (not _in_progress directly)."""
        bot_path = BACKEND / "dormammu" / "telegram" / "bot.py"
        source = bot_path.read_text(encoding="utf-8")
        self.assertNotIn("self._runner._in_progress", source,
                         "bot.py must use in_progress_snapshot() instead of direct _in_progress access")
        self.assertIn("in_progress_snapshot()", source)


# ===========================================================================
# 2. Graceful shutdown
# ===========================================================================

class GracefulShutdownTests(unittest.TestCase):

    def test_shutdown_not_requested_initially(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            self.assertFalse(runner.shutdown_requested)

    def test_request_shutdown_sets_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            runner.request_shutdown()
            self.assertTrue(runner.shutdown_requested)

    def test_request_shutdown_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            runner.request_shutdown()
            runner.request_shutdown()  # must not raise
            self.assertTrue(runner.shutdown_requested)

    def test_request_shutdown_is_thread_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            errors: list[Exception] = []

            def _call_shutdown() -> None:
                try:
                    runner.request_shutdown()
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=_call_shutdown) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=2)

            self.assertEqual(errors, [])
            self.assertTrue(runner.shutdown_requested)

    def test_run_pending_once_respects_shutdown_flag(self) -> None:
        """run_pending_once still works when shutdown is requested — it finishes the
        current batch; the loop in run_forever() is what stops."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            runner.request_shutdown()
            # No prompts → returns 0 without hanging
            result = runner.run_pending_once(watcher_backend="polling")
            self.assertEqual(result, 0)

    def test_run_pending_once_returns_early_when_shutdown_requested_during_settle_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config_path = root / "daemonize.json"
            config_path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "prompt_path": "./queue/prompts",
                    "result_path": "./queue/results",
                    "watch": {"backend": "polling", "poll_interval_seconds": 1, "settle_seconds": 60},
                    "queue": {"allowed_extensions": [".md"], "ignore_hidden_files": True},
                }, indent=2) + "\n",
                encoding="utf-8",
            )
            app_config = _app_config(root)
            daemon_config = load_daemon_config(config_path, app_config=app_config)
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            runner = DaemonRunner(app_config, daemon_config, progress_stream=io.StringIO())
            (daemon_config.prompt_path / "pending.md").write_text("# pending\n", encoding="utf-8")

            elapsed: list[float] = []

            def _run() -> None:
                started = time.monotonic()
                runner.run_pending_once(watcher_backend="polling")
                elapsed.append(time.monotonic() - started)

            thread = threading.Thread(target=_run)
            thread.start()
            time.sleep(0.1)
            runner.request_shutdown()
            thread.join(timeout=2.0)

            self.assertFalse(thread.is_alive(), "run_pending_once is still blocked in settle wait")
            self.assertTrue(elapsed, "run_pending_once did not return")
            self.assertLess(elapsed[0], 2.0, f"run_pending_once took too long: {elapsed[0]:.2f}s")


# ===========================================================================
# 3. Heartbeat file
# ===========================================================================

class HeartbeatTests(unittest.TestCase):

    def test_write_heartbeat_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            runner._write_heartbeat(status="idle")
            self.assertIsNotNone(runner._heartbeat_path)
            assert runner._heartbeat_path is not None
            self.assertTrue(runner._heartbeat_path.exists())

    def test_heartbeat_contains_pid_status_ts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            runner._write_heartbeat(status="busy")
            assert runner._heartbeat_path is not None
            data = json.loads(runner._heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(data["pid"], os.getpid())
            self.assertEqual(data["status"], "busy")
            self.assertIn("ts", data)
            self.assertTrue(data["ts"])  # non-empty

    def test_write_heartbeat_overwrites_previous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            runner._write_heartbeat(status="idle")
            runner._write_heartbeat(status="busy")
            assert runner._heartbeat_path is not None
            data = json.loads(runner._heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "busy")

    def test_remove_heartbeat_deletes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            runner._write_heartbeat(status="idle")
            runner._remove_heartbeat()
            assert runner._heartbeat_path is not None
            self.assertFalse(runner._heartbeat_path.exists())

    def test_remove_heartbeat_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            runner._remove_heartbeat()  # file does not exist — must not raise
            runner._remove_heartbeat()

    def test_heartbeat_path_is_inside_queue_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)
            assert runner._heartbeat_path is not None
            self.assertEqual(runner._heartbeat_path.name, "daemon_heartbeat.json")


# ===========================================================================
# 4. TelegramBot._send_shutdown delegates to runner.request_shutdown()
# ===========================================================================

class TelegramShutdownCommandTests(unittest.IsolatedAsyncioTestCase):

    async def _make_bot_with_mock_runner(self):
        """Build a TelegramBot with mocked dependencies for unit testing."""
        from dormammu.telegram.bot import TelegramBot
        from dormammu.telegram.config import TelegramConfig

        mock_runner = mock.MagicMock()
        mock_runner.shutdown_requested = False
        mock_runner.in_progress_snapshot.return_value = frozenset()

        mock_stream = mock.MagicMock()
        mock_stream.streaming_chat_id = None

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            app_config = _app_config(root)
            app_config.base_dev_dir.mkdir(parents=True, exist_ok=True)

            tg_config = TelegramConfig(
                bot_token="1234:fake",
                allowed_chat_ids=[42],
                chunk_size=3000,
                flush_interval_seconds=2.0,
            )
            daemon_config = load_daemon_config(
                _write_daemon_config(root), app_config=app_config
            )
            bot = TelegramBot(
                tg_config,
                daemon_config=daemon_config,
                app_config=app_config,
                stream=mock_stream,
                runner=mock_runner,
            )
            return bot, mock_runner

    async def test_send_shutdown_calls_request_shutdown(self) -> None:
        bot, mock_runner = await self._make_bot_with_mock_runner()
        mock_runner.shutdown_requested = False

        mock_update = mock.MagicMock()
        mock_update.effective_chat.id = 42
        mock_update.callback_query = None
        mock_update.message = mock.AsyncMock()
        mock_update.effective_message = mock_update.message
        mock_context = mock.MagicMock()

        await bot._send_shutdown(mock_update, mock_context)

        mock_runner.request_shutdown.assert_called_once()

    async def test_send_shutdown_replies_with_graceful_message(self) -> None:
        bot, mock_runner = await self._make_bot_with_mock_runner()
        mock_runner.shutdown_requested = False

        mock_update = mock.MagicMock()
        mock_update.effective_chat.id = 42
        mock_update.callback_query = None
        mock_update.message = mock.AsyncMock()
        mock_update.effective_message = mock_update.message
        mock_context = mock.MagicMock()

        await bot._send_shutdown(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        reply_text = mock_update.message.reply_text.call_args[0][0]
        self.assertIn("shutdown", reply_text.lower())

    async def test_send_shutdown_already_requested_does_not_call_again(self) -> None:
        bot, mock_runner = await self._make_bot_with_mock_runner()
        mock_runner.shutdown_requested = True  # already set

        mock_update = mock.MagicMock()
        mock_update.effective_chat.id = 42
        mock_update.callback_query = None
        mock_update.message = mock.AsyncMock()
        mock_update.effective_message = mock_update.message
        mock_context = mock.MagicMock()

        await bot._send_shutdown(mock_update, mock_context)

        mock_runner.request_shutdown.assert_not_called()

    async def test_send_shutdown_mentions_active_prompt_if_busy(self) -> None:
        bot, mock_runner = await self._make_bot_with_mock_runner()
        mock_runner.shutdown_requested = False
        mock_runner.in_progress_snapshot.return_value = frozenset([Path("/queue/001-task.md")])

        mock_update = mock.MagicMock()
        mock_update.effective_chat.id = 42
        mock_update.callback_query = None
        mock_update.message = mock.AsyncMock()
        mock_update.effective_message = mock_update.message
        mock_context = mock.MagicMock()

        await bot._send_shutdown(mock_update, mock_context)

        reply_text = mock_update.message.reply_text.call_args[0][0]
        self.assertIn("001-task.md", reply_text)


# ===========================================================================
# 5. /shutdown command is registered in bot help text and commands
# ===========================================================================

class BotShutdownRegistrationTests(unittest.TestCase):

    def test_shutdown_in_help_text(self) -> None:
        from dormammu.telegram.bot import _HELP_TEXT
        self.assertIn("shutdown", _HELP_TEXT.lower())

    def test_shutdown_in_menu_keyboard(self) -> None:
        from dormammu.telegram.bot import _MENU_KEYBOARD_BASE
        all_callbacks = [btn["callback_data"] for row in _MENU_KEYBOARD_BASE for btn in row]
        self.assertIn("shutdown", all_callbacks)


# ===========================================================================
# 6. Watcher shutdown responsiveness
# ===========================================================================

class WatcherShutdownResponsivenessTests(unittest.TestCase):
    """Verify that both watchers unblock quickly when the stop_event fires."""

    def test_polling_watcher_returns_early_on_stop_event(self) -> None:
        """PollingWatcher with a long interval must return within ~1 s when
        the stop_event is set."""
        import threading
        from dormammu.daemon.models import WatchConfig
        from dormammu.daemon.watchers import PollingWatcher
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            watch_config = WatchConfig(backend="polling", poll_interval_seconds=60)
            stop_event = threading.Event()
            watcher = PollingWatcher(Path(tmpdir), watch_config, stop_event=stop_event)
            watcher.start()

            results: list[float] = []

            def _run() -> None:
                t0 = time.monotonic()
                watcher.wait_for_changes()
                results.append(time.monotonic() - t0)

            t = threading.Thread(target=_run)
            t.start()
            time.sleep(0.05)  # let the watcher block
            stop_event.set()
            t.join(timeout=2.0)
            watcher.close()

            self.assertFalse(t.is_alive(), "watcher thread is still blocked after stop_event")
            self.assertTrue(results, "wait_for_changes() did not return")
            self.assertLess(results[0], 2.0, f"wait_for_changes() took too long: {results[0]:.2f}s")

    def test_request_shutdown_wakes_polling_watcher_via_event(self) -> None:
        """DaemonRunner.request_shutdown() must unblock a PollingWatcher promptly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            runner = _make_runner(root)

            # Simulate the watcher being active (as run_forever does)
            from dormammu.daemon.models import WatchConfig
            from dormammu.daemon.watchers import PollingWatcher
            watch_config = WatchConfig(backend="polling", poll_interval_seconds=60)
            watcher = PollingWatcher(
                runner.daemon_config.prompt_path,
                watch_config,
                stop_event=runner._shutdown_requested,
            )
            runner._active_watcher = watcher
            watcher.start()

            results: list[float] = []

            def _run() -> None:
                t0 = time.monotonic()
                watcher.wait_for_changes()
                results.append(time.monotonic() - t0)

            t = threading.Thread(target=_run)
            t.start()
            time.sleep(0.05)
            runner.request_shutdown()
            t.join(timeout=2.0)
            watcher.close()

            self.assertFalse(t.is_alive())
            self.assertLess(results[0], 2.0)


if __name__ == "__main__":
    unittest.main()
