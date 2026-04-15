"""Regression tests for the /history Telegram bot command.

Covers:
  1. No results directory → graceful "not found" message
  2. Empty results directory → "no history" message
  3. Single result file → correct prompt name, status icon, timestamps
  4. Multiple result files → sorted newest-first, truncated to n
  5. Status icon mapping (done, failed, in_progress, error, unknown)
  6. Supervisor verdict shown when present
  7. Completed timestamp suppressed for "not completed" values
  8. Custom n argument respected
  9. Long output truncated at 3800 chars
 10. /history in help text
 11. /history in menu keyboard
 12. /history registered in callback dispatcher
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
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


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_daemon_hardening.py)
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


def _make_result_md(
    *,
    prompt_name: str = "001-task.md",
    status: str = "done",
    started_at: str = "2026-01-01T00:00:00+00:00",
    completed_at: str = "2026-01-01T00:01:00+00:00",
    supervisor_verdict: str | None = None,
) -> str:
    lines = [
        f"# Result: {prompt_name}",
        "",
        "## Summary",
        "",
        f"- Status: `{status}`",
        f"- Prompt path: `/queue/prompts/{prompt_name}`",
        f"- Result path: `/queue/results/{prompt_name}_RESULT.md`",
        f"- Session id: `test-session`",
        f"- Watcher backend: `polling`",
        f"- Started at: `{started_at}`",
        f"- Completed at: `{completed_at}`",
        f"- Queue sort key: `{prompt_name}`",
    ]
    if supervisor_verdict:
        lines.append(f"- Supervisor verdict: `{supervisor_verdict}`")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Bot factory
# ---------------------------------------------------------------------------

def _make_bot(root: Path):
    from dormammu.telegram.bot import TelegramBot
    from dormammu.telegram.config import TelegramConfig

    _seed_repo(root)
    app_config = _app_config(root)
    app_config.base_dev_dir.mkdir(parents=True, exist_ok=True)

    mock_runner = mock.MagicMock()
    mock_runner.shutdown_requested = False
    mock_runner.in_progress_snapshot.return_value = frozenset()

    mock_stream = mock.MagicMock()
    mock_stream.streaming_chat_id = None

    tg_config = TelegramConfig(
        bot_token="1234:fake",
        allowed_chat_ids=[42],
        chunk_size=3000,
        flush_interval_seconds=2.0,
    )
    daemon_config = load_daemon_config(_write_daemon_config(root), app_config=app_config)
    bot = TelegramBot(
        tg_config,
        daemon_config=daemon_config,
        app_config=app_config,
        stream=mock_stream,
        runner=mock_runner,
    )
    return bot, daemon_config


def _make_update(chat_id: int = 42) -> mock.MagicMock:
    upd = mock.MagicMock()
    upd.effective_chat.id = chat_id
    upd.callback_query = None
    upd.message = mock.AsyncMock()
    return upd


def _last_reply(update: mock.MagicMock) -> str:
    """Return the text of the last reply_text call."""
    return update.message.reply_text.call_args[0][0]


# ===========================================================================
# 1-2. Missing / empty directory
# ===========================================================================

class HistoryMissingDirectoryTests(unittest.IsolatedAsyncioTestCase):

    async def test_no_results_dir_replies_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            # result_path directory is NOT created
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("No results directory", reply)

    async def test_empty_results_dir_replies_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("No history", reply)


# ===========================================================================
# 3. Single result file
# ===========================================================================

class HistorySingleResultTests(unittest.IsolatedAsyncioTestCase):

    async def test_prompt_name_stripped_of_result_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_file = daemon_config.result_path / "001-my-task.md_RESULT.md"
            result_file.write_text(
                _make_result_md(prompt_name="001-my-task.md", status="done"),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("001-my-task.md", reply)
            self.assertNotIn("_RESULT", reply)

    async def test_status_done_shows_check_icon(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_file = daemon_config.result_path / "task_RESULT.md"
            result_file.write_text(
                _make_result_md(prompt_name="task.md", status="done"),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("✅", reply)

    async def test_started_at_shown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_file = daemon_config.result_path / "task_RESULT.md"
            result_file.write_text(
                _make_result_md(started_at="2026-03-01T10:00:00+00:00"),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("2026-03-01T10:00:00", reply)

    async def test_completed_at_shown_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_file = daemon_config.result_path / "task_RESULT.md"
            result_file.write_text(
                _make_result_md(completed_at="2026-03-01T10:05:00+00:00"),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("2026-03-01T10:05:00", reply)

    async def test_not_completed_value_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_file = daemon_config.result_path / "task_RESULT.md"
            result_file.write_text(
                _make_result_md(completed_at="not completed"),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertNotIn("not completed", reply)


# ===========================================================================
# 4. Status icon mapping
# ===========================================================================

class HistoryStatusIconTests(unittest.IsolatedAsyncioTestCase):

    async def _icon_for_status(self, status: str) -> str:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_file = daemon_config.result_path / "task_RESULT.md"
            result_file.write_text(
                _make_result_md(status=status),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []
            await bot._send_history(update, context)
            return _last_reply(update)

    async def test_status_failed_shows_x_icon(self) -> None:
        reply = await self._icon_for_status("failed")
        self.assertIn("❌", reply)

    async def test_status_in_progress_shows_play_icon(self) -> None:
        reply = await self._icon_for_status("in_progress")
        self.assertIn("▶️", reply)

    async def test_status_error_shows_warning_icon(self) -> None:
        reply = await self._icon_for_status("error")
        self.assertIn("⚠️", reply)

    async def test_unknown_status_shows_question_icon(self) -> None:
        reply = await self._icon_for_status("something_unexpected")
        self.assertIn("❓", reply)


# ===========================================================================
# 5. Supervisor verdict
# ===========================================================================

class HistoryVerdictTests(unittest.IsolatedAsyncioTestCase):

    async def test_verdict_shown_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_file = daemon_config.result_path / "task_RESULT.md"
            result_file.write_text(
                _make_result_md(supervisor_verdict="PASS"),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("PASS", reply)
            self.assertIn("Verdict", reply)

    async def test_verdict_omitted_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            result_file = daemon_config.result_path / "task_RESULT.md"
            result_file.write_text(
                _make_result_md(supervisor_verdict=None),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertNotIn("Verdict", reply)


# ===========================================================================
# 6. Multiple results and n argument
# ===========================================================================

class HistoryMultipleResultsTests(unittest.IsolatedAsyncioTestCase):

    def _write_results(self, result_dir: Path, count: int) -> list[Path]:
        result_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(count):
            p = result_dir / f"{i:03d}-task.md_RESULT.md"
            p.write_text(
                _make_result_md(
                    prompt_name=f"{i:03d}-task.md",
                    status="done",
                    started_at=f"2026-01-{i + 1:02d}T00:00:00+00:00",
                    completed_at=f"2026-01-{i + 1:02d}T00:01:00+00:00",
                ),
                encoding="utf-8",
            )
            # Set mtime so ordering is deterministic
            os.utime(p, (i * 10, i * 10))
            paths.append(p)
        return paths

    async def test_default_n_is_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            self._write_results(daemon_config.result_path, 15)
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            # Header says "last 10"
            self.assertIn("last 10", reply)

    async def test_custom_n_argument_respected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            self._write_results(daemon_config.result_path, 15)
            update = _make_update()
            context = mock.MagicMock()
            context.args = ["3"]

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("last 3", reply)

    async def test_n_clamped_to_50(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            self._write_results(daemon_config.result_path, 5)
            update = _make_update()
            context = mock.MagicMock()
            context.args = ["999"]

            await bot._send_history(update, context)

            # Should not crash — n is clamped to 50, result shows all 5 available
            reply = _last_reply(update)
            self.assertIn("last 5", reply)

    async def test_invalid_n_shows_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            update = _make_update()
            context = mock.MagicMock()
            context.args = ["not_a_number"]

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertIn("Usage", reply)


# ===========================================================================
# 7. Long output truncation
# ===========================================================================

class HistoryTruncationTests(unittest.IsolatedAsyncioTestCase):

    async def test_output_truncated_at_3800_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, daemon_config = _make_bot(root)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            # Write a result file with a very long supervisor verdict
            long_verdict = "A" * 4000
            result_file = daemon_config.result_path / "task_RESULT.md"
            result_file.write_text(
                _make_result_md(supervisor_verdict=long_verdict),
                encoding="utf-8",
            )
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_history(update, context)

            reply = _last_reply(update)
            self.assertLessEqual(len(reply), 3815)  # 3800 + "\n…(truncated)" overhead
            self.assertIn("truncated", reply)


# ===========================================================================
# 8. Registration: help text, menu keyboard, callback
# ===========================================================================

class HistoryRegistrationTests(unittest.TestCase):

    def test_history_in_help_text(self) -> None:
        from dormammu.telegram.bot import _HELP_TEXT
        self.assertIn("history", _HELP_TEXT.lower())

    def test_history_in_menu_keyboard(self) -> None:
        from dormammu.telegram.bot import _MENU_KEYBOARD_BASE
        all_callbacks = [btn["callback_data"] for row in _MENU_KEYBOARD_BASE for btn in row]
        self.assertIn("history", all_callbacks)

    def test_history_callback_is_handled(self) -> None:
        """_cmd_callback must route 'history' without raising AttributeError."""
        import inspect
        from dormammu.telegram import bot as bot_module
        source = inspect.getsource(bot_module.TelegramBot._cmd_callback)
        self.assertIn('"history"', source)


if __name__ == "__main__":
    unittest.main()
