from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

telegram_error = pytest.importorskip("telegram.error")
BadRequest = telegram_error.BadRequest
TimedOut = telegram_error.TimedOut

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.telegram import bot as telegram_bot_module
from dormammu.telegram.bot import TelegramBot


def _run(coro: object) -> object:
    return asyncio.run(coro)


def _make_bot() -> TelegramBot:
    return object.__new__(TelegramBot)


def _make_update(message: MagicMock) -> MagicMock:
    update = MagicMock()
    update.callback_query = None
    update.effective_message = message
    update.message = message
    return update


def _make_channel_update(text: str, chat_id: int = 42) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.caption = None
    message.reply_text = AsyncMock(return_value=None)
    update = MagicMock()
    update.callback_query = None
    update.effective_chat.id = chat_id
    update.message = None
    update.channel_post = message
    update.effective_message = message
    return update


def test_reply_retries_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _make_bot()
    message = MagicMock()
    message.reply_text = AsyncMock(side_effect=[TimedOut("connect timed out"), None])
    update = _make_update(message)
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(telegram_bot_module.asyncio, "sleep", _fake_sleep)

    _run(bot._reply(update, "hello"))

    assert message.reply_text.await_count == 2
    assert delays == [bot._COMMAND_REPLY_RETRY_DELAYS_S[0]]


def test_reply_uses_short_command_timeouts() -> None:
    bot = _make_bot()
    message = MagicMock()
    message.reply_text = AsyncMock(return_value=None)
    update = _make_update(message)

    _run(bot._reply(update, "hello"))

    _args, kwargs = message.reply_text.await_args
    assert kwargs["connect_timeout"] == bot._COMMAND_REPLY_TIMEOUT_S
    assert kwargs["read_timeout"] == bot._COMMAND_REPLY_TIMEOUT_S
    assert kwargs["write_timeout"] == bot._COMMAND_REPLY_TIMEOUT_S
    assert kwargs["pool_timeout"] == min(
        bot._REQUEST_POOL_TIMEOUT_S,
        bot._COMMAND_REPLY_TIMEOUT_S,
    )


def test_reply_omits_parse_mode_when_none() -> None:
    bot = _make_bot()
    message = MagicMock()
    message.reply_text = AsyncMock(return_value=None)
    update = _make_update(message)

    _run(bot._reply(update, "hello"))

    _args, kwargs = message.reply_text.await_args
    assert kwargs.get("parse_mode") is None
    assert "parse_mode" not in kwargs


def test_reply_swallows_transient_timeout_after_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = _make_bot()
    message = MagicMock()
    message.reply_text = AsyncMock(side_effect=[TimedOut("connect timed out")] * 2)
    update = _make_update(message)

    async def _fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(telegram_bot_module.asyncio, "sleep", _fake_sleep)

    with caplog.at_level(logging.WARNING):
        _run(bot._reply(update, "hello"))

    assert message.reply_text.await_count == 2
    assert "telegram command reply failed after 2 attempt(s)" in caplog.text


def test_reply_retries_without_markup_after_telegram_markup_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = _make_bot()
    message = MagicMock()
    message.reply_text = AsyncMock(side_effect=[BadRequest("button data invalid"), None])
    update = _make_update(message)
    reply_markup = object()

    with caplog.at_level(logging.WARNING):
        _run(bot._reply(update, "hello", reply_markup=reply_markup))

    assert message.reply_text.await_count == 2
    first = message.reply_text.await_args_list[0]
    second = message.reply_text.await_args_list[1]
    assert first.kwargs["reply_markup"] is reply_markup
    assert "reply_markup" not in second.kwargs
    assert "retrying without reply markup" in caplog.text


def test_reply_raises_non_network_errors() -> None:
    bot = _make_bot()
    message = MagicMock()
    message.reply_text = AsyncMock(side_effect=RuntimeError("boom"))
    update = _make_update(message)

    with pytest.raises(RuntimeError, match="boom"):
        _run(bot._reply(update, "hello"))


def test_application_error_handler_logs_transient_network_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = _make_bot()
    context = MagicMock()
    context.error = TimedOut("connect timed out")

    with caplog.at_level(logging.WARNING):
        _run(bot._handle_application_error(object(), context))

    assert "telegram update handler network error" in caplog.text


def test_channel_post_command_logs_input_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bot = _make_bot()
    update = _make_channel_update("/unknown hello")
    context = MagicMock()
    context.args = []

    _run(bot._cmd_channel_post_command(update, context))

    assert (
        "telegram channel input: chat_id=42 text=/unknown hello"
        in capsys.readouterr().err
    )
    update.channel_post.reply_text.assert_not_awaited()


def test_channel_post_reply_logs_output_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bot = _make_bot()
    update = _make_channel_update("/status")

    _run(bot._reply(update, "status line 1\nstatus line 2"))

    assert (
        "telegram channel output: chat_id=42 text=status line 1\\nstatus line 2"
        in capsys.readouterr().err
    )
    update.channel_post.reply_text.assert_awaited_once()


def test_notify_started_queues_broadcasts_without_blocking_on_futures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _make_bot()
    bot._loop = MagicMock()
    bot._app = MagicMock()
    bot._outgoing_queue = MagicMock()
    bot._app_config = MagicMock()
    bot._app_config.repo_root = Path("/repo")
    bot._broadcast_targets = MagicMock(return_value=[1, 2])
    bot._send_message_sync = MagicMock()
    run_threadsafe = MagicMock()
    monkeypatch.setattr(telegram_bot_module.asyncio, "run_coroutine_threadsafe", run_threadsafe)

    bot.notify_started()

    assert bot._send_message_sync.call_count == 2
    run_threadsafe.assert_not_called()


def test_telegram_application_enables_limited_concurrent_updates() -> None:
    source = inspect.getsource(TelegramBot._async_run)

    assert ".concurrent_updates(self._CONCURRENT_UPDATES)" in source


def test_telegram_polling_explicitly_subscribes_to_channel_posts() -> None:
    source = inspect.getsource(TelegramBot._async_run)

    assert "allowed_updates=list(self._ALLOWED_UPDATES)" in source
    assert '"channel_post"' in inspect.getsource(TelegramBot)


def test_telegram_polling_uses_short_long_poll_timeout() -> None:
    source = inspect.getsource(TelegramBot._async_run)

    assert "timeout=self._GET_UPDATES_POLL_TIMEOUT_S" in source
    assert TelegramBot._GET_UPDATES_POLL_TIMEOUT_S == 1
