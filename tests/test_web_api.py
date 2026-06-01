from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dormammu.config import AppConfig
from dormammu.web.auth import hash_password
from dormammu.web.app import build_dormammu_terminal_command, create_app


def _seed_repo(root: Path) -> None:
    (root / "AGENTS.md").write_text("repo\n", encoding="utf-8")


def _app_config(root: Path) -> AppConfig:
    env = dict(os.environ)
    env["HOME"] = str(root / "home")
    return AppConfig.load(repo_root=root, env=env)


def _write_daemon_config(config: AppConfig, *, goals: bool = True) -> Path:
    path = config.home_dir / ".dormammu" / "daemonize.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema_version": 1,
        "prompt_path": str(config.home_dir / "queue" / "prompts"),
        "result_path": str(config.home_dir / "queue" / "results"),
    }
    if goals:
        payload["goals"] = {
            "path": str(config.home_dir / "goals"),
            "interval_minutes": 5,
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_config_api_requires_token(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    client = testclient.TestClient(create_app(_app_config(tmp_path), token="secret"))

    unauthorized = client.get("/api/config")
    authorized = client.get("/api/config", headers={"Authorization": "Bearer secret"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_login_api_validates_token(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    client = testclient.TestClient(create_app(_app_config(tmp_path), token="secret"))

    rejected = client.post("/api/auth/login", json={"token": "wrong"})
    accepted = client.post("/api/auth/login", json={"token": "secret"})

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"ok": True}


def test_auth_setup_creates_password_hash(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    client = testclient.TestClient(create_app(_app_config(tmp_path), token=None))

    state = client.get("/api/auth/state")
    short = client.post("/api/auth/setup", json={"password": "short"})
    created = client.post("/api/auth/setup", json={"password": "secret-password"})
    repeated = client.post("/api/auth/setup", json={"password": "another-password"})
    login = client.post("/api/auth/login", json={"token": "secret-password"})

    payload = (tmp_path / "dormammu.json").read_text(encoding="utf-8")
    assert state.json()["setup_required"] is True
    assert short.status_code == 400
    assert created.status_code == 200
    assert repeated.status_code == 409
    assert "password_hash" in payload
    assert "secret-password" not in payload
    assert login.status_code == 200


def test_login_api_accepts_configured_password(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    (tmp_path / "dormammu.json").write_text(
        '{"web": {"password_hash": "%s"}}\n' % hash_password("secret-password"),
        encoding="utf-8",
    )
    client = testclient.TestClient(create_app(_app_config(tmp_path), token=None))

    rejected = client.post("/api/auth/login", json={"token": "wrong"})
    accepted = client.post("/api/auth/login", json={"token": "secret-password"})
    config = client.get("/api/config", headers={"Authorization": "Bearer secret-password"})

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert config.status_code == 200


def test_raw_config_api_preserves_masked_secrets(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    (tmp_path / "dormammu.json").write_text(
        '{"telegram": {"bot_token": "secret"}, "web": {"password_hash": "%s", "host": "127.0.0.1"}}\n'
        % hash_password("secret-password"),
        encoding="utf-8",
    )
    client = testclient.TestClient(create_app(_app_config(tmp_path), token=None))

    settings = client.get("/api/config", headers={"Authorization": "Bearer secret-password"}).json()
    raw_json = settings["raw_json"].replace('"host": "127.0.0.1"', '"host": "0.0.0.0"')
    response = client.patch(
        "/api/config/raw",
        json={"raw_json": raw_json},
        headers={"Authorization": "Bearer secret-password"},
    )

    payload = (tmp_path / "dormammu.json").read_text(encoding="utf-8")
    assert response.status_code == 200
    assert '"bot_token": "secret"' in payload
    assert '"password_hash": "***"' not in payload
    assert '"host": "0.0.0.0"' in payload


def test_terminal_create_rejects_invalid_cwd(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    client = testclient.TestClient(create_app(_app_config(tmp_path), token="secret"))

    response = client.post(
        "/api/terminal/sessions",
        json={"cwd": str(outside)},
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 400


def test_terminal_input_endpoint_validates_command(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    client = testclient.TestClient(create_app(_app_config(tmp_path), token="secret"))

    empty = client.post(
        "/api/terminal/sessions/missing/input",
        json={"command": ""},
        headers={"Authorization": "Bearer secret"},
    )
    missing = client.post(
        "/api/terminal/sessions/missing/input",
        json={"command": "pwd"},
        headers={"Authorization": "Bearer secret"},
    )
    unauthorized = client.post("/api/terminal/sessions/missing/input", json={"command": "pwd"})

    assert empty.status_code == 400
    assert missing.status_code == 404
    assert unauthorized.status_code == 401


def test_dormammu_terminal_command_builder_quotes_prompt(tmp_path: Path) -> None:
    command = build_dormammu_terminal_command(
        mode="run",
        repo_root=tmp_path,
        prompt="review this repo; echo unsafe",
    )

    assert command == f"dormammu run --repo-root {tmp_path} --prompt 'review this repo; echo unsafe'"
    assert build_dormammu_terminal_command(mode="resume", repo_root=tmp_path) == f"dormammu resume --repo-root {tmp_path}"


def test_dormammu_terminal_command_builder_requires_prompt(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_dormammu_terminal_command(mode="run", repo_root=tmp_path)


def test_daemon_api_manages_queue_prompts_and_goals(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    config = _app_config(tmp_path)
    _write_daemon_config(config)
    client = testclient.TestClient(create_app(config, token="secret"))
    headers = {"Authorization": "Bearer secret"}

    status = client.get("/api/daemon/status", headers=headers)
    queued = client.post("/api/daemon/queue", json={"text": "Implement queue UI"}, headers=headers)
    prompts = client.get("/api/daemon/prompts", headers=headers)
    filename = queued.json()["prompt"]["filename"]
    prompt = client.get(f"/api/daemon/prompts/{filename}", headers=headers)
    updated = client.put(
        f"/api/daemon/prompts/{filename}",
        json={"content": "Implement queue UI\n\nWith details."},
        headers=headers,
    )
    queued_second = client.post("/api/daemon/queue", json={"text": "Second queue item"}, headers=headers)
    goal = client.post("/api/daemon/goals", json={"content": "Add daemon dashboard"}, headers=headers)
    goals = client.get("/api/daemon/goals", headers=headers)
    deleted_prompt = client.post(
        "/api/daemon/queue/delete",
        json={"filenames": [filename, queued_second.json()["prompt"]["filename"]]},
        headers=headers,
    )
    deleted_goal = client.delete(f"/api/daemon/goals/{goal.json()['goal']['filename']}", headers=headers)

    assert status.status_code == 200
    assert status.json()["queue_depth"] == 0
    assert queued.status_code == 200
    assert prompts.status_code == 200
    assert prompt.json()["content"] == "Implement queue UI\n"
    assert updated.json()["prompt"]["content"] == "Implement queue UI\n\nWith details.\n"
    assert queued_second.status_code == 200
    assert goal.status_code == 200
    assert goals.status_code == 200
    assert len(goals.json()["goals"]) == 1
    assert deleted_prompt.status_code == 200
    assert len(deleted_prompt.json()["deleted"]) == 2
    assert deleted_goal.status_code == 200


def test_daemon_api_rejects_path_traversal(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    config = _app_config(tmp_path)
    _write_daemon_config(config)
    client = testclient.TestClient(create_app(config, token="secret"))

    response = client.put(
        "/api/daemon/prompts/../escape.md",
        json={"content": "bad"},
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code in {400, 404}


def test_daemon_start_and_stop_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    _seed_repo(tmp_path)
    config = _app_config(tmp_path)
    _write_daemon_config(config)
    client = testclient.TestClient(create_app(config, token="secret"))
    calls: list[list[str]] = []

    class FakeProcess:
        pid = 4321

    def fake_popen(command, **kwargs):
        calls.append(list(command))
        pid_path = config.results_dir.parent / "daemon.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text("4321", encoding="utf-8")
        return FakeProcess()

    stopped: list[int] = []

    def fake_kill(pid: int, signal_number: int) -> None:
        stopped.append(pid)

    monkeypatch.setattr("dormammu.web.app.subprocess.Popen", fake_popen)
    monkeypatch.setattr("os.kill", fake_kill)

    started = client.post("/api/daemon/start", headers={"Authorization": "Bearer secret"})
    stopped_response = client.post("/api/daemon/stop", headers={"Authorization": "Bearer secret"})

    assert started.status_code == 200
    assert started.json()["started"] is True
    assert calls and calls[0][3] == "daemonize"
    assert stopped_response.status_code == 200
    assert stopped == [4321]
