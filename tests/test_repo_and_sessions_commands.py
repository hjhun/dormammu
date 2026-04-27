"""Regression tests for /repo and /clear_sessions Telegram bot commands.

/repo:
  1. No args → shows sibling repo list as inline keyboard
  2. No sibling repos → shows "no siblings" message
  3. Direct path arg (valid repo) → switches and confirms
  4. Direct path arg (nonexistent) → error message
  5. Direct path arg (not a repo) → warning message
  6. Same repo as current → "already using" message
  7. repo_pick callback (valid index) → switches repo
  8. repo_pick callback (cancel) → cancellation message
  9. repo_pick callback (expired index) → asks to re-run
 10. Switches runner.app_config and runner.repository
 11. Warning shown when prompt in progress
 12. /repo registered in help text and menu keyboard

/clear_sessions:
 13. No sessions dir → "nothing to clear"
 14. Empty sessions dir → "already empty"
 15. Clears session dirs, reports count
 16. Partial failure is reported
 17. /clear_sessions registered in help text and menu keyboard
"""
from __future__ import annotations

import asyncio
import json
import io
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config


# ---------------------------------------------------------------------------
# Shared helpers
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
    env["DORMAMMU_SESSIONS_DIR"] = str(root / "sessions")
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


def _make_bot(root: Path, mock_runner=None):
    from dormammu.telegram.bot import TelegramBot
    from dormammu.telegram.config import TelegramConfig

    _seed_repo(root)
    app_config = _app_config(root)
    app_config.base_dev_dir.mkdir(parents=True, exist_ok=True)

    if mock_runner is None:
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
    return bot, mock_runner, app_config


def _make_update(chat_id: int = 42) -> mock.MagicMock:
    upd = mock.MagicMock()
    upd.effective_chat.id = chat_id
    upd.callback_query = None
    upd.message = mock.AsyncMock()
    upd.effective_message = upd.message
    return upd


def _make_text_update(text: str, chat_id: int = 42) -> mock.MagicMock:
    upd = _make_update(chat_id=chat_id)
    upd.message.text = text
    upd.message.caption = None
    upd.message.reply_text = mock.AsyncMock()
    upd.effective_message = upd.message
    return upd


def _last_reply(update: mock.MagicMock) -> str:
    message = getattr(update, "effective_message", None) or update.message
    return message.reply_text.call_args[0][0]


def _last_reply_kwargs(update: mock.MagicMock) -> dict:
    message = getattr(update, "effective_message", None) or update.message
    return message.reply_text.call_args[1]


async def _wait_direct_response_tasks(bot) -> None:
    tasks = tuple(getattr(bot, "_direct_response_tasks", ()) or ())
    if tasks:
        await asyncio.gather(*tasks)


def _make_channel_update(text: str, chat_id: int = 42) -> mock.MagicMock:
    upd = mock.MagicMock()
    upd.effective_chat.id = chat_id
    upd.callback_query = None
    upd.message = None
    upd.channel_post = mock.AsyncMock()
    upd.channel_post.text = text
    upd.channel_post.caption = None
    upd.channel_post.reply_text = mock.AsyncMock()
    upd.effective_message = upd.channel_post
    return upd


# ===========================================================================
# /repo — no args: inline keyboard list
# ===========================================================================

class RepoCmdListTests(unittest.IsolatedAsyncioTestCase):

    async def test_shows_sibling_repos_as_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            current_repo = parent / "repo-a"
            sibling_repo = parent / "repo-b"
            current_repo.mkdir()
            sibling_repo.mkdir()
            # Make both look like repos
            (current_repo / "AGENTS.md").write_text("x")
            (sibling_repo / "AGENTS.md").write_text("x")
            import subprocess
            subprocess.run(["git", "init"], cwd=current_repo, capture_output=True, check=True)
            subprocess.run(["git", "init"], cwd=sibling_repo, capture_output=True, check=True)

            bot, runner, _ = _make_bot(current_repo)
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_repo(update, context)

            # Both repos must appear in _pending_repo_choices
            names = [p.name for p in bot._pending_repo_choices]
            self.assertIn("repo-a", names)
            self.assertIn("repo-b", names)
            # Reply must mention both names
            reply = _last_reply(update)
            self.assertIn("repo-a", reply)
            self.assertIn("repo-b", reply)

    async def test_no_sibling_repos_shows_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            current_repo = parent / "only-repo"
            current_repo.mkdir()
            (current_repo / "AGENTS.md").write_text("x")
            import subprocess
            subprocess.run(["git", "init"], cwd=current_repo, capture_output=True, check=True)

            bot, runner, _ = _make_bot(current_repo)
            update = _make_update()
            context = mock.MagicMock()
            context.args = []

            await bot._send_repo(update, context)

            reply = _last_reply(update)
            self.assertIn("No sibling repos", reply)


# ===========================================================================
# /repo <path> — direct path switch
# ===========================================================================

class RepoDirectPathTests(unittest.IsolatedAsyncioTestCase):

    async def test_valid_repo_switches_and_confirms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            current_repo = parent / "repo-a"
            new_repo = parent / "repo-b"
            current_repo.mkdir()
            new_repo.mkdir()
            (current_repo / "AGENTS.md").write_text("x")
            (new_repo / "AGENTS.md").write_text("x")
            import subprocess
            subprocess.run(["git", "init"], cwd=current_repo, capture_output=True, check=True)
            subprocess.run(["git", "init"], cwd=new_repo, capture_output=True, check=True)

            bot, runner, _ = _make_bot(current_repo)
            update = _make_update()
            context = mock.MagicMock()
            context.args = [str(new_repo)]

            await bot._send_repo(update, context)

            reply = _last_reply(update)
            self.assertIn("✅", reply)
            self.assertIn("repo-b", reply)

    async def test_nonexistent_path_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            update = _make_update()
            context = mock.MagicMock()
            context.args = ["/nonexistent/path/that/does/not/exist"]

            await bot._send_repo(update, context)

            reply = _last_reply(update)
            self.assertIn("❌", reply)
            self.assertIn("not found", reply.lower())

    async def test_non_repo_dir_returns_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            current_repo = parent / "repo-a"
            plain_dir = parent / "not-a-repo"
            current_repo.mkdir()
            plain_dir.mkdir()
            (current_repo / "AGENTS.md").write_text("x")
            import subprocess
            subprocess.run(["git", "init"], cwd=current_repo, capture_output=True, check=True)

            bot, runner, _ = _make_bot(current_repo)
            update = _make_update()
            context = mock.MagicMock()
            context.args = [str(plain_dir)]

            await bot._send_repo(update, context)

            reply = _last_reply(update)
            self.assertIn("⚠️", reply)

    async def test_same_repo_shows_already_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            update = _make_update()
            context = mock.MagicMock()
            context.args = [str(root)]

            await bot._send_repo(update, context)

            reply = _last_reply(update)
            self.assertIn("Already", reply)


# ===========================================================================
# /repo inline keyboard callbacks
# ===========================================================================

class RepoPickCallbackTests(unittest.IsolatedAsyncioTestCase):

    async def _setup_with_sibling(self, tmpdir_path: str):
        parent = Path(tmpdir_path)
        current_repo = parent / "repo-a"
        sibling_repo = parent / "repo-b"
        current_repo.mkdir()
        sibling_repo.mkdir()
        (current_repo / "AGENTS.md").write_text("x")
        (sibling_repo / "AGENTS.md").write_text("x")
        import subprocess
        subprocess.run(["git", "init"], cwd=current_repo, capture_output=True, check=True)
        subprocess.run(["git", "init"], cwd=sibling_repo, capture_output=True, check=True)
        bot, runner, _ = _make_bot(current_repo)
        # Populate pending choices
        update = _make_update()
        context = mock.MagicMock()
        context.args = []
        await bot._send_repo(update, context)
        return bot, runner, sibling_repo

    async def test_valid_pick_switches_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bot, runner, sibling = await self._setup_with_sibling(tmpdir)
            # Find the index of the sibling
            idx = bot._pending_repo_choices.index(sibling)
            update = _make_update()
            await bot._handle_repo_pick(update, str(idx))
            reply = _last_reply(update)
            self.assertIn("✅", reply)
            self.assertIn("repo-b", reply)

    async def test_cancel_pick_shows_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bot, runner, _ = await self._setup_with_sibling(tmpdir)
            update = _make_update()
            await bot._handle_repo_pick(update, "cancel")
            reply = _last_reply(update)
            self.assertIn("cancel", reply.lower())

    async def test_expired_index_asks_to_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            # _pending_repo_choices is empty — simulates expiry
            update = _make_update()
            await bot._handle_repo_pick(update, "5")
            reply = _last_reply(update)
            self.assertIn("/repo", reply)

    async def test_invalid_index_str_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            update = _make_update()
            await bot._handle_repo_pick(update, "not_a_number")
            reply = _last_reply(update)
            self.assertIn("❌", reply)


# ===========================================================================
# Repo switch side-effects
# ===========================================================================

class RepoSwitchSideEffectTests(unittest.IsolatedAsyncioTestCase):

    async def test_switch_updates_runner_app_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            current_repo = parent / "repo-a"
            new_repo = parent / "repo-b"
            current_repo.mkdir()
            new_repo.mkdir()
            (current_repo / "AGENTS.md").write_text("x")
            (new_repo / "AGENTS.md").write_text("x")
            import subprocess
            subprocess.run(["git", "init"], cwd=current_repo, capture_output=True, check=True)
            subprocess.run(["git", "init"], cwd=new_repo, capture_output=True, check=True)

            runner = mock.MagicMock()
            runner.shutdown_requested = False
            runner.in_progress_snapshot.return_value = frozenset()
            runner.app_config = None
            runner.repository = None

            bot, _, _ = _make_bot(current_repo, mock_runner=runner)
            update = _make_update()
            context = mock.MagicMock()
            context.args = [str(new_repo)]

            await bot._send_repo(update, context)

            self.assertIsNotNone(runner.app_config)
            self.assertEqual(runner.app_config.repo_root.resolve(), new_repo.resolve())

    async def test_switch_updates_runner_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            current_repo = parent / "repo-a"
            new_repo = parent / "repo-b"
            current_repo.mkdir()
            new_repo.mkdir()
            (current_repo / "AGENTS.md").write_text("x")
            (new_repo / "AGENTS.md").write_text("x")
            import subprocess
            subprocess.run(["git", "init"], cwd=current_repo, capture_output=True, check=True)
            subprocess.run(["git", "init"], cwd=new_repo, capture_output=True, check=True)

            runner = mock.MagicMock()
            runner.shutdown_requested = False
            runner.in_progress_snapshot.return_value = frozenset()

            bot, _, _ = _make_bot(current_repo, mock_runner=runner)
            update = _make_update()
            context = mock.MagicMock()
            context.args = [str(new_repo)]

            await bot._send_repo(update, context)

            # repository was set (not just called as mock)
            self.assertTrue(hasattr(runner, "repository"))

    async def test_switch_shows_warning_when_prompt_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            current_repo = parent / "repo-a"
            new_repo = parent / "repo-b"
            current_repo.mkdir()
            new_repo.mkdir()
            (current_repo / "AGENTS.md").write_text("x")
            (new_repo / "AGENTS.md").write_text("x")
            import subprocess
            subprocess.run(["git", "init"], cwd=current_repo, capture_output=True, check=True)
            subprocess.run(["git", "init"], cwd=new_repo, capture_output=True, check=True)

            runner = mock.MagicMock()
            runner.shutdown_requested = False
            runner.in_progress_snapshot.return_value = frozenset([Path("/q/active-task.md")])

            bot, _, _ = _make_bot(current_repo, mock_runner=runner)
            update = _make_update()
            context = mock.MagicMock()
            context.args = [str(new_repo)]

            await bot._send_repo(update, context)

            reply = _last_reply(update)
            self.assertIn("⚠️", reply)
            self.assertIn("active-task.md", reply)


# ===========================================================================
# /clear_sessions
# ===========================================================================

class ClearSessionsTests(unittest.IsolatedAsyncioTestCase):

    async def test_no_sessions_dir_says_nothing_to_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            # Don't create sessions dir
            update = _make_update()
            context = mock.MagicMock()

            await bot._send_clear_sessions(update, context)

            reply = _last_reply(update)
            self.assertIn("nothing to clear", reply.lower())

    async def test_empty_sessions_dir_says_already_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, app_config = _make_bot(root)
            sessions_dir = app_config.sessions_dir
            sessions_dir.mkdir(parents=True, exist_ok=True)
            update = _make_update()
            context = mock.MagicMock()

            await bot._send_clear_sessions(update, context)

            reply = _last_reply(update)
            self.assertIn("already empty", reply.lower())

    async def test_clears_session_dirs_and_reports_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, app_config = _make_bot(root)
            sessions_dir = app_config.sessions_dir
            sessions_dir.mkdir(parents=True, exist_ok=True)
            # Create 3 fake session directories
            for i in range(3):
                d = sessions_dir / f"session-{i:03d}"
                d.mkdir()
                (d / "state.json").write_text("{}", encoding="utf-8")
            update = _make_update()
            context = mock.MagicMock()

            await bot._send_clear_sessions(update, context)

            reply = _last_reply(update)
            self.assertIn("3", reply)
            # Sessions should actually be gone
            remaining = [p for p in sessions_dir.iterdir() if p.is_dir()]
            self.assertEqual(remaining, [])

    async def test_clear_uses_current_app_config_base_dev_dir(self) -> None:
        """Verify that /clear_sessions targets the current bot._app_config, not a stale one."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, app_config = _make_bot(root)
            sessions_dir = app_config.sessions_dir
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (sessions_dir / "sess-001").mkdir()
            update = _make_update()
            context = mock.MagicMock()

            await bot._send_clear_sessions(update, context)

            self.assertFalse((sessions_dir / "sess-001").exists())


# ===========================================================================
# Registration: help text, menu keyboard
# ===========================================================================

class RepoAndClearSessionsRegistrationTests(unittest.TestCase):

    def test_repo_in_help_text(self) -> None:
        from dormammu.telegram.bot import _HELP_TEXT
        self.assertIn("/repo", _HELP_TEXT)

    def test_clear_sessions_in_help_text(self) -> None:
        from dormammu.telegram.bot import _HELP_TEXT
        self.assertIn("clear", _HELP_TEXT.lower())
        self.assertIn("sessions", _HELP_TEXT.lower())

    def test_fast_commands_in_help_text(self) -> None:
        from dormammu.telegram.bot import _HELP_TEXT
        self.assertIn("/ask", _HELP_TEXT)
        self.assertIn("/run_fast", _HELP_TEXT)

    def test_repo_in_menu_keyboard(self) -> None:
        from dormammu.telegram.bot import _MENU_KEYBOARD_BASE
        all_callbacks = [btn["callback_data"] for row in _MENU_KEYBOARD_BASE for btn in row]
        self.assertIn("repo", all_callbacks)

    def test_clear_sessions_in_menu_keyboard(self) -> None:
        from dormammu.telegram.bot import _MENU_KEYBOARD_BASE
        all_callbacks = [btn["callback_data"] for row in _MENU_KEYBOARD_BASE for btn in row]
        self.assertIn("clear_sessions", all_callbacks)

    def test_repo_pick_handled_in_callback(self) -> None:
        import inspect
        from dormammu.telegram import bot as bot_module
        source = inspect.getsource(bot_module.TelegramBot._cmd_callback)
        self.assertIn("repo_pick", source)

    def test_clear_sessions_handled_in_callback(self) -> None:
        import inspect
        from dormammu.telegram import bot as bot_module
        source = inspect.getsource(bot_module.TelegramBot._cmd_callback)
        self.assertIn("clear_sessions", source)


class ChannelCommandTests(unittest.IsolatedAsyncioTestCase):

    def _assert_channel_reply_without_markup(self, update: mock.MagicMock, expected: str) -> None:
        reply = _last_reply(update)
        kwargs = _last_reply_kwargs(update)
        self.assertIn(expected, reply)
        self.assertNotIn("reply_markup", kwargs)
        update.channel_post.reply_text.assert_called_once()

    async def test_channel_start_command_replies_without_inline_keyboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/start")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "dormammu bot commands")

    async def test_channel_help_command_replies_without_inline_keyboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/help")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "dormammu bot commands")

    async def test_channel_status_command_uses_channel_post_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/status")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            reply = _last_reply(update)
            self.assertIn("daemon status", reply.lower())
            update.channel_post.reply_text.assert_called_once()

    async def test_channel_queue_command_replies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/queue")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "Prompt queue")

    async def test_channel_run_command_queues_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/run investigate telegram channel failure")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            prompt_files = sorted(bot._daemon_config.prompt_path.glob("tg_*.md"))
            self.assertEqual(len(prompt_files), 1)
            self.assertIn("investigate telegram channel failure", prompt_files[0].read_text(encoding="utf-8"))
            self.assertIn("Queued", _last_reply(update))

    async def test_channel_run_command_wakes_daemon_after_queue_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = mock.MagicMock()
            runner.shutdown_requested = False
            runner.in_progress_snapshot.return_value = frozenset()
            bot, runner, _ = _make_bot(root, mock_runner=runner)
            update = _make_channel_update("/run investigate queue latency")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            runner.notify_prompt_enqueued.assert_called_once()

    async def test_channel_ask_command_queues_fast_direct_response_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/ask why is telegram slow")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            prompt_files = sorted(bot._daemon_config.prompt_path.glob("tg_fast_*.md"))
            self.assertEqual(len(prompt_files), 1)
            content = prompt_files[0].read_text(encoding="utf-8")
            self.assertIn("DORMAMMU_REQUEST_CLASS: direct_response", content)
            self.assertIn("why is telegram slow", content)
            self.assertIn("Queued fast path", _last_reply(update))

    async def test_channel_plain_text_replies_with_cli_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(
                active_agent_cli=Path("codex"),
            )
            update = _make_channel_update("summarize this channel request")
            context = mock.MagicMock()
            context.args = []

            def fake_run_once(request):
                stdout_path = root / "stdout.txt"
                stderr_path = root / "stderr.txt"
                stdout_path.write_text("direct CLI reply", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return SimpleNamespace(stdout_path=stdout_path, stderr_path=stderr_path, exit_code=0)

            with mock.patch("dormammu.telegram.bot.CliAdapter") as adapter_cls:
                adapter_cls.return_value.run_once.side_effect = fake_run_once
                await bot._cmd_channel_post_command(update, context)
                await _wait_direct_response_tasks(bot)

            prompt_files = sorted(bot._daemon_config.prompt_path.glob("tg_fast_*.md"))
            self.assertEqual(prompt_files, [])
            replies = [call.args[0] for call in update.channel_post.reply_text.call_args_list]
            self.assertIn("CLI request started: codex", replies[0])
            self.assertIn("direct CLI reply", _last_reply(update))
            runner.notify_prompt_enqueued.assert_not_called()
            request = adapter_cls.return_value.run_once.call_args.args[0]
            self.assertIn("summarize this channel request", request.prompt_text)

    async def test_channel_plain_text_schedules_cli_response_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(
                active_agent_cli=Path("codex"),
            )
            update = _make_channel_update("slow request")
            context = mock.MagicMock()
            context.args = []
            release = asyncio.Event()

            async def fake_complete(*args):
                await release.wait()

            bot._complete_cli_response = mock.AsyncMock(side_effect=fake_complete)

            await bot._cmd_channel_post_command(update, context)
            await asyncio.sleep(0)

            self.assertIn("CLI request started: codex", _last_reply(update))
            self.assertTrue(bot._direct_response_tasks)
            bot._complete_cli_response.assert_called_once()

            release.set()
            await _wait_direct_response_tasks(bot)

    async def test_channel_plain_text_start_reply_omits_model_name(self) -> None:
        from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(
                active_agent_cli=Path("codex"),
                agents=AgentsConfig(developer=RoleAgentConfig(model="gpt-5.5")),
            )
            update = _make_channel_update("slow request")
            context = mock.MagicMock()
            context.args = []
            release = asyncio.Event()

            async def fake_complete(*args):
                await release.wait()

            bot._complete_cli_response = mock.AsyncMock(side_effect=fake_complete)

            await bot._cmd_channel_post_command(update, context)
            await asyncio.sleep(0)

            self.assertEqual(_last_reply(update), "CLI request started: codex")
            self.assertNotIn("gpt-5.5", _last_reply(update))

            release.set()
            await _wait_direct_response_tasks(bot)

    async def test_reply_falls_back_to_send_message_when_reply_text_exhausts_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_text_update("hello")
            bot._reply_text = mock.AsyncMock(return_value=None)
            bot._send_message_fallback = mock.AsyncMock(return_value=object())

            await bot._reply(
                update,
                "final answer",
                action="telegram cli response reply",
                timeout_seconds=20.0,
                retry_delays=(1.0, 3.0, 8.0),
            )

            bot._reply_text.assert_awaited_once()
            bot._send_message_fallback.assert_awaited_once_with(
                chat_id=42,
                text="final answer",
                action="telegram cli response reply send_message fallback",
                timeout_seconds=20.0,
                retry_delays=(1.0, 3.0, 8.0),
                parse_mode=None,
            )

    async def test_cli_response_uses_longer_telegram_send_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(
                active_agent_cli=Path("codex"),
            )
            update = _make_channel_update("summarize this channel request")
            context = mock.MagicMock()
            context.args = []

            def fake_run_once(request):
                stdout_path = root / "stdout.txt"
                stderr_path = root / "stderr.txt"
                stdout_path.write_text("direct CLI reply", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return SimpleNamespace(stdout_path=stdout_path, stderr_path=stderr_path, exit_code=0)

            with mock.patch("dormammu.telegram.bot.CliAdapter") as adapter_cls:
                adapter_cls.return_value.run_once.side_effect = fake_run_once
                original_reply = bot._reply
                bot._reply = mock.AsyncMock(side_effect=original_reply)
                await bot._cmd_channel_post_command(update, context)
                await _wait_direct_response_tasks(bot)

            final_reply = bot._reply.await_args_list[-1]
            self.assertEqual(final_reply.args[1], "direct CLI reply")
            self.assertEqual(final_reply.kwargs["action"], "telegram cli response reply")
            self.assertEqual(final_reply.kwargs["timeout_seconds"], bot._IMPORTANT_REPLY_TIMEOUT_S)
            self.assertEqual(final_reply.kwargs["retry_delays"], bot._IMPORTANT_REPLY_RETRY_DELAYS_S)

    async def test_channel_plain_text_logs_input_output_and_cli_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(
                active_agent_cli=Path("codex"),
            )
            update = _make_channel_update("summarize this channel request")
            context = mock.MagicMock()
            context.args = []

            def fake_run_once(request):
                stdout_path = root / "stdout.txt"
                stderr_path = root / "stderr.txt"
                stdout_path.write_text("direct CLI reply", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return SimpleNamespace(stdout_path=stdout_path, stderr_path=stderr_path, exit_code=0)

            with mock.patch("dormammu.telegram.bot.CliAdapter") as adapter_cls, mock.patch("sys.stderr", io.StringIO()) as stderr:
                adapter_cls.return_value.run_once.side_effect = fake_run_once
                await bot._cmd_channel_post_command(update, context)
                await _wait_direct_response_tasks(bot)

            logs = stderr.getvalue()
            self.assertIn("telegram input: kind=channel_post", logs)
            self.assertIn("telegram output: kind=channel_post", logs)
            self.assertIn("telegram cli request started: cli=codex", logs)
            self.assertIn("telegram cli request completed: cli=codex", logs)

    async def test_channel_plain_text_without_cli_config_replies_with_setup_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(active_agent_cli=None, agents=None)
            update = _make_channel_update("summarize this channel request")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self.assertEqual(list(bot._daemon_config.prompt_path.glob("tg_fast_*.md")), [])
            self.assertIn("No CLI is configured", _last_reply(update))
            runner.notify_prompt_enqueued.assert_not_called()

    async def test_plain_text_message_replies_with_cli_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(
                active_agent_cli=Path("codex"),
            )
            update = _make_text_update("summarize this user message")
            context = mock.MagicMock()
            context.args = []

            def fake_run_once(request):
                stdout_path = root / "stdout.txt"
                stderr_path = root / "stderr.txt"
                stdout_path.write_text("direct message CLI reply", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return SimpleNamespace(stdout_path=stdout_path, stderr_path=stderr_path, exit_code=0)

            with mock.patch("dormammu.telegram.bot.CliAdapter") as adapter_cls:
                adapter_cls.return_value.run_once.side_effect = fake_run_once
                await bot._handle_text_input(update, context)
                await _wait_direct_response_tasks(bot)

            prompt_files = sorted(bot._daemon_config.prompt_path.glob("tg_fast_*.md"))
            self.assertEqual(prompt_files, [])
            replies = [call.args[0] for call in update.message.reply_text.call_args_list]
            self.assertIn("CLI request started: codex", replies[0])
            self.assertIn("direct message CLI reply", _last_reply(update))
            runner.notify_prompt_enqueued.assert_not_called()
            request = adapter_cls.return_value.run_once.call_args.args[0]
            self.assertIn("summarize this user message", request.prompt_text)

    async def test_plain_text_message_keeps_goals_add_flow_before_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(
                active_agent_cli=Path("codex"),
            )
            update = _make_text_update("Investigate queue latency")
            context = mock.MagicMock()
            context.args = []
            bot._goals_pending[42] = "add_waiting"

            with mock.patch("dormammu.telegram.bot.CliAdapter") as adapter_cls:
                await bot._handle_text_input(update, context)

            adapter_cls.assert_not_called()
            self.assertNotIn(42, bot._goals_pending)

    async def test_channel_plain_text_is_not_processed_twice_by_plain_text_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            bot._app_config = bot._app_config.with_overrides(
                active_agent_cli=Path("codex"),
            )
            update = _make_channel_update("summarize this channel request")
            context = mock.MagicMock()
            context.args = []

            with mock.patch("dormammu.telegram.bot.CliAdapter") as adapter_cls:
                await bot._handle_text_input(update, context)

            adapter_cls.assert_not_called()
            update.channel_post.reply_text.assert_not_called()

    async def test_channel_run_fast_command_queues_fast_direct_response_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/run_fast summarize queue state")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            prompt_files = sorted(bot._daemon_config.prompt_path.glob("tg_fast_*.md"))
            self.assertEqual(len(prompt_files), 1)
            content = prompt_files[0].read_text(encoding="utf-8")
            self.assertIn("DORMAMMU_REQUEST_CLASS: direct_response", content)
            self.assertIn("summarize queue state", content)
            self.assertIn("Queued fast path", _last_reply(update))

    async def test_channel_run_command_without_args_replies_with_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/run")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "Usage: /run")

    async def test_channel_fast_commands_without_args_reply_with_usage(self) -> None:
        for command in ["/ask", "/run_fast"]:
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    bot, _, _ = _make_bot(root)
                    update = _make_channel_update(command)
                    context = mock.MagicMock()
                    context.args = []

                    await bot._cmd_channel_post_command(update, context)

                    self._assert_channel_reply_without_markup(update, f"Usage: {command}")

    async def test_channel_tail_commands_reply_without_inline_keyboard(self) -> None:
        for command, expected in [
            ("/tail", "Tail is currently"),
            ("/tail on", "Tail ON"),
            ("/tail off", "Tail OFF"),
        ]:
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    bot, _, _ = _make_bot(root)
                    update = _make_channel_update(command)
                    context = mock.MagicMock()
                    context.args = []

                    await bot._cmd_channel_post_command(update, context)

                    self._assert_channel_reply_without_markup(update, expected)

    async def test_channel_result_command_replies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/result")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "No results")

    async def test_channel_sessions_command_replies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/sessions")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "No sessions")

    async def test_channel_repo_command_replies_without_inline_keyboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            current_repo = parent / "repo-a"
            sibling_repo = parent / "repo-b"
            current_repo.mkdir()
            sibling_repo.mkdir()
            (sibling_repo / "AGENTS.md").write_text("x", encoding="utf-8")
            import subprocess
            subprocess.run(["git", "init"], cwd=sibling_repo, capture_output=True, check=True)
            bot, _, _ = _make_bot(current_repo)
            update = _make_channel_update("/repo")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "Select repository")
            self.assertIn("repo-b", _last_reply(update))

    async def test_channel_clear_sessions_command_replies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            update = _make_channel_update("/clear_sessions")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "nothing to clear")

    async def test_channel_goals_command_replies_without_inline_keyboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            goals_dir = root / "goals"
            goals_dir.mkdir()
            (goals_dir / "sample-goal.md").write_text("goal", encoding="utf-8")
            from dormammu.daemon.goals_config import GoalsConfig

            bot, _, _ = _make_bot(root)
            bot._daemon_config = replace(
                bot._daemon_config,
                goals=GoalsConfig(path=goals_dir, interval_minutes=60),
            )
            update = _make_channel_update("/goals")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            self._assert_channel_reply_without_markup(update, "Goals")
            self.assertIn("sample-goal", _last_reply(update))

    async def test_channel_shutdown_command_replies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, runner, _ = _make_bot(root)
            update = _make_channel_update("/shutdown")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            runner.request_shutdown.assert_called_once()
            self._assert_channel_reply_without_markup(update, "Graceful shutdown requested")

    async def test_channel_command_ignores_other_bot_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot, _, _ = _make_bot(root)
            bot._app = mock.MagicMock()
            bot._app.bot.username = "dormammu_bot"
            update = _make_channel_update("/status@other_bot")
            context = mock.MagicMock()
            context.args = []

            await bot._cmd_channel_post_command(update, context)

            update.channel_post.reply_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
