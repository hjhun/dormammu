from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu._cli_handlers import _enqueue_stdin_prompt_if_requested
from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config
from dormammu.daemon.runner import DaemonRunner
from dormammu.state import StateRepository


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


def test_daemon_runner_llm_direct_response_does_not_require_agent_cli(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "dormammu.json").write_text(
        json.dumps(
            {
                "ai": {
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "auth": {
                        "type": "api_key",
                        "api_key_env": "OPENAI_API_KEY",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    daemon_config_path = root / "daemonize.json"
    daemon_config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "prompt_path": "./queue/prompts",
                "result_path": "./queue/results",
                "watch": {"backend": "polling", "poll_interval_seconds": 1, "settle_seconds": 0},
                "queue": {"allowed_extensions": [".md"], "ignore_hidden_files": True},
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig.load(repo_root=root, env={"HOME": str(tmp_path / "home")})
    daemon_config = load_daemon_config(daemon_config_path, app_config=config)
    repository = StateRepository(config)
    repository.start_new_session(goal="LLM direct response", prompt_text="hello", active_roadmap_phase_ids=["phase_4"])
    session_state = repository.read_session_state()
    session_id = session_state.get("active_session_id") or session_state["session_id"]
    session_repository = StateRepository(config, session_id=session_id)

    class FakeClient:
        def __init__(self, llm_config):
            self.llm_config = llm_config

        def generate(self, prompt_text: str):
            assert prompt_text == "hello"
            return SimpleNamespace(
                provider="openai",
                model=self.llm_config.model,
                text="LLM says hello",
                request_id="req_test",
            )

    monkeypatch.setattr("dormammu.daemon.runner.LlmClient", FakeClient)

    result = DaemonRunner(config, daemon_config)._run_llm_direct_response(
        scoped_config=config,
        session_repository=session_repository,
        prompt_path=daemon_config.prompt_path / "stdin_fast.md",
        prompt_text="DORMAMMU_REQUEST_CLASS: direct_response\n\nhello",
    )

    assert result.status.value == "completed"
    assert result.output == "LLM says hello"
    assert result.report_path is not None
    assert result.report_path.read_text(encoding="utf-8") == "# LLM Response\n\nLLM says hello\n"
