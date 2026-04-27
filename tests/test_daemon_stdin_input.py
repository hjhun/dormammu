from __future__ import annotations

import argparse
import io
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu._cli_handlers import _enqueue_stdin_prompt_if_requested


def test_daemonize_stdin_empty_string_does_not_enqueue_prompt(monkeypatch, tmp_path: Path) -> None:
    daemon_config = SimpleNamespace(prompt_path=tmp_path / "prompts")
    args = argparse.Namespace(stdin_prompt=True)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    result = _enqueue_stdin_prompt_if_requested(args, daemon_config)

    assert result is None
    assert not daemon_config.prompt_path.exists()


def test_daemonize_stdin_whitespace_does_not_enqueue_prompt(monkeypatch, tmp_path: Path) -> None:
    daemon_config = SimpleNamespace(prompt_path=tmp_path / "prompts")
    args = argparse.Namespace(stdin_prompt=True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("  \n\t"))

    result = _enqueue_stdin_prompt_if_requested(args, daemon_config)

    assert result is None
    assert not daemon_config.prompt_path.exists()


def test_daemonize_stdin_non_empty_enqueues_direct_response_prompt(monkeypatch, tmp_path: Path) -> None:
    daemon_config = SimpleNamespace(prompt_path=tmp_path / "prompts")
    args = argparse.Namespace(stdin_prompt=True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("hello from stdin\n"))

    result = _enqueue_stdin_prompt_if_requested(args, daemon_config)

    assert result is not None
    content = result.read_text(encoding="utf-8")
    assert "DORMAMMU_REQUEST_CLASS: direct_response" in content
    assert "hello from stdin" in content
