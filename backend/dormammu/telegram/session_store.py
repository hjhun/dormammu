from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from dormammu._utils import iso_now
from dormammu.config import AppConfig


DEFAULT_PROMPT_HARD_LIMIT_BYTES = 256 * 1024
DEFAULT_PROMPT_SOFT_LIMIT_BYTES = 220 * 1024
DEFAULT_RECENT_TURNS = 12
DEFAULT_SUMMARY_LIMIT_BYTES = 48 * 1024


def _safe_segment(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return normalized or "default"


def _utf8_size(text: str) -> int:
    return len(text.encode("utf-8"))


def _trim_to_bytes(text: str, limit: int) -> str:
    if _utf8_size(text) <= limit:
        return text
    encoded = text.encode("utf-8")[: max(0, limit)]
    return encoded.decode("utf-8", errors="ignore").rstrip()


@dataclass(frozen=True, slots=True)
class ConversationIdentity:
    chat_id: int | str
    thread_id: int | str | None = None

    @property
    def session_id(self) -> str:
        base = f"chat-{self.chat_id}"
        if self.thread_id is not None:
            base = f"{base}-thread-{self.thread_id}"
        return _safe_segment(base)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    role: str
    text: str
    created_at: str
    kind: str = "message"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConversationTurn":
        return cls(
            role=str(payload.get("role") or "unknown"),
            text=str(payload.get("text") or ""),
            created_at=str(payload.get("created_at") or ""),
            kind=str(payload.get("kind") or "message"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "kind": self.kind,
            "created_at": self.created_at,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class ConversationSnapshot:
    session_id: str
    session_dir: Path
    summary: str
    turns: tuple[ConversationTurn, ...]
    compaction_count: int

    @property
    def recent_turns(self) -> tuple[ConversationTurn, ...]:
        return self.turns[-DEFAULT_RECENT_TURNS:]


class TelegramConversationSessionStore:
    """Persist Telegram direct-response conversation state per repo/chat."""

    def __init__(
        self,
        app_config: AppConfig,
        *,
        hard_limit_bytes: int = DEFAULT_PROMPT_HARD_LIMIT_BYTES,
        soft_limit_bytes: int = DEFAULT_PROMPT_SOFT_LIMIT_BYTES,
        recent_turns: int = DEFAULT_RECENT_TURNS,
    ) -> None:
        self._config = app_config
        self.root_dir = app_config.workspace_project_root / ".sessions"
        self.hard_limit_bytes = hard_limit_bytes
        self.soft_limit_bytes = soft_limit_bytes
        self.recent_turns = recent_turns

    @staticmethod
    def identity_from_update(update: Any) -> ConversationIdentity:
        chat = getattr(update, "effective_chat", None)
        chat_id = getattr(chat, "id", "unknown")
        message = (
            getattr(update, "effective_message", None)
            or getattr(update, "message", None)
            or getattr(update, "channel_post", None)
        )
        thread_id = getattr(message, "message_thread_id", None)
        if not isinstance(thread_id, (int, str)):
            thread_id = None
        return ConversationIdentity(chat_id=chat_id, thread_id=thread_id)

    def session_dir(self, identity: ConversationIdentity) -> Path:
        return self.root_dir / identity.session_id

    def load(self, identity: ConversationIdentity) -> ConversationSnapshot:
        session_dir = self.session_dir(identity)
        summary = self._read_text(session_dir / "summary.md")
        turns = tuple(self._read_turns(session_dir / "transcript.jsonl"))
        metadata = self._read_metadata(session_dir / "session.json")
        compaction_count = int(metadata.get("compaction_count") or 0)
        return ConversationSnapshot(
            session_id=identity.session_id,
            session_dir=session_dir,
            summary=summary,
            turns=turns,
            compaction_count=compaction_count,
        )

    def clear(self, identity: ConversationIdentity) -> bool:
        session_dir = self.session_dir(identity)
        if not session_dir.exists():
            return False
        shutil.rmtree(session_dir)
        return True

    def append_turn(
        self,
        identity: ConversationIdentity,
        *,
        role: str,
        text: str,
        kind: str = "message",
    ) -> ConversationTurn:
        session_dir = self.session_dir(identity)
        session_dir.mkdir(parents=True, exist_ok=True)
        turn = ConversationTurn(
            role=role,
            text=text,
            kind=kind,
            created_at=iso_now(),
        )
        with (session_dir / "transcript.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(turn.to_dict(), ensure_ascii=False) + "\n")
        self._write_metadata(identity, session_dir=session_dir)
        return turn

    def build_prompt(self, snapshot: ConversationSnapshot, current_message: str) -> str:
        sections = [
            "Request class: direct_response",
            "This Telegram message should be handled in one pass.",
            "Use the conversation context below when it is relevant.",
            "Do not invent a multi-phase workflow, slice list, or retry plan.",
            "Do not modify repository files unless the message explicitly asks for it.",
            "Answer directly, then stop.",
            "",
        ]
        if snapshot.summary.strip():
            sections.extend([
                "Conversation summary:",
                snapshot.summary.strip(),
                "",
            ])
        recent = snapshot.turns[-self.recent_turns:]
        if recent:
            sections.extend([
                "Recent conversation:",
                self._format_turns(recent),
                "",
            ])
        sections.extend([
            "Current message:",
            current_message.strip() or "(empty message)",
            "",
        ])
        return "\n".join(sections)

    def compact_if_needed(
        self,
        identity: ConversationIdentity,
        *,
        current_message: str,
    ) -> ConversationSnapshot:
        snapshot = self.load(identity)
        prompt = self.build_prompt(snapshot, current_message)
        if (
            _utf8_size(prompt) < self.soft_limit_bytes
            and self._snapshot_size(snapshot) < self.soft_limit_bytes
        ):
            return snapshot

        compacted = self._compact_snapshot(snapshot)
        self._write_compacted(identity, compacted)
        refreshed = self.load(identity)
        prompt = self.build_prompt(refreshed, current_message)
        if _utf8_size(prompt) > self.hard_limit_bytes:
            self._trim_for_hard_limit(identity, current_message=current_message)
            refreshed = self.load(identity)
        return refreshed

    def _compact_snapshot(self, snapshot: ConversationSnapshot) -> ConversationSnapshot:
        keep = snapshot.turns[-self.recent_turns:]
        compacted_turns = snapshot.turns[: max(0, len(snapshot.turns) - len(keep))]
        if not compacted_turns:
            return snapshot
        summary_parts: list[str] = []
        if snapshot.summary.strip():
            summary_parts.append(snapshot.summary.strip())
        summary_parts.append(
            f"Compacted {len(compacted_turns)} earlier Telegram conversation turn(s)."
        )
        summary_parts.append(self._format_summary_excerpt(compacted_turns))
        summary = "\n\n".join(part for part in summary_parts if part.strip())
        summary = _trim_to_bytes(
            summary,
            min(DEFAULT_SUMMARY_LIMIT_BYTES, max(0, self.hard_limit_bytes // 2)),
        )
        return ConversationSnapshot(
            session_id=snapshot.session_id,
            session_dir=snapshot.session_dir,
            summary=summary,
            turns=keep,
            compaction_count=snapshot.compaction_count + 1,
        )

    @staticmethod
    def _snapshot_size(snapshot: ConversationSnapshot) -> int:
        text = snapshot.summary + "\n" + TelegramConversationSessionStore._format_turns(snapshot.turns)
        return _utf8_size(text)

    def _trim_for_hard_limit(
        self,
        identity: ConversationIdentity,
        *,
        current_message: str,
    ) -> None:
        snapshot = self.load(identity)
        turns = list(snapshot.turns)
        while turns:
            candidate = ConversationSnapshot(
                session_id=snapshot.session_id,
                session_dir=snapshot.session_dir,
                summary=snapshot.summary,
                turns=tuple(turns),
                compaction_count=snapshot.compaction_count,
            )
            if _utf8_size(self.build_prompt(candidate, current_message)) <= self.hard_limit_bytes:
                break
            turns.pop(0)
        trimmed = ConversationSnapshot(
            session_id=snapshot.session_id,
            session_dir=snapshot.session_dir,
            summary=_trim_to_bytes(snapshot.summary, max(0, self.hard_limit_bytes // 3)),
            turns=tuple(turns),
            compaction_count=snapshot.compaction_count + 1,
        )
        self._write_compacted(identity, trimmed)

    def _write_compacted(
        self,
        identity: ConversationIdentity,
        snapshot: ConversationSnapshot,
    ) -> None:
        session_dir = self.session_dir(identity)
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "summary.md").write_text(snapshot.summary, encoding="utf-8")
        transcript = session_dir / "transcript.jsonl"
        transcript.write_text(
            "".join(
                json.dumps(turn.to_dict(), ensure_ascii=False) + "\n"
                for turn in snapshot.turns
            ),
            encoding="utf-8",
        )
        self._write_metadata(
            identity,
            session_dir=session_dir,
            compaction_count=snapshot.compaction_count,
            turn_count=len(snapshot.turns),
        )

    def _write_metadata(
        self,
        identity: ConversationIdentity,
        *,
        session_dir: Path,
        compaction_count: int | None = None,
        turn_count: int | None = None,
    ) -> None:
        metadata_path = session_dir / "session.json"
        existing = self._read_metadata(metadata_path)
        now = iso_now()
        turns = turn_count
        if turns is None:
            turns = sum(1 for _ in self._read_turns(session_dir / "transcript.jsonl"))
        metadata = {
            "schema_version": 1,
            "session_id": identity.session_id,
            "repo_root": str(self._config.repo_root),
            "workspace_project_root": str(self._config.workspace_project_root),
            "chat_id": str(identity.chat_id),
            "thread_id": str(identity.thread_id) if identity.thread_id is not None else None,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
            "turn_count": turns,
            "compaction_count": (
                int(existing.get("compaction_count") or 0)
                if compaction_count is None
                else compaction_count
            ),
            "soft_limit_bytes": self.soft_limit_bytes,
            "hard_limit_bytes": self.hard_limit_bytes,
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _read_turns(path: Path) -> Iterable[ConversationTurn]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()
        turns: list[ConversationTurn] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                turns.append(ConversationTurn.from_dict(payload))
        return tuple(turns)

    @staticmethod
    def _format_turns(turns: Iterable[ConversationTurn]) -> str:
        lines: list[str] = []
        for turn in turns:
            role = turn.role.upper()
            text = turn.text.strip() or "(empty)"
            lines.append(f"{role}: {text}")
        return "\n".join(lines)

    @staticmethod
    def _format_summary_excerpt(turns: Iterable[ConversationTurn]) -> str:
        lines = ["Compacted transcript excerpt:"]
        for turn in turns:
            text = _trim_to_bytes(turn.text.strip().replace("\n", " "), 700)
            if text:
                lines.append(f"- {turn.role}: {text}")
        return "\n".join(lines)
