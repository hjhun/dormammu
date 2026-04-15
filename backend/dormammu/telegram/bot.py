from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)


def _md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV1."""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


if TYPE_CHECKING:
    from dormammu.config import AppConfig
    from dormammu.daemon.models import DaemonConfig
    from dormammu.daemon.runner import DaemonRunner
    from dormammu.telegram.config import TelegramConfig
    from dormammu.telegram.stream import TelegramProgressStream


_HELP_TEXT = (
    "🤖 *dormammu bot commands*\n\n"
    "📊 /status — daemon status and active prompt\n"
    r"▶️ /run \<prompt\> — queue a new prompt for execution" "\n"
    "📋 /queue — list pending prompts\n"
    r"📡 /tail \[on\|off\] — stream skill progress \(on: show skill banners \+ output digest\)" "\n"
    r"📜 /logs \[n\] — last N lines of progress log \(default 50\)" "\n"
    r"📄 /result \[name\] — last \(or named\) result file content" "\n"
    r"🕐 /history \[n\] — last N execution results with status \(default 10\)" "\n"
    "🗂️ /sessions — recent session list\n"
    r"🗂️ /repo \[path\] — switch working repo \(or pick from sibling list\)" "\n"
    r"🗑️ /clear\_sessions — delete all session data for the current repo" "\n"
    "🎯 /goals — list, add, or delete goal files\n"
    "🛑 /stop — send interrupt to the running prompt\n"
    "🔌 /shutdown — finish current prompt then stop the daemon\n"
    "❓ /help — this message"
)

# Patterns for parsing result markdown files in _send_history.
_HISTORY_STATUS_RE = re.compile(r"^- Status: `([^`]+)`", re.MULTILINE)
_HISTORY_STARTED_RE = re.compile(r"^- Started at: `([^`]+)`", re.MULTILINE)
_HISTORY_COMPLETED_RE = re.compile(r"^- Completed at: `([^`]+)`", re.MULTILINE)
_HISTORY_VERDICT_RE = re.compile(r"^- Supervisor verdict: `([^`]+)`", re.MULTILINE)

_MENU_KEYBOARD_BASE = [
    [
        {"text": "📊 Status", "callback_data": "status"},
        {"text": "📋 Queue", "callback_data": "queue"},
    ],
    # Row 1 placeholder — tail button is injected dynamically by _build_menu_keyboard.
    [
        {"text": "📜 Logs", "callback_data": "logs"},
        {"text": "🕐 History", "callback_data": "history"},
        {"text": "🗂️ Sessions", "callback_data": "sessions"},
    ],
    [
        {"text": "🗂️ Repo", "callback_data": "repo"},
        {"text": "🗑️ Clear Sessions", "callback_data": "clear_sessions"},
    ],
    [
        {"text": "🎯 Goals", "callback_data": "goals"},
    ],
    [
        {"text": "🛑 Stop", "callback_data": "stop"},
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
                    self._app.bot.send_message(chat_id=chat_id, text=message),
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
        event loop process incoming Telegram updates (e.g. /status, /stop)
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
                    await self._app.bot.send_message(chat_id=chat_id, text=text)
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

        self._app = Application.builder().token(self._config.bot_token).build()
        self._app.add_handler(CommandHandler("start", self._cmd_help))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("run", self._cmd_run))
        self._app.add_handler(CommandHandler("queue", self._cmd_queue))
        self._app.add_handler(CommandHandler("tail", self._cmd_tail))
        self._app.add_handler(CommandHandler("logs", self._cmd_logs))
        self._app.add_handler(CommandHandler("result", self._cmd_result))
        self._app.add_handler(CommandHandler("history", self._cmd_history))
        self._app.add_handler(CommandHandler("sessions", self._cmd_sessions))
        self._app.add_handler(CommandHandler("repo", self._cmd_repo))
        self._app.add_handler(CommandHandler("clear_sessions", self._cmd_clear_sessions))
        self._app.add_handler(CommandHandler("goals", self._cmd_goals))
        self._app.add_handler(CommandHandler("stop", self._cmd_stop))
        self._app.add_handler(CommandHandler("shutdown", self._cmd_shutdown))
        self._app.add_handler(CallbackQueryHandler(self._cmd_callback))
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

        async with self._app:
            await self._app.bot.set_my_commands([
                BotCommand("status", "📊 daemon status"),
                BotCommand("run", "▶️ run a prompt"),
                BotCommand("queue", "📋 pending prompts"),
                BotCommand("tail", "📡 stream skill progress (on/off)"),
                BotCommand("logs", "📜 recent logs"),
                BotCommand("result", "📄 last result"),
                BotCommand("history", "🕐 execution history"),
                BotCommand("sessions", "🗂️ session list"),
                BotCommand("repo", "🗂️ switch working repo"),
                BotCommand("clear_sessions", "🗑️ clear session data"),
                BotCommand("goals", "🎯 list/add/delete goals"),
                BotCommand("stop", "🛑 stop execution"),
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
            elif update.message:
                await update.message.reply_text("Access denied.")
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

    async def _cmd_help(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await update.message.reply_text(
            _HELP_TEXT,
            parse_mode="MarkdownV2",
            reply_markup=self._build_menu_markup(),
        )

    async def _reply(
        self,
        update: Any,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: Any = None,
    ) -> None:
        """Send a reply whether the update came from a message or a callback query."""
        kwargs: dict[str, Any] = {"parse_mode": parse_mode}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        if update.callback_query is not None:
            await update.callback_query.message.reply_text(text, **kwargs)
        elif update.message is not None:
            await update.message.reply_text(text, **kwargs)

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
        elif data == "logs":
            context.args = []
            await self._send_logs(update, context)
        elif data == "history":
            context.args = []
            await self._send_history(update, context)
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
        elif data == "stop":
            await self._send_stop(update, context)
        elif data == "shutdown":
            await self._send_shutdown(update, context)

    async def _cmd_status(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_status(update, context)

    async def _send_status(self, update: Any, context: Any) -> None:
        in_progress = list(self._runner.in_progress_snapshot())
        streaming_id = self._stream.streaming_chat_id
        lines = ["📊 *dormammu daemon status*"]
        if in_progress:
            lines.append("▶️ Active: " + ", ".join(_md(p.name) for p in in_progress))
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
        lines.append(f"📁 Repo: `{_md(str(self._app_config.repo_root))}`")
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
        await self._reply(update, f"▶️ Queued: `{prompt_path.name}`")

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
        lines = [f"📋 *Prompt queue ({len(items)})*"] + [f"• {name}" for name in items]
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
                f"📡 Tail is currently *{state}*.\n"
                "Use `/tail on` to start or `/tail off` to stop.",
                reply_markup=self._build_menu_markup(),
            )
            return
        if mode == "off":
            self._stream.disable_streaming()
            await self._reply(
                update,
                "📡 Tail *OFF* — streaming stopped.",
                reply_markup=self._build_menu_markup(),
            )
        else:
            # Any value other than "off" enables streaming.
            self._stream.enable_streaming(chat_id)
            await self._reply(
                update,
                "📡 Tail *ON* — streaming skill progress.\n"
                "Shows each skill as it starts, a digest of its output when it "
                "finishes, and supervisor verdicts.\n"
                "Use `/tail off` or tap the Tail button to stop.",
                reply_markup=self._build_menu_markup(),
            )

    async def _cmd_logs(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_logs(update, context)

    async def _send_logs(self, update: Any, context: Any) -> None:
        try:
            n = int(context.args[0]) if context.args else 50
            n = max(1, min(n, 200))
        except (ValueError, IndexError):
            await self._reply(update, "Usage: /logs [n]  — lines to show, 1–200")
            return
        progress_dir = self._daemon_config.result_path.parent / "progress"
        log_path: Path | None = None
        if progress_dir.exists():
            candidates = sorted(
                progress_dir.glob("*_progress.log"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                log_path = candidates[0]
        if log_path is None or not log_path.exists():
            await self._reply(update, "📜 No progress log available (run with --debug to enable).")
            return
        text = log_path.read_text(encoding="utf-8", errors="replace")
        tail = "\n".join(text.splitlines()[-n:])
        if not tail.strip():
            await self._reply(update, "📜 Log is empty.")
            return
        max_chars = 3800
        if len(tail) > max_chars:
            tail = "..." + tail[-max_chars:]
        await self._reply(update, f"```\n{tail}\n```")

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

    async def _cmd_history(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_history(update, context)

    async def _send_history(self, update: Any, context: Any) -> None:
        try:
            n = int(context.args[0]) if context.args else 10
            n = max(1, min(n, 50))
        except (ValueError, IndexError):
            await self._reply(update, "Usage: /history [n]  — entries to show, 1–50")
            return
        result_dir = self._daemon_config.result_path
        if not result_dir.exists():
            await self._reply(update, "🕐 No results directory found.")
            return
        candidates = sorted(
            result_dir.glob("*_RESULT.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:n]
        if not candidates:
            await self._reply(update, "🕐 No history found.")
            return

        _status_icons = {
            "done": "✅",
            "failed": "❌",
            "in_progress": "▶️",
            "error": "⚠️",
        }

        lines = [f"🕐 *Execution history (last {len(candidates)})*", ""]
        for path in reversed(candidates):  # oldest first for chronological readability
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            status_m = _HISTORY_STATUS_RE.search(content)
            started_m = _HISTORY_STARTED_RE.search(content)
            completed_m = _HISTORY_COMPLETED_RE.search(content)
            verdict_m = _HISTORY_VERDICT_RE.search(content)

            status = status_m.group(1) if status_m else "?"
            started = started_m.group(1) if started_m else "?"
            completed = completed_m.group(1) if completed_m else ""
            verdict = verdict_m.group(1) if verdict_m else ""

            # Strip _RESULT.md suffix to get the original prompt filename
            prompt_name = path.name
            if prompt_name.endswith("_RESULT.md"):
                prompt_name = prompt_name[: -len("_RESULT.md")]

            icon = _status_icons.get(status, "❓")
            entry = f"{icon} `{prompt_name}`"
            if verdict:
                entry += f"\n  Verdict: {verdict}"
            entry += f"\n  Started: {started}"
            if completed and completed != "not completed":
                entry += f" → {completed}"
            lines.append(entry)

        text = "\n".join(lines)
        max_chars = 3800
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…(truncated)"
        await self._reply(update, text)

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
        lines = [f"🗂️ *Recent sessions ({len(session_dirs)})*"] + [f"• {s.name}" for s in session_dirs]
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
                f"🗂️ Current repo: `{current}`\n"
                f"No sibling repos found under `{parent}`.\n"
                "Use `/repo <path>` to switch directly.",
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

        lines = [f"🗂️ *Select repository*", f"Current: `{current.name}`", ""]
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
            await self._reply(update, f"❌ Path not found: `{new_root}`")
            return
        if not any((new_root / marker).exists() for marker in REPO_MARKERS):
            await self._reply(
                update,
                f"⚠️ `{new_root.name}` does not look like a dormammu repo\n"
                "(missing AGENTS.md, .dev/, and pyproject.toml).",
            )
            return
        if new_root.resolve() == self._app_config.repo_root.resolve():
            await self._reply(update, f"🗂️ Already using repo `{new_root.name}`.")
            return

        in_progress = self._runner.in_progress_snapshot()
        warning = ""
        if in_progress:
            names = ", ".join(p.name for p in in_progress)
            warning = f"\n⚠️ A prompt is still running ({names}); change takes effect for the next prompt."

        try:
            new_config = AppConfig.load(repo_root=new_root)
        except Exception as exc:
            await self._reply(update, f"❌ Failed to load config for `{new_root.name}`: {exc}")
            return

        self._app_config = new_config
        self._runner.app_config = new_config
        self._runner.repository = StateRepository(new_config)
        _log.info("repo switched to %s", new_root)
        await self._reply(
            update,
            f"✅ Switched to repo: `{new_root}`{warning}",
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
                f"⚠️ Cleared with errors:\n```\n{err_text}\n```",
            )
        else:
            await self._reply(
                update,
                f"🗑️ Cleared {len(session_dirs)} session(s) from `{sessions_dir}`.",
            )

    async def _cmd_stop(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_stop(update, context)

    async def _send_stop(self, update: Any, context: Any) -> None:
        in_progress = list(self._runner.in_progress_snapshot())
        if not in_progress:
            await self._reply(update, "🛑 No active prompt to stop.")
            return
        names = ", ".join(_md(p.name) for p in in_progress)
        await self._reply(update, f"🛑 Sending interrupt to active prompt: {names}")
        os.kill(os.getpid(), signal.SIGINT)

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
        goals_cfg = getattr(self._daemon_config, "goals", None)
        return goals_cfg.path if goals_cfg is not None else None

    def _list_goal_files(self) -> list[Path]:
        path = self._goals_path()
        if path is None or not path.exists():
            return []
        return sorted(p for p in path.iterdir() if p.is_file() and p.suffix == ".md")

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
                "Add a `goals` section to your daemonize config.",
            )
            return

        files = self._list_goal_files()
        if not files:
            lines = ["🎯 *Goals* — no goal files yet."]
        else:
            lines = [f"🎯 *Goals ({len(files)})*"]
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
            "🎯 *Add goal*\n\nPlease type your goal content.\n"
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

            lines = ["🗑️ *Select goal to delete*"] + [
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
            target.unlink(missing_ok=True)
            await self._reply(update, f"🗑️ Deleted goal: `{target.stem}`")
        except OSError as exc:
            await self._reply(update, f"❌ Failed to delete `{target.name}`: {exc}")

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

        goals_path = self._goals_path()
        if goals_path is None:
            return

        text = (update.message.text or "").strip()
        if not text:
            await self._reply(update, "❌ Goal content cannot be empty.")
            return

        # Derive filename stem from the first line.
        import re as _re
        first_line = text.splitlines()[0].strip()
        stem = _re.sub(r"[^\w\s-]", "", first_line.lower())
        stem = _re.sub(r"[\s_]+", "-", stem).strip("-") or "goal"

        from datetime import datetime, timezone as _tz
        date_str = datetime.now(_tz.utc).strftime("%Y%m%d")
        filename = f"{date_str}_{stem}.md"
        dest = goals_path / filename

        try:
            goals_path.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
            await self._reply(update, f"✅ Goal saved: `{filename}`")
        except OSError as exc:
            await self._reply(update, f"❌ Failed to save goal: {exc}")
