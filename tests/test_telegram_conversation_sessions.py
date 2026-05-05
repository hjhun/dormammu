from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config
from dormammu.telegram.config import TelegramConfig
from dormammu.telegram.session_store import (
    ConversationIdentity,
    TelegramConversationSessionStore,
)


def _app_config(tmp_path: Path) -> AppConfig:
    home = tmp_path / "home"
    repo = home / "samba" / "github" / "dormammu"
    repo.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("repo\n", encoding="utf-8")
    env = dict(os.environ)
    env["HOME"] = str(home)
    return AppConfig.load(repo_root=repo, env=env)


def _run(coro):
    return asyncio.run(coro)


def _seed_runtime_repo(root: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
    (root / "AGENTS.md").write_text("repo\n", encoding="utf-8")
    templates = root / "templates" / "dev"
    templates.mkdir(parents=True, exist_ok=True)
    (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n", encoding="utf-8")
    (templates / "plan.md.tmpl").write_text("# PLAN\n", encoding="utf-8")


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


def _runtime_app_config(root: Path) -> AppConfig:
    env = dict(os.environ)
    env["HOME"] = str(root / ".test-home")
    return AppConfig.load(repo_root=root, env=env)


def _make_bot(root: Path):
    from dormammu.telegram.bot import TelegramBot

    _seed_runtime_repo(root)
    app_config = _runtime_app_config(root)
    app_config.base_dev_dir.mkdir(parents=True, exist_ok=True)
    runner = mock.MagicMock()
    runner.shutdown_requested = False
    runner.in_progress_snapshot.return_value = frozenset()
    stream = mock.MagicMock()
    stream.streaming_chat_id = None
    telegram_config = TelegramConfig(
        bot_token="1234:fake",
        allowed_chat_ids=[42, 99],
        chunk_size=3000,
        flush_interval_seconds=2.0,
    )
    daemon_config = load_daemon_config(_write_daemon_config(root), app_config=app_config)
    return TelegramBot(
        telegram_config,
        daemon_config=daemon_config,
        app_config=app_config,
        stream=stream,
        runner=runner,
    ), runner, app_config


def _make_channel_update(text: str, chat_id: int = 42) -> mock.MagicMock:
    update = mock.MagicMock()
    update.effective_chat.id = chat_id
    update.callback_query = None
    update.message = None
    update.channel_post = mock.AsyncMock()
    update.channel_post.text = text
    update.channel_post.caption = None
    update.channel_post.reply_text = mock.AsyncMock()
    update.effective_message = update.channel_post
    return update


def _last_reply(update: mock.MagicMock) -> str:
    message = getattr(update, "effective_message", None) or update.message
    return message.reply_text.call_args[0][0]


def test_conversation_sessions_live_under_workspace_project_root(tmp_path: Path) -> None:
    config = _app_config(tmp_path)
    store = TelegramConversationSessionStore(config)
    identity = ConversationIdentity(chat_id=42)

    store.append_turn(identity, role="user", text="hello")

    expected = (
        config.global_home_dir
        / "workspace"
        / "samba"
        / "github"
        / "dormammu"
        / ".sessions"
        / "chat-42"
    )
    assert store.session_dir(identity) == expected
    assert (expected / "session.json").exists()
    assert (expected / "transcript.jsonl").exists()


def test_prompt_includes_summary_recent_turns_and_current_message(tmp_path: Path) -> None:
    config = _app_config(tmp_path)
    store = TelegramConversationSessionStore(config)
    identity = ConversationIdentity(chat_id=42)
    store.append_turn(identity, role="user", text="my name is Ada")
    store.append_turn(identity, role="assistant", text="Noted.")

    prompt = store.build_prompt(store.load(identity), "what is my name?")

    assert "Recent conversation:" in prompt
    assert "USER: my name is Ada" in prompt
    assert "ASSISTANT: Noted." in prompt
    assert "Current message:" in prompt
    assert "what is my name?" in prompt


def test_compaction_reduces_prompt_below_hard_limit(tmp_path: Path) -> None:
    config = _app_config(tmp_path)
    store = TelegramConversationSessionStore(
        config,
        soft_limit_bytes=900,
        hard_limit_bytes=1200,
        recent_turns=2,
    )
    identity = ConversationIdentity(chat_id=42)
    for index in range(10):
        store.append_turn(identity, role="user", text=f"turn {index} " + ("x" * 220))

    snapshot = store.compact_if_needed(identity, current_message="next")
    prompt = store.build_prompt(snapshot, "next")

    assert len(prompt.encode("utf-8")) <= 1200
    assert len(snapshot.turns) <= 2
    assert "Compacted" in snapshot.summary
    metadata = json.loads((store.session_dir(identity) / "session.json").read_text(encoding="utf-8"))
    assert metadata["compaction_count"] >= 1


def test_clear_removes_only_conversation_session(tmp_path: Path) -> None:
    config = _app_config(tmp_path)
    store = TelegramConversationSessionStore(config)
    first = ConversationIdentity(chat_id=42)
    second = ConversationIdentity(chat_id=99)
    store.append_turn(first, role="user", text="first")
    store.append_turn(second, role="user", text="second")

    assert store.clear(first) is True

    assert not store.session_dir(first).exists()
    assert store.session_dir(second).exists()


def test_telegram_direct_response_reuses_previous_session_context(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    bot, _, _ = _make_bot(root)
    bot._app_config = bot._app_config.with_overrides(active_agent_cli=Path("codex"))
    context = mock.MagicMock()
    context.args = []
    prompts: list[str] = []

    def fake_run_once(request):
        prompts.append(request.prompt_text)
        stdout_path = root / f"stdout-{len(prompts)}.txt"
        stderr_path = root / f"stderr-{len(prompts)}.txt"
        stdout_path.write_text(f"answer {len(prompts)}", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return SimpleNamespace(stdout_path=stdout_path, stderr_path=stderr_path, exit_code=0)

    async def exercise() -> None:
        with mock.patch("dormammu.telegram.bot.CliAdapter") as adapter_cls:
            adapter_cls.return_value.run_once.side_effect = fake_run_once
            await bot._cmd_channel_post_command(_make_channel_update("remember red"), context)
            await asyncio.gather(*tuple(bot._direct_response_tasks))
            await bot._cmd_channel_post_command(_make_channel_update("what color?"), context)
            await asyncio.gather(*tuple(bot._direct_response_tasks))

    _run(exercise())

    assert len(prompts) == 2
    assert "Current message:\nremember red" in prompts[0]
    assert "USER: remember red" in prompts[1]
    assert "ASSISTANT: answer 1" in prompts[1]
    assert "Current message:\nwhat color?" in prompts[1]


def test_clear_session_command_clears_current_conversation_only(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    bot, _, app_config = _make_bot(root)
    store = TelegramConversationSessionStore(app_config)
    store.append_turn(ConversationIdentity(chat_id=42), role="user", text="hello")
    store.append_turn(ConversationIdentity(chat_id=99), role="user", text="other")

    update = _make_channel_update("/clearSession", chat_id=42)
    context = mock.MagicMock()
    context.args = []

    _run(bot._cmd_channel_post_command(update, context))

    assert "Cleared conversation session" in _last_reply(update)
    assert not store.session_dir(ConversationIdentity(chat_id=42)).exists()
    assert store.session_dir(ConversationIdentity(chat_id=99)).exists()


def test_clear_session_callback_is_registered() -> None:
    from dormammu.telegram.bot import _HELP_TEXT, _MENU_KEYBOARD_BASE

    callbacks = [btn["callback_data"] for row in _MENU_KEYBOARD_BASE for btn in row]
    assert "clear_session" in callbacks
    assert "/clearSession" in _HELP_TEXT
