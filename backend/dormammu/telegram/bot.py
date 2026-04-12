from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    r"📡 /tail \[on\|off\|dashboard\] — stream output \(dashboard: plan \+ dashboard info per loop\)" "\n"
    r"📜 /logs \[n\] — last N lines of progress log \(default 50\)" "\n"
    r"📄 /result \[name\] — last \(or named\) result file content" "\n"
    "🗂️ /sessions — recent session list\n"
    "🛑 /stop — send interrupt to the running prompt\n"
    "❓ /help — this message"
)

_MENU_KEYBOARD = [
    [
        {"text": "📊 Status", "callback_data": "status"},
        {"text": "📋 Queue", "callback_data": "queue"},
    ],
    [
        {"text": "📡 Tail on", "callback_data": "tail_on"},
        {"text": "📡 Tail dashboard", "callback_data": "tail_dashboard"},
        {"text": "📡 Tail off", "callback_data": "tail_off"},
    ],
    [
        {"text": "📜 Logs", "callback_data": "logs"},
        {"text": "🗂️ Sessions", "callback_data": "sessions"},
    ],
    [
        {"text": "🛑 Stop", "callback_data": "stop"},
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
            except Exception:
                pass

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
        except Exception:
            pass

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
            pass  # shed load rather than block

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
            except Exception:
                pass
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
        self._app.add_handler(CommandHandler("sessions", self._cmd_sessions))
        self._app.add_handler(CommandHandler("stop", self._cmd_stop))
        self._app.add_handler(CallbackQueryHandler(self._cmd_callback))
        # Record any incoming message so the sender is tracked for broadcasts.
        self._app.add_handler(
            MessageHandler(filters.ALL, self._track_chat),
            group=1,
        )

        async with self._app:
            await self._app.bot.set_my_commands([
                BotCommand("status", "📊 daemon status"),
                BotCommand("run", "▶️ run a prompt"),
                BotCommand("queue", "📋 pending prompts"),
                BotCommand("tail", "📡 log streaming"),
                BotCommand("logs", "📜 recent logs"),
                BotCommand("result", "📄 last result"),
                BotCommand("sessions", "🗂️ session list"),
                BotCommand("stop", "🛑 stop execution"),
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

    def _build_menu_markup(self) -> Any:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = [
            [InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"]) for btn in row]
            for row in _MENU_KEYBOARD
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

    async def _reply(self, update: Any, text: str, parse_mode: str = "Markdown") -> None:
        """Send a reply whether the update came from a message or a callback query."""
        if update.callback_query is not None:
            await update.callback_query.message.reply_text(text, parse_mode=parse_mode)
        elif update.message is not None:
            await update.message.reply_text(text, parse_mode=parse_mode)

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
        elif data == "tail_on":
            context.args = ["on"]
            await self._send_tail(update, context)
        elif data == "tail_dashboard":
            context.args = ["dashboard"]
            await self._send_tail(update, context)
        elif data == "tail_off":
            context.args = ["off"]
            await self._send_tail(update, context)
        elif data == "logs":
            context.args = []
            await self._send_logs(update, context)
        elif data == "sessions":
            await self._send_sessions(update, context)
        elif data == "stop":
            await self._send_stop(update, context)

    async def _cmd_status(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_status(update, context)

    async def _send_status(self, update: Any, context: Any) -> None:
        in_progress = list(self._runner._in_progress)
        streaming_id = self._stream.streaming_chat_id
        lines = ["📊 *dormammu daemon status*"]
        if in_progress:
            lines.append("▶️ Active: " + ", ".join(p.name for p in in_progress))
        else:
            lines.append("💤 Active: idle")
        from dormammu.daemon.queue import is_prompt_candidate

        prompt_dir = self._daemon_config.prompt_path
        pending_count = 0
        if prompt_dir.exists():
            pending_count = sum(
                1
                for p in prompt_dir.iterdir()
                if is_prompt_candidate(p, self._daemon_config.queue) and p not in self._runner._in_progress
            )
        lines.append(f"📋 Queued: {pending_count}")
        lines.append(f"📡 Streaming: {'on (chat ' + str(streaming_id) + ')' if streaming_id else 'off'}")
        lines.append(f"📁 Repo: `{self._app_config.repo_root}`")
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
        mode = context.args[0].lower() if context.args else "on"
        if mode == "off":
            self._stream.disable_streaming()
            await self._reply(update, "📡 Log streaming disabled.")
        elif mode == "dashboard":
            self._stream.enable_streaming(chat_id, dashboard=True)
            await self._reply(
                update,
                "📡 Dashboard streaming enabled.\n"
                "Shows loop number, PLAN.md and DASHBOARD.md content per loop,\n"
                "agent output, and supervisor verdict.\n"
                "Use /tail off to stop.",
            )
        else:
            self._stream.enable_streaming(chat_id)
            await self._reply(update, "📡 Log streaming enabled (full). Use /tail off to stop.")

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
        await self._reply(update, f"*{result_path.name}*\n\n{content}")

    async def _cmd_sessions(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_sessions(update, context)

    async def _send_sessions(self, update: Any, context: Any) -> None:
        sessions_dir = self._app_config.base_dev_dir / "sessions"
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

    async def _cmd_stop(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await self._send_stop(update, context)

    async def _send_stop(self, update: Any, context: Any) -> None:
        in_progress = list(self._runner._in_progress)
        if not in_progress:
            await self._reply(update, "🛑 No active prompt to stop.")
            return
        names = ", ".join(p.name for p in in_progress)
        await self._reply(update, f"🛑 Sending interrupt to active prompt: {names}")
        os.kill(os.getpid(), signal.SIGINT)
