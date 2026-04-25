from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from dormammu.operator_services import GoalsOperatorService

_log = logging.getLogger(__name__)


if TYPE_CHECKING:
    from dormammu.config import AppConfig
    from dormammu.daemon.models import DaemonConfig
    from dormammu.daemon.runner import DaemonRunner
    from dormammu.telegram.config import TelegramConfig
    from dormammu.telegram.stream import TelegramProgressStream


_HELP_TEXT = (
    "dormammu bot commands\n\n"
    "📊 /status — daemon status and active prompt\n"
    "▶️ /run <prompt> — queue a new prompt for execution\n"
    "📋 /queue — list pending prompts\n"
    "📡 /tail [on|off] — stream prompt and stage updates only\n"
    "📄 /result [name] — last (or named) result file content\n"
    "🗂️ /sessions — recent session list\n"
    "🗂️ /repo [path] — switch working repo (or pick from sibling list)\n"
    "🗑️ /clear_sessions — delete all session data for the current repo\n"
    "🎯 /goals — list, add, or delete goal files\n"
    "🔌 /shutdown — finish current prompt then stop the daemon\n"
    "❓ /help — this message"
)

_MENU_KEYBOARD_BASE = [
    [
        {"text": "📊 Status", "callback_data": "status"},
        {"text": "📋 Queue", "callback_data": "queue"},
    ],
    # Row 1 placeholder — tail button is injected dynamically by _build_menu_keyboard.
    [
        {"text": "🎯 Goals", "callback_data": "goals"},
        {"text": "🗂️ Repo", "callback_data": "repo"},
    ],
    [
        {"text": "🗑️ Clear Sessions", "callback_data": "clear_sessions"},
        {"text": "🔌 Shutdown", "callback_data": "shutdown"},
    ],
]


class TelegramBot:
    """Telegram bot that integrates with DaemonRunner.

    Runs in a background daemon thread with its own asyncio event loop.
    Command handlers can safely read daemon state and write prompt files.

    Known chat IDs (chats that have successfully issued at least one command)
    are persisted to ``<base_dev_dir>/telegram_known_chats.json`` so that
    startup broadcast messages can reach users even when ``allowed_chat_ids``
    is not configured.

    Outgoing progress messages are funnelled through an asyncio queue drained
    by ``_drain_send_queue`` at a maximum of ~20 messages/second (50 ms
    interval).  This keeps the bot's event loop responsive to incoming commands
    even during heavy log streaming, and stays safely under Telegram's 30 msg/s
    per-bot API limit.
    """

    # Minimum delay between consecutive outgoing sends (50 ms ≈ 20 msg/s).
    _SEND_INTERVAL_S: float = 0.05
    # Maximum queued outgoing messages; older items are dropped if exceeded.
    _SEND_QUEUE_MAXSIZE: int = 200
    # The python-telegram-bot defaults use a 5s connect timeout, which is
    # short enough to trip during transient network jitter on modest links.
    _REQUEST_CONNECT_TIMEOUT_S: float = 20.0
    _REQUEST_READ_TIMEOUT_S: float = 20.0
    _REQUEST_WRITE_TIMEOUT_S: float = 20.0
    _REQUEST_POOL_TIMEOUT_S: float = 5.0
    # Retry direct reply/send operations a small number of times before giving up.
    _SEND_RETRY_DELAYS_S: tuple[float, ...] = (1.0, 3.0)

    def __init__(
        self,
        telegram_config: TelegramConfig,
        *,
        daemon_config: DaemonConfig,
        app_config: AppConfig,
        stream: TelegramProgressStream,
        runner: DaemonRunner,
    ) -> None:
        self._config = telegram_config
        self._daemon_config = daemon_config
        self._app_config = app_config
        self._stream = stream
        self._runner = runner
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: Any = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._known_chats_path = app_config.base_dev_dir / "telegram_known_chats.json"
        self._known_chats: set[int] = self._load_known_chats()
        self._known_chats_lock = threading.Lock()
        self._startup_error: BaseException | None = None
        # Outgoing message queue — drained by _drain_send_queue at a controlled
        # rate so that heavy progress streaming cannot saturate the Telegram Bot
        # API (30 msg/s limit) and delay incoming command responses.
        self._send_queue: asyncio.Queue[tuple[int, str]] | None = None
        self._send_task: asyncio.Task[None] | None = None
        # Ephemeral list of repo paths shown in the last /repo inline keyboard.
        # Indexed by callback_data "repo_pick:<i>".  Lives only in the asyncio
        # event-loop thread so no lock is required.
        self._pending_repo_choices: list[Path] = []
        # Goals add/delete conversation state — keyed by chat_id.
        # "add_waiting" means the bot is waiting for the user to type goal content.
        # "del_waiting" means the bot is waiting for the user to pick a file to delete.
        self._goals_pending: dict[int, str] = {}
        # Cache of goal files shown in the last /goals_del inline keyboard.
        self._pending_goal_choices: list[Path] = []

    # ------------------------------------------------------------------
    # Known-chat registry (persisted to disk)
    # ------------------------------------------------------------------

    def _load_known_chats(self) -> set[int]:
        try:
            data = json.loads(self._known_chats_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {int(cid) for cid in data}
        except (OSError, ValueError, TypeError):
            pass
        return set()

    def _save_known_chats(self) -> None:
        try:
            self._known_chats_path.parent.mkdir(parents=True, exist_ok=True)
            self._known_chats_path.write_text(
                json.dumps(sorted(self._known_chats), indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _record_chat(self, chat_id: int) -> None:
        """Add chat_id to the known-chats registry and persist if new."""
        with self._known_chats_lock:
            if chat_id not in self._known_chats:
                self._known_chats.add(chat_id)
                self._save_known_chats()

    def _broadcast_targets(self) -> list[int]:
        """Return the list of chat IDs to broadcast to.

        If ``allowed_chat_ids`` is configured, use that list.
        Otherwise fall back to every chat that has ever used the bot.
        """
        if self._config.allowed_chat_ids:
            return list(self._config.allowed_chat_ids)
        with self._known_chats_lock:
            return list(self._known_chats)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start bot polling in a daemon thread. Blocks until the bot loop is ready.

        Raises the startup error if the bot thread fails to initialize.
        """
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="dormammu-telegram-bot",
        )
        self._thread.start()
        self._ready.wait(timeout=15)
        if self._startup_error is not None:
            raise self._startup_error
        self._stream.set_send_fn(self._send_message_sync)

    def notify_started(self) -> None:
        """Broadcast a startup message to all target chat IDs."""
        if self._loop is None or self._app is None:
            return
        targets = self._broadcast_targets()
        if not targets:
            return
        repo = str(self._app_config.repo_root)
        message = f"dormammu daemon started.\nRepo: {repo}"
        for chat_id in targets:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._perform_telegram_request(
                        lambda chat_id=chat_id: self._app.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                        ),
                        action=f"startup notification to chat {chat_id}",
                    ),
                    self._loop,
                )
                future.result(timeout=10)
            except Exception as exc:
                _log.warning("notify_started: failed to send startup message to chat %s: %s", chat_id, exc)

    def _send_message_sync(self, chat_id: int, text: str) -> None:
        """Thread-safe: enqueue a Telegram message from any thread.

        The message is placed into ``_send_queue`` via
        ``loop.call_soon_threadsafe`` so that the asyncio event loop drains it
        at a controlled rate (``_SEND_INTERVAL_S``).  This prevents heavy
        progress streaming from flooding the API or starving incoming command
        handlers.
        """
        if self._loop is None or self._send_queue is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._put_to_send_queue, chat_id, text)
        except Exception as exc:
            _log.debug("_send_message_sync: could not schedule message (loop closed?): %s", exc)

    def _put_to_send_queue(self, chat_id: int, text: str) -> None:
        """Called from within the event loop (via call_soon_threadsafe).

        Drops the message silently if the queue is full so that a burst of
        progress output cannot cause unbounded memory growth.
        """
        if self._send_queue is None:
            return
        try:
            self._send_queue.put_nowait((chat_id, text))
        except asyncio.QueueFull:
            _log.debug("_put_to_send_queue: outgoing queue full; dropping message to chat %s", chat_id)

    async def _drain_send_queue(self) -> None:
        """Background asyncio task: send queued messages at a controlled rate.

        Yielding ``asyncio.sleep(_SEND_INTERVAL_S)`` after every send lets the
        event loop process incoming Telegram updates (e.g. /status)
        between outgoing messages, keeping the bot responsive during long runs.
        """
        assert self._send_queue is not None
        while True:
            try:
                chat_id, text = await self._send_queue.get()
            except asyncio.CancelledError:
                break
            try:
                if self._app is not None:
                    await self._perform_telegram_request(
                        lambda chat_id=chat_id, text=text: self._app.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                        ),
                        action=f"queued Telegram send to chat {chat_id}",
                    )
            except Exception as exc:
                _log.warning("_drain_send_queue: send to chat %s failed: %s", chat_id, exc)
            finally:
                self._send_queue.task_done()
            # Yield control so incoming command handlers can run between sends.
            try:
                await asyncio.sleep(self._SEND_INTERVAL_S)
            except asyncio.CancelledError:
                break

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_run())
        except Exception as exc:
            if self._ready.is_set():
                raise  # runtime error after startup — let thread exception handler see it
            self._startup_error = exc
            self._ready.set()
        finally:
            self._loop.close()

    async def _async_run(self) -> None:
        try:
            from telegram.ext import Application, CommandHandler
        except ImportError:
            import sys

            print(
                "error: python-telegram-bot is not installed. "
                "Install it with: pip install 'dormammu[telegram]'",
                file=sys.stderr,
            )
            self._ready.set()
            return

        from telegram import BotCommand
        from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

        builder = (
            Application.builder()
            .token(self._config.bot_token)
            .connect_timeout(self._REQUEST_CONNECT_TIMEOUT_S)
            .read_timeout(self._REQUEST_READ_TIMEOUT_S)
            .write_timeout(self._REQUEST_WRITE_TIMEOUT_S)
            .pool_timeout(self._REQUEST_POOL_TIMEOUT_S)
            .get_updates_connect_timeout(self._REQUEST_CONNECT_TIMEOUT_S)
            .get_updates_read_timeout(self._REQUEST_READ_TIMEOUT_S)
            .get_updates_write_timeout(self._REQUEST_WRITE_TIMEOUT_S)
            .get_updates_pool_timeout(self._REQUEST_POOL_TIMEOUT_S)
        )
        self._app = builder.build()
        self._app.add_handler(CommandHandler("start", self._cmd_help))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("run", self._cmd_run))
        self._app.add_handler(CommandHandler("queue", self._cmd_queue))
        self._app.add_handler(CommandHandler("tail", self._cmd_tail))
        self._app.add_handler(CommandHandler("result", self._cmd_result))
        self._app.add_handler(CommandHandler("sessions", self._cmd_sessions))
        self._app.add_handler(CommandHandler("repo", self._cmd_repo))
        self._app.add_handler(CommandHandler("clear_sessions", self._cmd_clear_sessions))
        self._app.add_handler(CommandHandler("goals", self._cmd_goals))
        self._app.add_handler(CommandHandler("shutdown", self._cmd_shutdown))
        self._app.add_handler(CallbackQueryHandler(self._cmd_callback))
        self._app.add_handler(
            MessageHandler(
                filters.UpdateType.CHANNEL_POSTS & (filters.TEXT | filters.CAPTION),
                self._cmd_channel_post_command,
            )
        )
        # Record any incoming message so the sender is tracked for broadcasts.
        self._app.add_handler(
            MessageHandler(filters.ALL, self._track_chat),
            group=1,
        )
        # Handle plain text messages for goals_add conversation flow.
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_input),
            group=2,
        )
        self._app.add_error_handler(self._handle_application_error)

        async with self._app:
            await self._app.bot.set_my_commands([
                BotCommand("status", "📊 daemon status"),
                BotCommand("run", "▶️ run a prompt"),
                BotCommand("queue", "📋 pending prompts"),
                BotCommand("tail", "📡 prompt/stage updates (on/off)"),
                BotCommand("result", "📄 last result"),
                BotCommand("sessions", "🗂️ session list"),
                BotCommand("repo", "🗂️ switch working repo"),
                BotCommand("clear_sessions", "🗑️ clear session data"),
                BotCommand("goals", "🎯 list/add/delete goals"),
                BotCommand("shutdown", "🔌 graceful daemon shutdown"),
                BotCommand("help", "❓ help"),
            ])
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            # Start the rate-limited outgoing message drainer before signalling
            # readiness so that _send_message_sync can be called immediately.
            self._send_queue = asyncio.Queue(maxsize=self._SEND_QUEUE_MAXSIZE)
            self._send_task = asyncio.create_task(
                self._drain_send_queue(), name="dormammu-telegram-sender"
            )
            self._ready.set()  # signal successful startup
            try:
                await asyncio.Event().wait()
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
            finally:
                if self._send_task is not None:
                    self._send_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._send_task
                await self._app.updater.stop()
                await self._app.stop()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _is_allowed(self, chat_id: int) -> bool:
        if not self._config.allowed_chat_ids:
            return True
        return chat_id in self._config.allowed_chat_ids

    async def _guard(self, update: Any) -> bool:
        chat = update.effective_chat
        chat_id = chat.id if chat else None
        if chat_id is None or not self._is_allowed(chat_id):
            if update.callback_query is not None:
                await update.callback_query.answer("Access denied.", show_alert=True)
            else:
                message = self._target_message(update)
                if message is not None:
                    await self._reply_text(
                        message,
                        "Access denied.",
                        action="access denied reply",
                    )
            return False
        self._record_chat(chat_id)
        return True

    # ------------------------------------------------------------------
    # Chat tracker (group=1, runs after command handlers)
    # ------------------------------------------------------------------

    async def _track_chat(self, update: Any, context: Any) -> None:
        """Persist chat ID for every allowed incoming message."""
        chat = update.effective_chat
        if chat is not None and self._is_allowed(chat.id):
            self._record_chat(chat.id)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _target_message(self, update: Any) -> Any:
        if update.callback_query is not None:
            return update.callback_query.message
        message = getattr(update, "effective_message", None)
        if message is not None:
            return message
        if getattr(update, "message", None) is not None:
            return update.message
        return getattr(update, "channel_post", None)

    def _command_text(self, update: Any) -> str:
        message = self._target_message(update)
        if message is None:
            return ""
        return (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()

    def _parse_command(self, text: str) -> tuple[str, list[str]] | None:
        match = re.match(r"^/([A-Za-z0-9_]+)(?:@([A-Za-z0-9_]+))?(?:\s+(.*))?$", text)
        if match is None:
            return None
        command = match.group(1).lower()
        addressed_username = match.group(2)
        if addressed_username:
            bot_username = getattr(getattr(self._app, "bot", None), "username", None)
            if bot_username and addressed_username.lower() != str(bot_username).lower():
                return None
        arg_text = (match.group(3) or "").strip()
        args = arg_text.split() if arg_text else []
        return command, args

    async def _cmd_channel_post_command(self, update: Any, context: Any) -> None:
        parsed = self._parse_command(self._command_text(update))
        if parsed is None:
            return
        command, args = parsed
        handlers = {
            "start": self._cmd_help,
            "help": self._cmd_help,
            "status": self._cmd_status,
            "run": self._cmd_run,
            "queue": self._cmd_queue,
            "tail": self._cmd_tail,
            "result": self._cmd_result,
            "sessions": self._cmd_sessions,
            "repo": self._cmd_repo,
            "clear_sessions": self._cmd_clear_sessions,
            "goals": self._cmd_goals,
            "shutdown": self._cmd_shutdown,
        }
        handler = handlers.get(command)
        if handler is None:
            return
        previous_args = list(getattr(context, "args", ()))
        context.args = args
        try:
            await handler(update, context)
        finally:
            context.args = previous_args

    def _build_menu_keyboard(self) -> list[list[dict[str, str]]]:
        """Return the full menu layout with a dynamic tail-toggle row."""
        streaming = self._stream.streaming_chat_id is not None
        tail_row = [
            {
                "text": "📡 Tail: ON ✓" if streaming else "📡 Tail: OFF",
                "callback_data": "tail",
            }
        ]
        return [_MENU_KEYBOARD_BASE[0], tail_row] + list(_MENU_KEYBOARD_BASE[1:])

    def _build_menu_markup(self) -> Any:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = [
            [InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"]) for btn in row]
            for row in self._build_menu_keyboard()
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _is_channel_post_update(update: Any) -> bool:
        return getattr(update, "channel_post", None) is not None and getattr(update, "message", None) is None

    @staticmethod
    def _retry_delay_seconds(exc: BaseException, fallback: float) -> float:
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is None:
            return fallback
        if hasattr(retry_after, "total_seconds"):
            return max(0.0, float(retry_after.total_seconds()))
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            return fallback

    async def _perform_telegram_request(
        self,
        send: Callable[[], Awaitable[Any]],
        *,
        action: str,
    ) -> Any | None:
        try:
            from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
        except ImportError:
            return await send()

        max_attempts = len(self._SEND_RETRY_DELAYS_S) + 1
        last_exc: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await send()
            except BadRequest:
                raise
            except (TimedOut, NetworkError, RetryAfter) as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    break
                delay = self._retry_delay_seconds(exc, self._SEND_RETRY_DELAYS_S[attempt - 1])
                _log.warning(
                    "%s failed with transient Telegram network error (%s/%s): %s; retrying in %.1fs",
                    action,
                    attempt,
                    max_attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        _log.warning(
            "%s failed after %s attempt(s): %s",
            action,
            max_attempts,
            last_exc,
        )
        return None

    async def _reply_text(self, message: Any, text: str, *, action: str, **kwargs: Any) -> Any | None:
        try:
            return await self._perform_telegram_request(
                lambda: message.reply_text(text, **kwargs),
                action=action,
            )
        except Exception as exc:
            if "reply_markup" not in kwargs:
                raise
            try:
                from telegram.error import TelegramError
            except ImportError:
                raise
            if not isinstance(exc, TelegramError):
                raise
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop("reply_markup", None)
            _log.warning(
                "%s failed with Telegram reply markup error: %s; retrying without reply markup",
                action,
                exc,
            )
            return await self._perform_telegram_request(
                lambda: message.reply_text(text, **fallback_kwargs),
                action=f"{action} without reply markup",
            )

    async def _handle_application_error(self, update: object, context: Any) -> None:
        error = getattr(context, "error", None)
        if error is None:
            return
        try:
            from telegram.error import NetworkError, RetryAfter, TimedOut
        except ImportError:
            _log.error(
                "telegram update handler failed",
                exc_info=(type(error), error, error.__traceback__),
            )
            return
        if isinstance(error, (TimedOut, NetworkError, RetryAfter)):
            _log.warning("telegram update handler network error: %s", error)
            return
        _log.error(
            "telegram update handler failed",
            exc_info=(type(error), error, error.__traceback__),
        )

    async def _cmd_help(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._reply(
            update,
            _HELP_TEXT,
            reply_markup=None if self._is_channel_post_update(update) else self._build_menu_markup(),
        )

    async def _reply(
        self,
        update: Any,
        text: str,
        parse_mode: str | None = None,
        reply_markup: Any = None,
    ) -> None:
        """Send a reply whether the update came from a message or a callback query."""
        kwargs: dict[str, Any] = {}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        message = self._target_message(update)
        if message is not None:
            await self._reply_text(message, text, action="telegram command reply", **kwargs)

    async def _cmd_callback(self, update: Any, context: Any) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        if not await self._guard(update):
            return

        data = query.data
        if data == "status":
            await self._send_status(update, context)
        elif data == "queue":
            await self._send_queue(update, context)
        elif data == "tail":
            streaming = self._stream.streaming_chat_id is not None
            context.args = ["off"] if streaming else ["on"]
            await self._send_tail(update, context)
        elif data == "sessions":
            await self._send_sessions(update, context)
        elif data == "repo":
            context.args = []
            await self._send_repo(update, context)
        elif data == "clear_sessions":
            await self._send_clear_sessions(update, context)
        elif data.startswith("repo_pick:"):
            await self._handle_repo_pick(update, data[len("repo_pick:"):])
        elif data == "goals":
            await self._send_goals(update, context)
        elif data == "goals_add":
            await self._handle_goals_add_start(update, context)
        elif data.startswith("goals_del:"):
            await self._handle_goals_del_pick(update, data[len("goals_del:"):])
        elif data == "goals_del_cancel":
            chat_id = update.effective_chat.id
            self._goals_pending.pop(chat_id, None)
            await self._reply(update, "🎯 Goals deletion cancelled.")
        elif data == "shutdown":
            await self._send_shutdown(update, context)

    async def _cmd_status(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_status(update, context)

    async def _send_status(self, update: Any, context: Any) -> None:
        in_progress = list(self._runner.in_progress_snapshot())
        streaming_id = self._stream.streaming_chat_id
        lines = ["📊 dormammu daemon status"]
        if in_progress:
            lines.append("▶️ Active: " + ", ".join(p.name for p in in_progress))
        else:
            lines.append("💤 Active: idle")
        from dormammu.daemon.queue import is_prompt_candidate

        active_snapshot = self._runner.in_progress_snapshot()
        prompt_dir = self._daemon_config.prompt_path
        pending_count = 0
        if prompt_dir.exists():
            pending_count = sum(
                1
                for p in prompt_dir.iterdir()
                if is_prompt_candidate(p, self._daemon_config.queue) and p not in active_snapshot
            )
        lines.append(f"📋 Queued: {pending_count}")
        lines.append(f"📡 Streaming: {'on (chat ' + str(streaming_id) + ')' if streaming_id else 'off'}")
        lines.append(f"📁 Repo: {self._app_config.repo_root}")
        await self._reply(update, "\n".join(lines))

    async def _cmd_run(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        if not context.args:
            await self._reply(update, "Usage: /run <prompt text>")
            return
        prompt_text = " ".join(context.args)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        prompt_path = self._daemon_config.prompt_path / f"tg_{ts}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        await self._reply(update, f"▶️ Queued: {prompt_path.name}")

    async def _cmd_queue(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_queue(update, context)

    async def _send_queue(self, update: Any, context: Any) -> None:
        from dormammu.daemon.queue import is_prompt_candidate

        prompt_dir = self._daemon_config.prompt_path
        items: list[str] = []
        if prompt_dir.exists():
            items = [
                p.name
                for p in sorted(prompt_dir.iterdir())
                if is_prompt_candidate(p, self._daemon_config.queue)
            ]
        if not items:
            await self._reply(update, "📋 Prompt queue is empty.")
            return
        lines = [f"📋 Prompt queue ({len(items)})"] + [f"• {name}" for name in items]
        await self._reply(update, "\n".join(lines))

    async def _cmd_tail(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_tail(update, context)

    async def _send_tail(self, update: Any, context: Any) -> None:
        chat_id = update.effective_chat.id
        mode = context.args[0].lower() if context.args else ""
        if not mode:
            # No argument — show current status.
            streaming = self._stream.streaming_chat_id is not None
            state = "ON ✓" if streaming else "OFF"
            await self._reply(
                update,
                f"📡 Tail is currently {state}.\n"
                "Use /tail on to start or /tail off to stop.",
                reply_markup=self._build_menu_markup(),
            )
            return
        if mode == "off":
            self._stream.disable_streaming()
            await self._reply(
                update,
                "📡 Tail OFF — streaming stopped.",
                reply_markup=self._build_menu_markup(),
            )
        else:
            # Any value other than "off" enables streaming.
            self._stream.enable_streaming(chat_id)
            await self._reply(
                update,
                "📡 Tail ON — streaming prompt and stage updates.\n"
                "Shows the active prompt and the current stage only.\n"
                "Use /tail off or tap the Tail button to stop.",
                reply_markup=self._build_menu_markup(),
            )

    async def _cmd_result(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        result_dir = self._daemon_config.result_path
        if not result_dir.exists():
            await self._reply(update, "📄 No results directory found.")
            return
        if context.args:
            name = context.args[0]
            if not name.endswith(".md"):
                name += "_RESULT.md"
            result_path = result_dir / name
        else:
            candidates = sorted(
                result_dir.glob("*_RESULT.md"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                await self._reply(update, "📄 No results found.")
                return
            result_path = candidates[0]
        if not result_path.exists():
            await self._reply(update, f"📄 Result not found: {result_path.name}")
            return
        content = result_path.read_text(encoding="utf-8", errors="replace")
        max_chars = 3800
        if len(content) > max_chars:
            content = content[:max_chars] + "\n…(truncated)"
        await self._reply(update, f"📄 {result_path.name}\n\n{content}", parse_mode=None)

    async def _cmd_sessions(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_sessions(update, context)

    async def _send_sessions(self, update: Any, context: Any) -> None:
        sessions_dir = self._app_config.sessions_dir
        if not sessions_dir.exists():
            await self._reply(update, "🗂️ No sessions directory found.")
            return
        session_dirs = sorted(
            (p for p in sessions_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:10]
        if not session_dirs:
            await self._reply(update, "🗂️ No sessions found.")
            return
        lines = [f"🗂️ Recent sessions ({len(session_dirs)})"] + [f"• {s.name}" for s in session_dirs]
        await self._reply(update, "\n".join(lines))

    async def _cmd_repo(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_repo(update, context)

    async def _send_repo(self, update: Any, context: Any) -> None:
        """Show the current repo and allow switching to a sibling repo (or a direct path)."""
        from dormammu.config import AppConfig, REPO_MARKERS

        if context.args:
            # Direct path provided: switch immediately.
            raw = " ".join(context.args)
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = (self._app_config.repo_root / candidate).resolve()
            await self._apply_repo_change(update, candidate)
            return

        # Scan sibling directories (parent of current repo root).
        parent = self._app_config.repo_root.parent
        candidates: list[Path] = []
        if parent.exists():
            for d in sorted(parent.iterdir()):
                if d.is_dir() and any((d / marker).exists() for marker in REPO_MARKERS):
                    candidates.append(d)

        current = self._app_config.repo_root
        other_candidates = [p for p in candidates if p.resolve() != current.resolve()]
        if not candidates or not other_candidates:
            await self._reply(
                update,
                f"🗂️ Current repo: {current}\n"
                f"No sibling repos found under {parent}.\n"
                "Use /repo <path> to switch directly.",
            )
            return

        self._pending_repo_choices = candidates

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = []
            for i, path in enumerate(candidates):
                label = f"✅ {path.name}" if path == current else path.name
                keyboard.append([InlineKeyboardButton(label, callback_data=f"repo_pick:{i}")])
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="repo_pick:cancel")])
            reply_markup = InlineKeyboardMarkup(keyboard)
        except ImportError:
            reply_markup = None

        lines = ["🗂️ Select repository", f"Current: {current.name}", ""]
        for i, path in enumerate(candidates):
            marker = "✅" if path == current else "  "
            lines.append(f"{marker} {i}. {path.name}")
        if reply_markup is None:
            lines.append("")
            lines.append("Reply with /repo <path> to switch.")

        await self._reply(
            update,
            "\n".join(lines),
            reply_markup=reply_markup,
        )

    async def _handle_repo_pick(self, update: Any, idx_str: str) -> None:
        """Handle a repo_pick:<i> callback from the inline keyboard."""
        if idx_str == "cancel":
            await self._reply(update, "🗂️ Repo switch cancelled.")
            return
        try:
            idx = int(idx_str)
        except ValueError:
            await self._reply(update, "❌ Invalid repo selection.")
            return
        if idx < 0 or idx >= len(self._pending_repo_choices):
            await self._reply(update, "❌ Selection expired — please run /repo again.")
            return
        await self._apply_repo_change(update, self._pending_repo_choices[idx])

    async def _apply_repo_change(self, update: Any, new_root: Path) -> None:
        """Validate new_root and hot-swap the runner's app_config."""
        from dormammu.config import AppConfig, REPO_MARKERS
        from dormammu.state import StateRepository

        if not new_root.exists() or not new_root.is_dir():
            await self._reply(update, f"❌ Path not found: {new_root}")
            return
        if not any((new_root / marker).exists() for marker in REPO_MARKERS):
            await self._reply(
                update,
                f"⚠️ {new_root.name} does not look like a dormammu repo\n"
                "(missing AGENTS.md, .dev/, and pyproject.toml).",
            )
            return
        if new_root.resolve() == self._app_config.repo_root.resolve():
            await self._reply(update, f"🗂️ Already using repo {new_root.name}.")
            return

        in_progress = self._runner.in_progress_snapshot()
        warning = ""
        if in_progress:
            names = ", ".join(p.name for p in in_progress)
            warning = f"\n⚠️ A prompt is still running ({names}); change takes effect for the next prompt."

        try:
            new_config = AppConfig.load(repo_root=new_root)
        except Exception as exc:
            await self._reply(update, f"❌ Failed to load config for {new_root.name}: {exc}")
            return

        self._app_config = new_config
        self._runner.app_config = new_config
        self._runner.repository = StateRepository(new_config)
        _log.info("repo switched to %s", new_root)
        await self._reply(
            update,
            f"✅ Switched to repo: {new_root}{warning}",
        )

    async def _cmd_clear_sessions(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_clear_sessions(update, context)

    async def _send_clear_sessions(self, update: Any, context: Any) -> None:
        """Delete all session subdirectories under the current sessions directory."""
        import shutil

        sessions_dir = self._app_config.sessions_dir
        if not sessions_dir.exists():
            await self._reply(update, "🗑️ No sessions directory found — nothing to clear.")
            return
        session_dirs = [p for p in sessions_dir.iterdir() if p.is_dir()]
        if not session_dirs:
            await self._reply(update, "🗑️ Sessions directory is already empty.")
            return
        errors: list[str] = []
        for d in session_dirs:
            try:
                shutil.rmtree(d)
            except OSError as exc:
                errors.append(f"{d.name}: {exc}")
        if errors:
            err_text = "\n".join(errors)
            await self._reply(
                update,
                f"⚠️ Cleared with errors:\n{err_text}",
            )
        else:
            await self._reply(
                update,
                f"🗑️ Cleared {len(session_dirs)} session(s) from {sessions_dir}.",
            )

    async def _cmd_shutdown(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_shutdown(update, context)

    async def _send_shutdown(self, update: Any, context: Any) -> None:
        """Request a graceful daemon shutdown after the current prompt finishes."""
        if self._runner.shutdown_requested:
            await self._reply(update, "🔌 Shutdown already requested — waiting for current prompt to finish.")
            return
        self._runner.request_shutdown()
        in_progress = list(self._runner.in_progress_snapshot())
        if in_progress:
            names = ", ".join(p.name for p in in_progress)
            await self._reply(
                update,
                f"🔌 Graceful shutdown requested.\nWaiting for active prompt to finish: {names}"
            )
        else:
            await self._reply(update, "🔌 Graceful shutdown requested. Daemon will stop shortly.")

    # ------------------------------------------------------------------
    # Goals commands
    # ------------------------------------------------------------------

    def _goals_path(self) -> Path | None:
        """Return the configured goals directory, or None if not configured."""
        return GoalsOperatorService(self._daemon_config).goals_path

    def _list_goal_files(self) -> list[Path]:
        return list(GoalsOperatorService(self._daemon_config).list_goals())

    async def _cmd_goals(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_goals(update, context)

    async def _send_goals(self, update: Any, context: Any) -> None:
        goals_path = self._goals_path()
        if goals_path is None:
            await self._reply(
                update,
                "🎯 Goals are not configured.\n"
                "Add a goals section to your daemonize config.",
            )
            return

        files = self._list_goal_files()
        if not files:
            lines = ["🎯 Goals — no goal files yet."]
        else:
            lines = [f"🎯 Goals ({len(files)})"]
            for f in files:
                lines.append(f"• {f.stem}")

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = [
                [
                    InlineKeyboardButton("➕ Add goal", callback_data="goals_add"),
                    InlineKeyboardButton("🗑️ Delete goal", callback_data="goals_del:list"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        except ImportError:
            reply_markup = None

        await self._reply(update, "\n".join(lines), reply_markup=reply_markup)

    async def _handle_goals_add_start(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        if self._goals_path() is None:
            await self._reply(update, "🎯 Goals are not configured.")
            return
        chat_id = update.effective_chat.id
        self._goals_pending[chat_id] = "add_waiting"
        await self._reply(
            update,
            "🎯 Add goal\n\nPlease type your goal content.\n"
            "The first line will be used as the filename stem.",
        )

    async def _handle_goals_del_pick(self, update: Any, idx_str: str) -> None:
        if not await self._guard(update):
            return
        goals_path = self._goals_path()
        if goals_path is None:
            await self._reply(update, "🎯 Goals are not configured.")
            return

        if idx_str == "list":
            files = self._list_goal_files()
            if not files:
                await self._reply(update, "🎯 No goal files to delete.")
                return
            self._pending_goal_choices = files
            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = [
                    [InlineKeyboardButton(f.stem, callback_data=f"goals_del:{i}")]
                    for i, f in enumerate(files)
                ]
                keyboard.append(
                    [InlineKeyboardButton("❌ Cancel", callback_data="goals_del_cancel")]
                )
                reply_markup = InlineKeyboardMarkup(keyboard)
            except ImportError:
                reply_markup = None

            lines = ["🗑️ Select goal to delete"] + [
                f"{i}. {f.stem}" for i, f in enumerate(files)
            ]
            await self._reply(update, "\n".join(lines), reply_markup=reply_markup)
            return

        # Numeric index — delete the selected file.
        try:
            idx = int(idx_str)
        except ValueError:
            await self._reply(update, "❌ Invalid selection.")
            return
        if idx < 0 or idx >= len(self._pending_goal_choices):
            await self._reply(update, "❌ Selection expired — please run /goals again.")
            return

        target = self._pending_goal_choices[idx]
        self._pending_goal_choices = []
        try:
            GoalsOperatorService(self._daemon_config).delete_goal(target)
            await self._reply(update, f"🗑️ Deleted goal: {target.stem}")
        except OSError as exc:
            await self._reply(update, f"❌ Failed to delete {target.name}: {exc}")

    async def _handle_text_input(self, update: Any, context: Any) -> None:
        """Process free-text input during active conversation flows (e.g. goals_add)."""
        chat = update.effective_chat
        if chat is None:
            return
        chat_id = chat.id
        if not self._is_allowed(chat_id):
            return

        pending = self._goals_pending.get(chat_id)
        if pending == "add_waiting":
            await self._handle_goals_add_content(update, context)

    async def _handle_goals_add_content(self, update: Any, context: Any) -> None:
        chat_id = update.effective_chat.id
        self._goals_pending.pop(chat_id, None)

        service = GoalsOperatorService(self._daemon_config)
        if service.goals_path is None:
            return

        text = self._command_text(update)
        if not text:
            await self._reply(update, "❌ Goal content cannot be empty.")
            return

        try:
            dest = service.save_goal(text)
            await self._reply(update, f"✅ Goal saved: {dest.name}")
        except (OSError, RuntimeError) as exc:
            await self._reply(update, f"❌ Failed to save goal: {exc}")
