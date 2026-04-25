from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config
from dormammu.operator_services import (
    ConfigOperatorService,
    DaemonOperatorService,
    GoalsOperatorService,
)


def _seed_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")


def _app_config(root: Path) -> AppConfig:
    return AppConfig.load(repo_root=root, env={"HOME": str(root / "home")})


def _write_daemon_config(root: Path, *, include_goals: bool = True) -> Path:
    payload: dict[str, object] = {
        "schema_version": 1,
        "prompt_path": str(root / "queue" / "prompts"),
        "result_path": str(root / "queue" / "results"),
    }
    if include_goals:
        payload["goals"] = {"path": str(root / "goals"), "interval_minutes": 60}
    path = root / "daemonize.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_config_operator_service_reads_and_updates_config(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    config = _app_config(tmp_path)
    service = ConfigOperatorService(config)

    path = service.set_value("active_agent_cli", value="/usr/bin/codex")

    assert path == tmp_path / "dormammu.json"
    updated = ConfigOperatorService(_app_config(tmp_path))
    assert updated.get("active_agent_cli") == "/usr/bin/codex"
    assert updated.resolved_config()["repo_root"] == str(tmp_path)


def test_daemon_operator_service_reports_status_and_queue(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    config = _app_config(tmp_path)
    daemon_config = load_daemon_config(_write_daemon_config(tmp_path), app_config=config)
    service = DaemonOperatorService(config, daemon_config=daemon_config)

    first = service.enqueue_prompt("first prompt", source="test")
    (daemon_config.prompt_path / "002-second.md").write_text("second\n", encoding="utf-8")
    service.heartbeat_path().parent.mkdir(parents=True, exist_ok=True)
    service.heartbeat_path().write_text('{"status": "completed"}', encoding="utf-8")

    queued = service.list_queue()
    status = service.status()

    assert first in queued
    assert [path.name for path in queued] == ["002-second.md", first.name]
    assert status.queue_depth == 2
    assert status.heartbeat_payload == {"status": "completed"}


def test_goals_operator_service_saves_lists_and_deletes_goals(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    config = _app_config(tmp_path)
    daemon_config = load_daemon_config(_write_daemon_config(tmp_path), app_config=config)
    service = GoalsOperatorService(daemon_config)

    saved = service.save_goal("Add Metrics Endpoint\n\nDetails", date_str="20260425")

    assert saved.name == "20260425_add-metrics-endpoint.md"
    assert service.list_goals() == (saved,)

    service.delete_goal(saved)

    assert service.list_goals() == ()
