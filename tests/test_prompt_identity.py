from __future__ import annotations

from pathlib import Path

from dormammu.agent.prompt_identity import prepend_cli_identity


def test_prepend_cli_identity_adds_header() -> None:
    assert prepend_cli_identity("Implement feature X", Path("codex")) == (
        "[codex]\nImplement feature X"
    )


def test_prepend_cli_identity_is_idempotent() -> None:
    prompt = "[gemini]\nRun the review"
    assert prepend_cli_identity(prompt, Path("gemini")) == prompt
