from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    bot_token: str
    allowed_chat_ids: tuple[int, ...]
    stream_on_start: bool = False
    chunk_size: int = 3000
    flush_interval_seconds: float = 2.0

    def to_dict(self) -> dict[str, object]:
        return {
            "bot_token": "***",
            "allowed_chat_ids": list(self.allowed_chat_ids),
            "stream_on_start": self.stream_on_start,
            "chunk_size": self.chunk_size,
            "flush_interval_seconds": self.flush_interval_seconds,
        }


def parse_telegram_config(value: Any, *, config_path: Path | None) -> TelegramConfig | None:
    if value is None:
        return None
    source = str(config_path) if config_path is not None else "dormammu.json"
    if not isinstance(value, Mapping):
        raise RuntimeError(f"telegram must be a JSON object in {source}")
    bot_token = value.get("bot_token")
    if not isinstance(bot_token, str) or not bot_token.strip():
        raise RuntimeError(f"telegram.bot_token must be a non-empty string in {source}")
    raw_ids = value.get("allowed_chat_ids", [])
    if not isinstance(raw_ids, list):
        raise RuntimeError(f"telegram.allowed_chat_ids must be a list in {source}")
    try:
        allowed_chat_ids = tuple(int(cid) for cid in raw_ids)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"telegram.allowed_chat_ids must contain integers in {source}") from exc
    return TelegramConfig(
        bot_token=bot_token.strip(),
        allowed_chat_ids=allowed_chat_ids,
        stream_on_start=bool(value.get("stream_on_start", False)),
        chunk_size=int(value.get("chunk_size", 3000)),
        flush_interval_seconds=float(value.get("flush_interval_seconds", 2.0)),
    )
