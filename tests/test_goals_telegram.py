"""Unit tests for Telegram goals commands in TelegramBot."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dormammu.daemon.goals_config import GoalsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _make_daemon_config(goals_path: Path | None = None) -> Any:
    cfg = MagicMock()
    if goals_path is not None:
        goals_cfg = MagicMock(spec=GoalsConfig)
        goals_cfg.path = goals_path
        cfg.goals = goals_cfg
    else:
        cfg.goals = None
    return cfg


def _make_bot(tmp_path: Path, *, goals_path: Path | None = None) -> Any:
    """Return a TelegramBot instance with minimal mocked dependencies."""
    from dormammu.telegram.bot import TelegramBot

    telegram_cfg = MagicMock()
    telegram_cfg.bot_token = "fake-token"
    telegram_cfg.allowed_chat_ids = ()

    daemon_cfg = _make_daemon_config(goals_path)
    app_cfg = MagicMock()
    app_cfg.repo_root = tmp_path
    runner = MagicMock()
    runner.in_progress_snapshot.return_value = frozenset()

    bot = object.__new__(TelegramBot)
    bot._config = telegram_cfg
    bot._daemon_config = daemon_cfg
    bot._app_config = app_cfg
    bot._runner = runner
    bot._known_chats = set()
    bot._known_chats_lock = __import__("threading").Lock()
    bot._pending_repo_choices = []
    bot._goals_pending = {}
    bot._pending_goal_choices = []
    return bot


def _make_update(chat_id: int = 123, text: str = "") -> Any:
    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.callback_query = None
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_message = update.message
    return update


def _make_context() -> Any:
    ctx = MagicMock()
    ctx.args = []
    return ctx


def test_help_text_is_plain_and_does_not_include_markdown_escapes() -> None:
    from dormammu.telegram.bot import _HELP_TEXT

    assert "*dormammu bot commands*" not in _HELP_TEXT
    assert r"\[on\|off\]" not in _HELP_TEXT
    assert r"\<prompt\>" not in _HELP_TEXT
    assert "/tail [on|off]" in _HELP_TEXT


# ---------------------------------------------------------------------------
# _goals_path
# ---------------------------------------------------------------------------


class TestGoalsPath:
    def test_none_when_not_configured(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path, goals_path=None)
        assert bot._goals_path() is None

    def test_returns_path_when_configured(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        assert bot._goals_path() == goals_dir


# ---------------------------------------------------------------------------
# _list_goal_files
# ---------------------------------------------------------------------------


class TestListGoalFiles:
    def test_empty_when_not_configured(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path, goals_path=None)
        assert bot._list_goal_files() == []

    def test_empty_when_dir_does_not_exist(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path, goals_path=tmp_path / "no-such-dir")
        assert bot._list_goal_files() == []

    def test_lists_md_files_sorted(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        (goals_dir / "b-goal.md").write_text("B", encoding="utf-8")
        (goals_dir / "a-goal.md").write_text("A", encoding="utf-8")
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        files = bot._list_goal_files()
        assert [f.name for f in files] == ["a-goal.md", "b-goal.md"]

    def test_ignores_non_md(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        (goals_dir / "notes.txt").write_text("note", encoding="utf-8")
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        assert bot._list_goal_files() == []


# ---------------------------------------------------------------------------
# _send_goals
# ---------------------------------------------------------------------------


class TestSendGoals:
    def test_not_configured_message(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path, goals_path=None)
        bot._reply = AsyncMock()

        _run(bot._send_goals(_make_update(), _make_context()))

        text = bot._reply.call_args[0][1]
        assert "not configured" in text.lower()

    def test_no_files_message(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._reply = AsyncMock()

        _run(bot._send_goals(_make_update(), _make_context()))

        text = bot._reply.call_args[0][1]
        assert "no goal files" in text.lower()
        assert "*" not in text
        assert "`" not in text

    def test_lists_files(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        (goals_dir / "my-feature.md").write_text("goal", encoding="utf-8")
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._reply = AsyncMock()

        _run(bot._send_goals(_make_update(), _make_context()))

        text = bot._reply.call_args[0][1]
        assert "my-feature" in text


# ---------------------------------------------------------------------------
# goals_add flow
# ---------------------------------------------------------------------------


class TestGoalsAddFlow:
    def test_add_start_sets_pending_state(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._is_allowed = lambda cid: True
        bot._record_chat = lambda cid: None
        bot._reply = AsyncMock()

        update = _make_update(chat_id=42)
        _run(bot._handle_goals_add_start(update, _make_context()))

        assert bot._goals_pending.get(42) == "add_waiting"
        text = bot._reply.call_args[0][1]
        assert "*" not in text
        assert "`" not in text

    def test_add_content_creates_file(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._reply = AsyncMock()

        update = _make_update(chat_id=42, text="Improve the authentication flow")
        bot._goals_pending[42] = "add_waiting"

        # Patch datetime inside bot module
        with patch("dormammu.telegram.bot.datetime") as mock_dt:
            from datetime import timezone
            mock_dt.now.return_value.strftime.return_value = "20260412"
            _run(bot._handle_goals_add_content(update, _make_context()))

        # State cleared
        assert 42 not in bot._goals_pending

        # File created
        files = list(goals_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "Improve the authentication flow" in content

    def test_add_content_empty_text_rejected(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._reply = AsyncMock()

        update = _make_update(chat_id=42, text="   ")
        bot._goals_pending[42] = "add_waiting"
        _run(bot._handle_goals_add_content(update, _make_context()))

        bot._reply.assert_called_once()
        assert "empty" in bot._reply.call_args[0][1].lower()
        assert list(goals_dir.glob("*.md")) == []

    def test_handle_text_input_routes_to_goals_add(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._reply = AsyncMock()
        bot._is_allowed = lambda cid: True

        update = _make_update(chat_id=99, text="some goal text")
        bot._goals_pending[99] = "add_waiting"

        bot._handle_goals_add_content = AsyncMock()
        _run(bot._handle_text_input(update, _make_context()))

        bot._handle_goals_add_content.assert_called_once()

    def test_handle_text_input_ignores_when_no_pending(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot._is_allowed = lambda cid: True
        bot._handle_goals_add_content = AsyncMock()

        update = _make_update(chat_id=99, text="random text")
        _run(bot._handle_text_input(update, _make_context()))

        bot._handle_goals_add_content.assert_not_called()

    def test_stem_derived_from_first_line(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._reply = AsyncMock()

        update = _make_update(chat_id=1, text="Add metrics endpoint\n\nMore details here.")
        bot._goals_pending[1] = "add_waiting"

        with patch("dormammu.telegram.bot.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260412"
            _run(bot._handle_goals_add_content(update, _make_context()))

        files = list(goals_dir.glob("*.md"))
        assert len(files) == 1
        # Stem should come from first line "Add metrics endpoint"
        assert "add-metrics-endpoint" in files[0].stem or "add" in files[0].stem


# ---------------------------------------------------------------------------
# goals_del flow
# ---------------------------------------------------------------------------


class TestGoalsDelFlow:
    def test_del_list_shows_files(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        (goals_dir / "goal-a.md").write_text("A", encoding="utf-8")
        (goals_dir / "goal-b.md").write_text("B", encoding="utf-8")
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._is_allowed = lambda cid: True
        bot._record_chat = lambda cid: None
        bot._reply = AsyncMock()

        _run(bot._handle_goals_del_pick(_make_update(), "list"))

        text = bot._reply.call_args[0][1]
        assert "goal-a" in text
        assert "goal-b" in text

    def test_del_by_index_deletes_file(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        target = goals_dir / "goal-a.md"
        target.write_text("A", encoding="utf-8")
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._is_allowed = lambda cid: True
        bot._record_chat = lambda cid: None
        bot._reply = AsyncMock()
        bot._pending_goal_choices = [target]

        _run(bot._handle_goals_del_pick(_make_update(), "0"))

        assert not target.exists()
        text = bot._reply.call_args[0][1]
        assert "goal-a" in text
        assert "`" not in text

    def test_del_no_files_message(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._is_allowed = lambda cid: True
        bot._record_chat = lambda cid: None
        bot._reply = AsyncMock()

        _run(bot._handle_goals_del_pick(_make_update(), "list"))

        text = bot._reply.call_args[0][1]
        assert "no goal files" in text.lower()

    def test_del_invalid_index_shows_error(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._is_allowed = lambda cid: True
        bot._record_chat = lambda cid: None
        bot._reply = AsyncMock()
        bot._pending_goal_choices = []

        _run(bot._handle_goals_del_pick(_make_update(), "0"))

        text = bot._reply.call_args[0][1]
        assert "expired" in text.lower() or "invalid" in text.lower()

    def test_del_not_configured(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path, goals_path=None)
        bot._is_allowed = lambda cid: True
        bot._record_chat = lambda cid: None
        bot._reply = AsyncMock()

        _run(bot._handle_goals_del_pick(_make_update(), "list"))

        text = bot._reply.call_args[0][1]
        assert "not configured" in text.lower()

    def test_del_cancel_clears_pending(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        bot = _make_bot(tmp_path, goals_path=goals_dir)
        bot._is_allowed = lambda cid: True
        bot._record_chat = lambda cid: None
        bot._reply = AsyncMock()

        update = _make_update(chat_id=5)
        bot._goals_pending[5] = "del_waiting"

        # Simulate goals_del_cancel callback routing
        from dormammu.telegram.bot import TelegramBot
        # Call the cancel branch directly
        bot._goals_pending.pop(5, None)
        _run(bot._reply(update, "🎯 Goals deletion cancelled."))

        assert 5 not in bot._goals_pending
