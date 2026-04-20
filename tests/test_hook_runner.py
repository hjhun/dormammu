from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from dormammu.config import AppConfig
from dormammu.hook_runner import HookExecutionError, HookRunner
from dormammu.hooks import HookEventName, HookInputPayload, HookResult, HookResultAction


def _make_config(repo_root: Path, home_dir: Path) -> AppConfig:
    return AppConfig.load(
        repo_root=repo_root,
        env={
            "HOME": str(home_dir),
            **{key: value for key, value in os.environ.items() if key != "HOME"},
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.resolve()


def _hook_payload(
    name: str,
    *,
    kind: str = "builtin",
    ref: str | None = None,
    event: str = "stage start",
    execution_mode: str = "sync",
    enabled: bool = True,
    settings: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "event": event,
        "execution_mode": execution_mode,
        "enabled": enabled,
        "target": {
            "kind": kind,
            "ref": ref or f"hooks.{name}",
        },
    }
    if settings is not None:
        target = payload["target"]
        assert isinstance(target, dict)
        target["settings"] = settings
    return payload


def _hook_input(event: HookEventName = HookEventName.STAGE_START) -> HookInputPayload:
    return HookInputPayload(
        event=event,
        session_id="session-123",
        run_id="run-456",
        agent_role="developer",
        payload={"phase": "design"},
        metadata={"attempt": 1},
    )


def test_hook_runner_executes_successful_sync_command_hook(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload(
                    "command-audit",
                    kind="command",
                    ref=sys.executable,
                    settings={
                        "args": [
                            "-c",
                            (
                                "import json, sys; "
                                "payload = json.load(sys.stdin); "
                                "print(json.dumps({'action': 'allow', 'message': payload['payload']['phase']}))"
                            ),
                        ]
                    },
                )
            ]
        },
    )

    config = _make_config(repo_root, home_dir)
    runner = HookRunner(config)

    result = runner.run_sync(_hook_input())

    assert result.blocked is False
    assert [item.hook.name for item in result.executed] == ["command-audit"]
    assert result.executed[0].result.action is HookResultAction.ALLOW
    assert result.executed[0].result.message == "design"
    assert result.executed[0].diagnostics["executor"] == "command"
    assert result.executed[0].diagnostics["exit_code"] == 0


def test_hook_runner_executes_multiple_matching_hooks_in_effective_catalog_order(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        home_dir / ".dormammu" / "config",
        {
            "hooks": [
                _hook_payload("alpha"),
                _hook_payload("shared", ref="global.shared"),
                _hook_payload("disabled", enabled=False),
            ]
        },
    )
    _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("shared", ref="project.shared"),
                _hook_payload("omega"),
                _hook_payload("ignored-async", execution_mode="async"),
            ]
        },
    )
    config = _make_config(repo_root, home_dir)
    called: list[str] = []

    def _handler(message: str):
        def run(_payload: HookInputPayload, hook) -> HookResult:
            called.append(hook.name)
            return HookResult(action=HookResultAction.ALLOW, message=message)

        return run

    runner = HookRunner(
        config,
        builtin_handlers={
            "hooks.alpha": _handler("alpha"),
            "project.shared": _handler("shared"),
            "hooks.omega": _handler("omega"),
        },
    )

    result = runner.run_sync(_hook_input())

    assert [hook.name for hook in result.selected_hooks] == ["alpha", "shared", "omega"]
    assert [item.hook.name for item in result.executed] == ["alpha", "shared", "omega"]
    assert called == ["alpha", "shared", "omega"]


def test_hook_runner_wraps_non_json_serializable_command_input(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload(
                    "command-audit",
                    kind="command",
                    ref=sys.executable,
                    settings={"args": ["-c", "print('should not run')"]},
                )
            ]
        },
    )

    config = _make_config(repo_root, home_dir)
    runner = HookRunner(config)
    hook_input = HookInputPayload(
        event=HookEventName.STAGE_START,
        session_id="session-123",
        run_id="run-456",
        agent_role="developer",
        payload={"path": Path("/tmp/x")},
        metadata={"attempt": 1},
    )

    with pytest.raises(
        HookExecutionError,
        match=r"Command hook input could not be JSON-serialized for hook 'command-audit'",
    ):
        runner.run_sync(hook_input)


def test_hook_runner_stops_after_first_blocking_deny_result(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("allow-first"),
                _hook_payload("deny-second"),
                _hook_payload("never-run"),
            ]
        },
    )
    config = _make_config(repo_root, home_dir)
    called: list[str] = []

    def _allow(_payload: HookInputPayload, hook) -> HookResult:
        called.append(hook.name)
        return HookResult(action=HookResultAction.ALLOW, message="ok")

    def _deny(_payload: HookInputPayload, hook) -> HookResult:
        called.append(hook.name)
        return HookResult(action=HookResultAction.DENY, message="blocked")

    def _unexpected(_payload: HookInputPayload, hook) -> HookResult:
        called.append(hook.name)
        return HookResult(action=HookResultAction.ALLOW, message="unexpected")

    runner = HookRunner(
        config,
        builtin_handlers={
            "hooks.allow-first": _allow,
            "hooks.deny-second": _deny,
            "hooks.never-run": _unexpected,
        },
    )

    result = runner.run_sync(_hook_input())

    assert result.blocked is True
    assert result.blocking_record is not None
    assert result.blocking_record.hook.name == "deny-second"
    assert [item.hook.name for item in result.executed] == ["allow-first", "deny-second"]
    assert called == ["allow-first", "deny-second"]


def test_hook_runner_preserves_warn_and_annotate_results(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("warn-hook"),
                _hook_payload("annotate-hook"),
            ]
        },
    )
    config = _make_config(repo_root, home_dir)

    runner = HookRunner(
        config,
        builtin_handlers={
            "hooks.warn-hook": lambda _payload, _hook: {
                "action": "warn",
                "message": "soft warning",
                "annotations": {"severity": "medium"},
            },
            "hooks.annotate-hook": lambda _payload, _hook: {
                "action": "annotate",
                "message": "added annotation",
                "annotations": {"owner": "policy"},
            },
        },
    )

    result = runner.run_sync(_hook_input())

    assert result.blocked is False
    assert [item.result.action for item in result.executed] == [
        HookResultAction.WARN,
        HookResultAction.ANNOTATE,
    ]
    assert result.executed[0].result.annotations == {"severity": "medium"}
    assert result.executed[1].result.annotations == {"owner": "policy"}


def test_hook_runner_preserves_background_started_results(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("background-hook"),
            ]
        },
    )
    config = _make_config(repo_root, home_dir)

    runner = HookRunner(
        config,
        builtin_handlers={
            "hooks.background-hook": lambda _payload, _hook: {
                "action": "background_started",
                "message": "audit job queued",
                "background_job": {
                    "job_id": "audit-1",
                    "kind": "audit-export",
                    "metadata": {"owner": "policy"},
                },
            },
        },
    )

    result = runner.run_sync(_hook_input())

    assert result.blocked is False
    assert [item.result.action for item in result.executed] == [
        HookResultAction.BACKGROUND_STARTED,
    ]
    background_job = result.executed[0].result.background_job
    assert background_job is not None
    assert background_job.job_id == "audit-1"
    assert background_job.kind == "audit-export"
    assert background_job.metadata == {"owner": "policy"}


def test_hook_runner_fails_clearly_on_malformed_output(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("broken"),
            ]
        },
    )
    config = _make_config(repo_root, home_dir)
    runner = HookRunner(
        config,
        builtin_handlers={
            "hooks.broken": lambda _payload, _hook: {"message": "missing action"},
        },
    )

    with pytest.raises(
        HookExecutionError,
        match=r"Malformed hook output from hook 'broken'",
    ):
        runner.run_sync(_hook_input())
