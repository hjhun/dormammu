from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib import error, request


SUPPORTED_LLM_PROVIDERS = frozenset({"gemini", "openai", "claude"})
SUPPORTED_AUTH_TYPES = frozenset({"api_key", "oauth"})
DEFAULT_LLM_TIMEOUT_SECONDS = 60
DEFAULT_LLM_MAX_OUTPUT_TOKENS = 1024
ANTHROPIC_VERSION = "2023-06-01"


class LlmError(RuntimeError):
    """Raised when a configured LLM provider cannot complete a request."""


def _source(config_path: Path | None) -> str:
    return str(config_path) if config_path is not None else "dormammu.json"


def _mask_secret(value: str | None) -> str | None:
    if value is None:
        return None
    return "***"


def _non_empty_string(value: Any, *, field_name: str, config_path: Path | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{field_name} must be a non-empty string in {_source(config_path)}")
    return value.strip()


@dataclass(frozen=True, slots=True)
class LlmAuthConfig:
    type: str
    api_key: str | None = None
    api_key_env: str | None = None
    oauth_token: str | None = None
    oauth_token_env: str | None = None

    def credential(self, *, env: Mapping[str, str] | None = None) -> str:
        values = env or os.environ
        if self.type == "api_key":
            if self.api_key:
                return self.api_key
            if self.api_key_env:
                value = values.get(self.api_key_env)
                if value:
                    return value
            raise LlmError("LLM API key is not configured or the configured environment variable is empty.")
        if self.type == "oauth":
            if self.oauth_token:
                return self.oauth_token
            if self.oauth_token_env:
                value = values.get(self.oauth_token_env)
                if value:
                    return value
            raise LlmError("LLM OAuth token is not configured or the configured environment variable is empty.")
        raise LlmError(f"Unsupported LLM auth type: {self.type}")

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "api_key": _mask_secret(self.api_key),
            "api_key_env": self.api_key_env,
            "oauth_token": _mask_secret(self.oauth_token),
            "oauth_token_env": self.oauth_token_env,
        }


@dataclass(frozen=True, slots=True)
class LlmConfig:
    provider: str
    model: str
    auth: LlmAuthConfig
    base_url: str | None = None
    timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS
    max_output_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "auth": self.auth.to_dict(),
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True, slots=True)
class LlmResponse:
    provider: str
    model: str
    text: str
    request_id: str | None = None
    metadata: Mapping[str, object] | None = None


def parse_llm_config(value: Any, *, config_path: Path | None) -> LlmConfig | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RuntimeError(f"ai must be a JSON object in {_source(config_path)}")
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise RuntimeError(f"ai.enabled must be a boolean in {_source(config_path)}")
    if not enabled:
        return None

    provider = _non_empty_string(value.get("provider"), field_name="ai.provider", config_path=config_path).lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
        raise RuntimeError(f"ai.provider must be one of {supported} in {_source(config_path)}")
    model = _non_empty_string(value.get("model"), field_name="ai.model", config_path=config_path)

    raw_auth = value.get("auth")
    if not isinstance(raw_auth, Mapping):
        raise RuntimeError(f"ai.auth must be a JSON object in {_source(config_path)}")
    auth_type = _non_empty_string(raw_auth.get("type"), field_name="ai.auth.type", config_path=config_path).lower()
    if auth_type not in SUPPORTED_AUTH_TYPES:
        supported = ", ".join(sorted(SUPPORTED_AUTH_TYPES))
        raise RuntimeError(f"ai.auth.type must be one of {supported} in {_source(config_path)}")
    if auth_type == "oauth" and provider != "openai":
        raise RuntimeError("ai.auth.type=oauth is supported only when ai.provider is openai")

    api_key = _optional_non_empty(raw_auth.get("api_key"), field_name="ai.auth.api_key", config_path=config_path)
    api_key_env = _optional_non_empty(raw_auth.get("api_key_env"), field_name="ai.auth.api_key_env", config_path=config_path)
    oauth_token = _optional_non_empty(raw_auth.get("oauth_token"), field_name="ai.auth.oauth_token", config_path=config_path)
    oauth_token_env = _optional_non_empty(raw_auth.get("oauth_token_env"), field_name="ai.auth.oauth_token_env", config_path=config_path)
    if auth_type == "api_key" and not (api_key or api_key_env):
        raise RuntimeError("ai.auth.api_key or ai.auth.api_key_env is required when ai.auth.type is api_key")
    if auth_type == "oauth" and not (oauth_token or oauth_token_env):
        raise RuntimeError("ai.auth.oauth_token or ai.auth.oauth_token_env is required when ai.auth.type is oauth")

    base_url = _optional_non_empty(value.get("base_url"), field_name="ai.base_url", config_path=config_path)
    timeout_seconds = int(value.get("timeout_seconds", DEFAULT_LLM_TIMEOUT_SECONDS))
    max_output_tokens = int(value.get("max_output_tokens", DEFAULT_LLM_MAX_OUTPUT_TOKENS))
    if timeout_seconds < 1:
        raise RuntimeError(f"ai.timeout_seconds must be >= 1 in {_source(config_path)}")
    if max_output_tokens < 1:
        raise RuntimeError(f"ai.max_output_tokens must be >= 1 in {_source(config_path)}")

    return LlmConfig(
        provider=provider,
        model=model,
        auth=LlmAuthConfig(
            type=auth_type,
            api_key=api_key,
            api_key_env=api_key_env,
            oauth_token=oauth_token,
            oauth_token_env=oauth_token_env,
        ),
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
    )


def _optional_non_empty(value: Any, *, field_name: str, config_path: Path | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"{field_name} must be a string in {_source(config_path)}")
    stripped = value.strip()
    if not stripped:
        raise RuntimeError(f"{field_name} must not be empty in {_source(config_path)}")
    return stripped


class LlmClient:
    def __init__(self, config: LlmConfig, *, env: Mapping[str, str] | None = None) -> None:
        self._config = config
        self._env = env

    def generate(self, prompt_text: str) -> LlmResponse:
        prompt = prompt_text.strip()
        if not prompt:
            raise LlmError("LLM prompt is empty.")
        if self._config.provider == "openai":
            return self._openai(prompt)
        if self._config.provider == "gemini":
            return self._gemini(prompt)
        if self._config.provider == "claude":
            return self._claude(prompt)
        raise LlmError(f"Unsupported LLM provider: {self._config.provider}")

    def _openai(self, prompt: str) -> LlmResponse:
        base_url = (self._config.base_url or "https://api.openai.com/v1").rstrip("/")
        payload = {
            "model": self._config.model,
            "input": prompt,
            "max_output_tokens": self._config.max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._config.auth.credential(env=self._env)}",
            "Content-Type": "application/json",
        }
        response, response_headers = self._post_json(f"{base_url}/responses", headers=headers, payload=payload)
        text = _extract_openai_text(response)
        return LlmResponse(
            provider="openai",
            model=self._config.model,
            text=text,
            request_id=response_headers.get("x-request-id"),
            metadata={"auth_type": self._config.auth.type},
        )

    def _gemini(self, prompt: str) -> LlmResponse:
        base_url = (
            self._config.base_url
            or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        model = self._config.model
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": self._config.max_output_tokens},
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._config.auth.credential(env=self._env),
        }
        response, response_headers = self._post_json(
            f"{base_url}/models/{model}:generateContent",
            headers=headers,
            payload=payload,
        )
        return LlmResponse(
            provider="gemini",
            model=model,
            text=_extract_gemini_text(response),
            request_id=response_headers.get("x-request-id"),
            metadata={"auth_type": self._config.auth.type},
        )

    def _claude(self, prompt: str) -> LlmResponse:
        base_url = (self._config.base_url or "https://api.anthropic.com").rstrip("/")
        payload = {
            "model": self._config.model,
            "max_tokens": self._config.max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._config.auth.credential(env=self._env),
            "anthropic-version": ANTHROPIC_VERSION,
        }
        response, response_headers = self._post_json(
            f"{base_url}/v1/messages",
            headers=headers,
            payload=payload,
        )
        return LlmResponse(
            provider="claude",
            model=self._config.model,
            text=_extract_claude_text(response),
            request_id=response_headers.get("request-id"),
            metadata={"auth_type": self._config.auth.type},
        )

    def _post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> tuple[Mapping[str, object], Mapping[str, str]]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with request.urlopen(req, timeout=self._config.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw) if raw else {}
                if not isinstance(parsed, Mapping):
                    raise LlmError("LLM provider returned a non-object JSON response.")
                return parsed, {key.lower(): value for key, value in resp.headers.items()}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise LlmError(f"LLM provider returned HTTP {exc.code}: {_truncate_error(detail)}") from exc
        except error.URLError as exc:
            raise LlmError(f"LLM provider request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LlmError("LLM provider request timed out.") from exc
        except json.JSONDecodeError as exc:
            raise LlmError("LLM provider returned invalid JSON.") from exc


def _truncate_error(text: str, *, limit: int = 500) -> str:
    if not text:
        return "no response body"
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"


def _extract_openai_text(payload: Mapping[str, object]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    output = payload.get("output")
    parts: list[str] = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, Mapping):
                    continue
                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    if parts:
        return "\n".join(parts)
    raise LlmError("OpenAI response did not contain output text.")


def _extract_gemini_text(payload: Mapping[str, object]) -> str:
    candidates = payload.get("candidates")
    parts: list[str] = []
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            content = candidate.get("content")
            if not isinstance(content, Mapping):
                continue
            raw_parts = content.get("parts")
            if not isinstance(raw_parts, list):
                continue
            for part in raw_parts:
                if not isinstance(part, Mapping):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    if parts:
        return "\n".join(parts)
    raise LlmError("Gemini response did not contain output text.")


def _extract_claude_text(payload: Mapping[str, object]) -> str:
    content = payload.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    if parts:
        return "\n".join(parts)
    raise LlmError("Claude response did not contain output text.")
