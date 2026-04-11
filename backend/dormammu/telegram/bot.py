from __future__ import annotations

import asyncio
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


_HELP_TEXT = """\
*dormammu bot commands*

/status — daemon status and active prompt
/run <prompt> — queue a new prompt for execution
/queue — list pending prompts
/tail [on|off] — stream daemon output to this chat
/logs [n] — last N lines of progress log (default 50)
/result [name] — last (or named) result file content
/sessions — recent session list
/stop — send interrupt to the running prompt
/help — this message\
"""


class TelegramBot:
    """Telegram bot that integrates with DaemonRunner.

    Runs in a background daemon thread with its own asyncio event loop.
    Command handlers can safely read daemon state and write prompt files.
    """

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start bot polling in a daemon thread. Blocks until the bot loop is ready."""
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="dormammu-telegram-bot",
        )
        self._thread.start()
        self._ready.wait(timeout=15)
        self._stream.set_send_fn(self._send_message_sync)

    def _send_message_sync(self, chat_id: int, text: str) -> None:
        """Thread-safe: schedule a Telegram message send from any thread."""
        if self._loop is None or self._app is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._app.bot.send_message(chat_id=chat_id, text=text),
                self._loop,
            )
        except Exception:
            pass

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_run())
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

        from telegram.ext import CommandHandler

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

        async with self._app:
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            self._ready.set()
            try:
                await asyncio.Event().wait()
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
            finally:
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
            if update.message:
                await update.message.reply_text("Access denied.")
            return False
        return True

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_help(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")

    async def _cmd_status(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        in_progress = list(self._runner._in_progress)
        streaming_id = self._stream.streaming_chat_id
        lines = ["*dormammu daemon status*"]
        if in_progress:
            lines.append("Active: " + ", ".join(p.name for p in in_progress))
        else:
            lines.append("Active: idle")
        from dormammu.daemon.queue import is_prompt_candidate

        prompt_dir = self._daemon_config.prompt_path
        pending_count = 0
        if prompt_dir.exists():
            pending_count = sum(
                1
                for p in prompt_dir.iterdir()
                if is_prompt_candidate(p, self._daemon_config.queue) and p not in self._runner._in_progress
            )
        lines.append(f"Queued: {pending_count}")
        lines.append(f"Streaming: {'on (chat ' + str(streaming_id) + ')' if streaming_id else 'off'}")
        lines.append(f"Repo: `{self._app_config.repo_root}`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_run(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /run <prompt text>")
            return
        prompt_text = " ".join(context.args)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        prompt_path = self._daemon_config.prompt_path / f"tg_{ts}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        await update.message.reply_text(
            f"Queued: `{prompt_path.name}`", parse_mode="Markdown"
        )

    async def _cmd_queue(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
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
            await update.message.reply_text("Prompt queue is empty.")
            return
        lines = [f"*Prompt queue ({len(items)})*"] + [f"• {name}" for name in items]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_tail(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        chat_id = update.effective_chat.id
        mode = context.args[0].lower() if context.args else "on"
        if mode == "off":
            self._stream.disable_streaming()
            await update.message.reply_text("Log streaming disabled.")
        else:
            self._stream.enable_streaming(chat_id)
            await update.message.reply_text(
                "Log streaming enabled. Use /tail off to stop."
            )

    async def _cmd_logs(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        try:
            n = int(context.args[0]) if context.args else 50
            n = max(1, min(n, 200))
        except (ValueError, IndexError):
            await update.message.reply_text("Usage: /logs [n]  — lines to show, 1–200")
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
            await update.message.reply_text("No progress log available (run with --debug to enable).")
            return
        text = log_path.read_text(encoding="utf-8", errors="replace")
        tail = "\n".join(text.splitlines()[-n:])
        if not tail.strip():
            await update.message.reply_text("Log is empty.")
            return
        max_chars = 3800
        if len(tail) > max_chars:
            tail = "..." + tail[-max_chars:]
        await update.message.reply_text(f"```\n{tail}\n```", parse_mode="Markdown")

    async def _cmd_result(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        result_dir = self._daemon_config.result_path
        if not result_dir.exists():
            await update.message.reply_text("No results directory found.")
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
                await update.message.reply_text("No results found.")
                return
            result_path = candidates[0]
        if not result_path.exists():
            await update.message.reply_text(f"Result not found: {result_path.name}")
            return
        content = result_path.read_text(encoding="utf-8", errors="replace")
        max_chars = 3800
        if len(content) > max_chars:
            content = content[:max_chars] + "\n…(truncated)"
        await update.message.reply_text(
            f"*{result_path.name}*\n\n{content}", parse_mode="Markdown"
        )

    async def _cmd_sessions(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        sessions_dir = self._app_config.base_dev_dir / "sessions"
        if not sessions_dir.exists():
            await update.message.reply_text("No sessions directory found.")
            return
        session_dirs = sorted(
            (p for p in sessions_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:10]
        if not session_dirs:
            await update.message.reply_text("No sessions found.")
            return
        lines = [f"*Recent sessions ({len(session_dirs)})*"] + [f"• {s.name}" for s in session_dirs]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_stop(self, update: Any, context: Any) -> None:
        if not await self._guard(update):
            return
        in_progress = list(self._runner._in_progress)
        if not in_progress:
            await update.message.reply_text("No active prompt to stop.")
            return
        names = ", ".join(p.name for p in in_progress)
        await update.message.reply_text(f"Sending interrupt to active prompt: {names}")
        os.kill(os.getpid(), signal.SIGINT)
