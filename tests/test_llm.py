from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.llm import LlmClient, parse_llm_config


class _FakeHeaders(dict):
    def items(self):
        return super().items()


class _FakeResponse:
    def __init__(self, payload: dict[str, object], headers: dict[str, str] | None = None) -> None:
        self._payload = payload
        self.headers = _FakeHeaders(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_parse_llm_config_masks_inline_secrets() -> None:
    config = parse_llm_config(
        {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "auth": {
                "type": "api_key",
                "api_key": "sk-secret",
            },
        },
        config_path=None,
    )

    assert config is not None
    assert config.auth.api_key == "sk-secret"
    assert config.to_dict()["auth"]["api_key"] == "***"


def test_parse_llm_config_rejects_oauth_for_non_openai_provider() -> None:
    with pytest.raises(RuntimeError, match="oauth.*openai"):
        parse_llm_config(
            {
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "auth": {
                    "type": "oauth",
                    "oauth_token_env": "ANTHROPIC_AUTH_TOKEN",
                },
            },
            config_path=None,
        )


def test_openai_oauth_uses_bearer_token_and_responses_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    config = parse_llm_config(
        {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "auth": {
                "type": "oauth",
                "oauth_token_env": "OPENAI_OAUTH_TOKEN",
            },
        },
        config_path=None,
    )
    assert config is not None
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse({"output_text": "hello"}, {"x-request-id": "req_123"})

    monkeypatch.setattr("dormammu.llm.request.urlopen", fake_urlopen)

    response = LlmClient(config, env={"OPENAI_OAUTH_TOKEN": "oauth-secret"}).generate("Say hello")

    assert response.text == "hello"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer oauth-secret"
    assert captured["body"]["model"] == "gpt-4.1-mini"


def test_gemini_api_key_uses_generate_content_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    config = parse_llm_config(
        {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "auth": {
                "type": "api_key",
                "api_key_env": "GEMINI_API_KEY",
            },
        },
        config_path=None,
    )
    assert config is not None
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        return _FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "gemini says hi"}]}}]}
        )

    monkeypatch.setattr("dormammu.llm.request.urlopen", fake_urlopen)

    response = LlmClient(config, env={"GEMINI_API_KEY": "gemini-secret"}).generate("Hi")

    assert response.text == "gemini says hi"
    assert captured["url"].endswith("/models/gemini-2.0-flash:generateContent")
    assert captured["headers"]["X-goog-api-key"] == "gemini-secret"


def test_claude_api_key_uses_messages_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    config = parse_llm_config(
        {
            "provider": "claude",
            "model": "claude-sonnet-4-5",
            "auth": {
                "type": "api_key",
                "api_key_env": "ANTHROPIC_API_KEY",
            },
        },
        config_path=None,
    )
    assert config is not None
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"content": [{"type": "text", "text": "claude says hi"}]})

    monkeypatch.setattr("dormammu.llm.request.urlopen", fake_urlopen)

    response = LlmClient(config, env={"ANTHROPIC_API_KEY": "claude-secret"}).generate("Hi")

    assert response.text == "claude says hi"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["X-api-key"] == "claude-secret"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["body"]["messages"][0]["content"] == "Hi"
