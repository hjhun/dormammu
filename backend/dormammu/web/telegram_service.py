from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from typing import Callable, TextIO

from dormammu.agent import CliAdapter
from dormammu.agent.models import AgentRunRequest
from dormammu.config import AppConfig
from dormammu.daemon.cli_output import model_args, select_agent_output
from dormammu.telegram.session_store import (
    ConversationIdentity,
    ConversationSnapshot,
    TelegramConversationSessionStore,
)


@dataclass(frozen=True, slots=True)
class TelegramSessionSummary:
    id: str
    path: Path
    updated_at: str | None
    turn_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": str(self.path),
            "updated_at": self.updated_at,
            "turn_count": self.turn_count,
        }


class TelegramConversationService:
    def __init__(
        self,
        app_config: AppConfig,
        *,
        adapter_cls: Callable[..., CliAdapter] = CliAdapter,
        live_output_stream: TextIO | None = None,
    ) -> None:
        self._config = app_config
        self._store = TelegramConversationSessionStore(app_config)
        self._adapter_cls = adapter_cls
        self._live_output_stream = live_output_stream
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @property
    def store(self) -> TelegramConversationSessionStore:
        return self._store

    def list_sessions(self) -> tuple[TelegramSessionSummary, ...]:
        root = self._store.root_dir
        if not root.exists():
            return ()
        summaries: list[TelegramSessionSummary] = []
        for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_dir():
                continue
            snapshot = self._store.load_by_session_id(path.name)
            metadata = TelegramConversationSessionStore._read_metadata(path / "session.json")
            summaries.append(
                TelegramSessionSummary(
                    id=snapshot.session_id,
                    path=path,
                    updated_at=str(metadata.get("updated_at") or "") or None,
                    turn_count=len(snapshot.turns),
                )
            )
        return tuple(summaries)

    def load_session(self, session_id: str) -> ConversationSnapshot:
        return self._store.load_by_session_id(session_id)

    def continue_identity(self, identity: ConversationIdentity, prompt_text: str) -> str:
        return self.continue_session(identity.session_id, prompt_text)

    def continue_session(self, session_id: str, prompt_text: str) -> str:
        lock = self._lock_for(session_id)
        with lock:
            try:
                response = self._run_cli_response(session_id, prompt_text)
            except Exception as exc:
                self._store.append_turn_by_session_id(session_id, role="user", text=prompt_text)
                self._store.append_turn_by_session_id(
                    session_id,
                    role="error",
                    kind="cli_error",
                    text=str(exc),
                )
                raise
            self._store.append_turn_by_session_id(session_id, role="user", text=prompt_text)
            self._store.append_turn_by_session_id(session_id, role="assistant", text=response)
            return response

    def _lock_for(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[session_id] = lock
            return lock

    def _run_cli_response(self, session_id: str, prompt_text: str) -> str:
        role_config = self._config.agents.developer if self._config.agents is not None else None
        cli = (
            role_config.resolve_cli(self._config.active_agent_cli)
            if role_config is not None
            else self._config.active_agent_cli
        )
        if cli is None:
            raise RuntimeError("No CLI is configured. Set active_agent_cli or agents.developer.cli.")
        model = role_config.model if role_config is not None else None
        snapshot = self._store.compact_if_needed_by_session_id(
            session_id,
            current_message=prompt_text,
        )
        direct_prompt = self._store.build_prompt(snapshot, prompt_text)
        started = time.monotonic()
        adapter = self._adapter_cls(
            self._config,
            live_output_stream=self._live_output_stream,
        )
        result = adapter.run_once(
            AgentRunRequest(
                cli_path=cli,
                prompt_text=direct_prompt,
                repo_root=self._config.repo_root,
                workdir=self._config.repo_root,
                extra_args=tuple(model_args(cli.name, model)),
                run_label=f"web-telegram-direct-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            )
        )
        stdout_text = result.stdout_path.read_text(encoding="utf-8") if result.stdout_path.exists() else ""
        stderr_text = result.stderr_path.read_text(encoding="utf-8") if result.stderr_path.exists() else ""
        output = select_agent_output(stdout_text, stderr_text).strip()
        if result.exit_code != 0:
            raise RuntimeError(
                f"CLI request failed with exit code {result.exit_code}: {output or '(no output)'}"
            )
        elapsed = time.monotonic() - started
        return output or f"(empty response after {elapsed:.2f}s)"
