from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

telegram_error = pytest.importorskip("telegram.error")
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
    assert delays == [bot._SEND_RETRY_DELAYS_S[0]]


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
    message.reply_text = AsyncMock(side_effect=[TimedOut("connect timed out")] * 3)
    update = _make_update(message)

    async def _fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(telegram_bot_module.asyncio, "sleep", _fake_sleep)

    with caplog.at_level(logging.WARNING):
        _run(bot._reply(update, "hello"))

    assert message.reply_text.await_count == 3
    assert "telegram command reply failed after 3 attempt(s)" in caplog.text


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
