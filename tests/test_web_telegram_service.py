from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from dormammu.config import AppConfig
from dormammu.telegram.session_store import ConversationIdentity, TelegramConversationSessionStore
from dormammu.web.telegram_service import TelegramConversationService


def _seed_repo(root: Path) -> None:
    (root / "AGENTS.md").write_text("repo\n", encoding="utf-8")


def _app_config(root: Path) -> AppConfig:
    env = dict(os.environ)
    env["HOME"] = str(root / "home")
    return AppConfig.load(repo_root=root, env=env).with_overrides(active_agent_cli=Path("codex"))


def test_web_service_continues_existing_telegram_session(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    config = _app_config(tmp_path)
    store = TelegramConversationSessionStore(config)
    identity = ConversationIdentity(chat_id=42)
    store.append_turn(identity, role="user", text="remember red")
    prompts: list[str] = []

    class FakeAdapter:
        def __init__(self, _config, *, live_output_stream=None):
            pass

        def run_once(self, request):
            prompts.append(request.prompt_text)
            stdout_path = tmp_path / "stdout.txt"
            stderr_path = tmp_path / "stderr.txt"
            stdout_path.write_text("red", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return SimpleNamespace(stdout_path=stdout_path, stderr_path=stderr_path, exit_code=0)

    service = TelegramConversationService(config, adapter_cls=FakeAdapter)

    response = service.continue_session(identity.session_id, "what color?")
    snapshot = store.load(identity)

    assert response == "red"
    assert "USER: remember red" in prompts[0]
    assert "Current message:\nwhat color?" in prompts[0]
    assert [turn.role for turn in snapshot.turns][-2:] == ["user", "assistant"]
    assert snapshot.turns[-1].text == "red"
