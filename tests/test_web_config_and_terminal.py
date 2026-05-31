from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import time

import pytest

from dormammu.config import AppConfig
from dormammu.web.auth import hash_password, host_requires_token, password_matches, validate_server_auth_config
from dormammu.web.settings import MASKED_SECRET, apply_settings_patch, read_settings, write_raw_settings
from dormammu.web.terminal import TerminalAccessError, TerminalSessionManager, resolve_allowed_cwd


def _seed_repo(root: Path) -> None:
    (root / "AGENTS.md").write_text("repo\n", encoding="utf-8")


def _app_config(root: Path) -> AppConfig:
    env = dict(os.environ)
    env["HOME"] = str(root / "home")
    return AppConfig.load(repo_root=root, env=env)


def test_web_config_defaults_to_repo_root(tmp_path: Path) -> None:
    _seed_repo(tmp_path)

    config = _app_config(tmp_path)

    assert config.web_config.allowed_roots == (tmp_path.resolve(),)
    assert config.web_config.host is None
    assert config.web_config.port is None
    assert config.web_config.password_hash is None


def test_web_config_parses_allowed_roots_host_and_port(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "dormammu.json").write_text(
        json.dumps({
            "web": {
                "allowed_roots": ["workspace"],
                "host": "127.0.0.1",
                "port": 9001,
                "password_hash": "pbkdf2_sha256$1$salt$digest",
            }
        }),
        encoding="utf-8",
    )

    config = _app_config(tmp_path)

    assert config.web_config.allowed_roots == (workspace.resolve(),)
    assert config.web_config.host == "127.0.0.1"
    assert config.web_config.port == 9001
    assert config.web_config.password_hash == "pbkdf2_sha256$1$salt$digest"


def test_settings_patch_preserves_unknown_keys_and_masks_token(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "dormammu.json").write_text(
        json.dumps({
            "unknown": {"keep": True},
            "telegram": {"bot_token": "secret", "allowed_chat_ids": [42]},
            "web": {"password_hash": "pbkdf2_sha256$1$salt$digest"},
        }),
        encoding="utf-8",
    )
    config = _app_config(tmp_path)

    settings = read_settings(config)
    written = apply_settings_patch(
        config,
        {
            "active_agent_cli": "/usr/bin/codex",
            "telegram": {
                "bot_token": MASKED_SECRET,
                "allowed_chat_ids": [42, "99"],
                "stream_on_start": True,
            },
            "web": {
                "allowed_roots": [str(tmp_path)],
                "host": "0.0.0.0",
                "port": 9001,
            },
            "process_timeout_seconds": 300,
            "fallback_on_nonzero_exit": True,
        },
    )
    payload = json.loads(written.read_text(encoding="utf-8"))

    assert settings["telegram"]["bot_token"] == MASKED_SECRET
    assert settings["web"]["password_configured"] is True
    assert "password_hash" not in settings["web"]
    assert settings["config_file"] == str(tmp_path / "dormammu.json")
    assert '"bot_token": "***"' in settings["raw_json"]
    assert '"password_hash": "***"' in settings["raw_json"]
    assert payload["unknown"] == {"keep": True}
    assert payload["telegram"]["bot_token"] == "secret"
    assert payload["telegram"]["allowed_chat_ids"] == [42, 99]
    assert payload["telegram"]["stream_on_start"] is True
    assert payload["web"]["port"] == 9001
    assert payload["web"]["password_hash"] == "pbkdf2_sha256$1$salt$digest"
    assert payload["process_timeout_seconds"] == 300
    assert payload["fallback_on_nonzero_exit"] is True


def test_raw_settings_write_preserves_masked_secrets(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "dormammu.json").write_text(
        json.dumps({
            "telegram": {"bot_token": "secret"},
            "web": {"password_hash": "hash", "host": "127.0.0.1"},
        }),
        encoding="utf-8",
    )
    config = _app_config(tmp_path)
    settings = read_settings(config)

    raw = settings["raw_json"].replace('"host": "127.0.0.1"', '"host": "0.0.0.0"')
    written = write_raw_settings(config, raw)
    payload = json.loads(written.read_text(encoding="utf-8"))

    assert payload["telegram"]["bot_token"] == "secret"
    assert payload["web"]["password_hash"] == "hash"
    assert payload["web"]["host"] == "0.0.0.0"


def test_allowed_cwd_rejects_path_outside_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    assert resolve_allowed_cwd(allowed, (allowed,)) == allowed.resolve()

    with pytest.raises(TerminalAccessError):
        resolve_allowed_cwd(outside, (allowed,))


def test_terminal_session_write_reaches_tmux_session(tmp_path: Path) -> None:
    if not shutil.which("tmux"):
        pytest.skip("tmux is required for terminal runtime tests")
    manager = TerminalSessionManager(allowed_roots=(tmp_path,))
    snapshot = manager.create_session(cwd=tmp_path, command=("/bin/cat",))
    session = manager.get(snapshot.id)
    chunks: list[bytes] = []
    deadline = time.monotonic() + 3

    try:
        with session.subscribe() as output:
            session.write("dormammu-input-smoke\n")
            while time.monotonic() < deadline:
                try:
                    chunk = output.get(timeout=0.1)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                chunks.append(chunk)
                if b"dormammu-input-smoke" in b"".join(chunks):
                    break
    finally:
        manager.close_all()

    assert b"dormammu-input-smoke" in b"".join(chunks)


def test_terminal_manager_rediscovers_tmux_sessions(tmp_path: Path) -> None:
    if not shutil.which("tmux"):
        pytest.skip("tmux is required for terminal runtime tests")
    manager = TerminalSessionManager(allowed_roots=(tmp_path,))
    snapshot = manager.create_session(cwd=tmp_path)

    try:
        rediscovered = TerminalSessionManager(allowed_roots=(tmp_path,)).list_sessions()
    finally:
        manager.delete(snapshot.id)

    assert any(item.id == snapshot.id for item in rediscovered)


def test_terminal_manager_persists_session_metadata(tmp_path: Path) -> None:
    if not shutil.which("tmux"):
        pytest.skip("tmux is required for terminal runtime tests")
    state_dir = tmp_path / ".state"
    manager = TerminalSessionManager(allowed_roots=(tmp_path,), state_dir=state_dir, repo_root=tmp_path)
    snapshot = manager.create_session(cwd=tmp_path, source="cli")

    try:
        manager.record_command(snapshot.id, "dormammu resume --repo-root .")
        rediscovered = TerminalSessionManager(
            allowed_roots=(tmp_path,),
            state_dir=state_dir,
            repo_root=tmp_path,
        ).list_sessions()
    finally:
        manager.delete(snapshot.id)

    matched = next(item for item in rediscovered if item.id == snapshot.id)
    assert matched.source == "cli"
    assert matched.repo_root == tmp_path.resolve()
    assert matched.last_command == "dormammu resume --repo-root ."
    payload = json.loads((state_dir / "terminal_sessions.json").read_text(encoding="utf-8"))
    assert snapshot.id not in payload["sessions"]


def test_external_bind_requires_token() -> None:
    assert host_requires_token("0.0.0.0") is True
    assert host_requires_token("127.0.0.1") is False

    with pytest.raises(ValueError):
        validate_server_auth_config(host="0.0.0.0", token=None, allow_initial_setup=False)

    validate_server_auth_config(host="0.0.0.0", token="secret")
    validate_server_auth_config(host="0.0.0.0", token=None, password_hash="hash")
    validate_server_auth_config(host="0.0.0.0", token=None, allow_initial_setup=True)


def test_password_hash_round_trip() -> None:
    password_hash = hash_password("secret-password")

    assert password_matches(password_hash=password_hash, supplied="secret-password") is True
    assert password_matches(password_hash=password_hash, supplied="wrong-password") is False
