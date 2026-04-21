from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from dormammu.config import AppConfig
from dormammu.hook_runner import HookRunner
from dormammu.mcp_runtime import (
    McpAccessBlockedError,
    McpAccessBoundary,
    McpAccessRequest,
    McpAccessStatus,
    McpAccessReason,
    McpAccessDeniedError,
    McpServerUnavailableError,
)
from dormammu.runtime_hooks import RuntimeHookController


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


def _server_payload(
    server_id: str,
    *,
    command: str = sys.executable,
    enabled: bool = True,
    profiles: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": server_id,
        "enabled": enabled,
        "transport": {
            "kind": "stdio",
            "command": command,
            "args": ["-m", "example"],
        },
        "access": {"profiles": profiles or ["developer"]},
    }


def _config_payload(
    *,
    hooks: list[dict[str, object]] | None = None,
    mcp_servers: list[dict[str, object]] | None = None,
    developer_permission_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "mcp": {"servers": mcp_servers or [_server_payload("github")]},
    }
    if developer_permission_policy is not None:
        payload["agents"] = {
            "developer": {
                "permission_policy": developer_permission_policy,
            }
        }
    if hooks is not None:
        payload["hooks"] = hooks
    return payload


def _tool_hook_payload(name: str, ref: str) -> dict[str, object]:
    return {
        "name": name,
        "event": "tool execution",
        "execution_mode": "sync",
        "enabled": True,
        "target": {"kind": "builtin", "ref": ref},
    }


def _request() -> McpAccessRequest:
    return McpAccessRequest(
        server_id="github",
        profile="developer",
        source="test-suite",
        session_id="session-123",
        run_id="run-456",
        agent_role="developer",
    )


def test_mcp_access_boundary_allows_visible_and_permitted_server(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            developer_permission_policy={
                "tools": {
                    "default": "deny",
                    "rules": [{"tool": "mcp", "decision": "allow"}],
                }
            },
        ),
    )

    config = _make_config(repo_root, home_dir)
    boundary = McpAccessBoundary(config)

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.READY
    assert result.reason is None
    assert result.server is not None
    assert result.server.id == "github"
    assert result.permission is not None
    assert result.permission.decision.value == "allow"
    assert result.permission.matched_tool_name == "mcp"
    assert result.hook_summary is None
    assert result.availability is not None
    assert result.availability.available is True
    assert boundary.require_access(_request()).status is McpAccessStatus.READY


def test_mcp_access_boundary_denies_server_hidden_from_profile(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            developer_permission_policy={
                "tools": {
                    "rules": [{"tool": "mcp", "decision": "allow"}],
                }
            },
            mcp_servers=[_server_payload("github", profiles=["reviewer"])],
        ),
    )

    config = _make_config(repo_root, home_dir)
    boundary = McpAccessBoundary(config)

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.DENIED
    assert result.reason is McpAccessReason.PROFILE_DENIED
    assert "MCP access configuration" in result.message


def test_mcp_access_boundary_denies_server_by_tool_permission(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            developer_permission_policy={
                "tools": {
                    "default": "deny",
                    "rules": [{"tool": "mcp", "decision": "deny"}],
                }
            },
        ),
    )

    config = _make_config(repo_root, home_dir)
    boundary = McpAccessBoundary(config)

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.DENIED
    assert result.reason is McpAccessReason.PERMISSION_DENIED
    assert result.permission is not None
    assert result.permission.matched_tool_name == "mcp"

    with pytest.raises(McpAccessDeniedError, match=r"denied for profile 'developer'"):
        boundary.require_access(_request())


def test_mcp_access_boundary_honors_server_specific_permission_rule(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            developer_permission_policy={
                "tools": {
                    "default": "deny",
                    "rules": [
                        {"tool": "mcp", "decision": "allow"},
                        {"tool": "mcp:github", "decision": "deny"},
                    ],
                }
            },
        ),
    )

    config = _make_config(repo_root, home_dir)
    boundary = McpAccessBoundary(config)

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.DENIED
    assert result.reason is McpAccessReason.PERMISSION_DENIED
    assert result.permission is not None
    assert result.permission.matched_tool_name == "mcp:github"
    assert result.permission.source == "server_rule"


def test_mcp_access_boundary_surfaces_hook_block_and_annotations(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            hooks=[
                _tool_hook_payload("annotate", "hooks.annotate"),
                _tool_hook_payload("block", "hooks.block"),
            ],
            developer_permission_policy={
                "tools": {
                    "default": "deny",
                    "rules": [{"tool": "mcp", "decision": "allow"}],
                }
            },
        ),
    )

    config = _make_config(repo_root, home_dir)
    hook_runner = HookRunner(
        config,
        builtin_handlers={
            "hooks.annotate": lambda payload, _hook: {
                "action": "annotate",
                "message": "annotated mcp request",
                "annotations": {
                    "tool_target": payload.payload["tool_target"],
                    "phase": payload.payload["operation"],
                },
            },
            "hooks.block": lambda _payload, _hook: {
                "action": "deny",
                "message": "policy hook blocked server",
            },
        },
    )
    boundary = McpAccessBoundary(
        config,
        hook_controller=RuntimeHookController(config, runner=hook_runner),
    )

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.BLOCKED
    assert result.reason is McpAccessReason.HOOK_BLOCKED
    assert result.hook_summary is not None
    assert result.hook_summary.blocked is True
    assert result.hook_summary.annotations == (
        {
            "hook": "annotate",
            "annotations": {"tool_target": "mcp:github", "phase": "invoke_server"},
            "message": "annotated mcp request",
        },
    )
    assert result.hook_summary.message == "policy hook blocked server"

    with pytest.raises(McpAccessBlockedError, match="blocked by runtime hook"):
        boundary.require_access(_request())


def test_mcp_access_boundary_surfaces_hook_annotations_on_ready_result(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            hooks=[_tool_hook_payload("annotate", "hooks.annotate")],
            developer_permission_policy={
                "tools": {
                    "default": "deny",
                    "rules": [{"tool": "mcp", "decision": "allow"}],
                }
            },
        ),
    )

    config = _make_config(repo_root, home_dir)
    hook_runner = HookRunner(
        config,
        builtin_handlers={
            "hooks.annotate": lambda payload, _hook: {
                "action": "annotate",
                "message": "annotated only",
                "annotations": {"tool_target": payload.payload["tool_target"]},
            },
        },
    )
    boundary = McpAccessBoundary(
        config,
        hook_controller=RuntimeHookController(config, runner=hook_runner),
    )

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.READY
    assert result.hook_summary is not None
    assert result.hook_summary.blocked is False
    assert result.hook_summary.annotations == (
        {
            "hook": "annotate",
            "annotations": {"tool_target": "mcp:github"},
            "message": "annotated only",
        },
    )


def test_mcp_access_boundary_reports_unavailable_stdio_server(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            developer_permission_policy={
                "tools": {
                    "default": "deny",
                    "rules": [{"tool": "mcp", "decision": "allow"}],
                }
            },
            mcp_servers=[
                _server_payload(
                    "github",
                    command="definitely-missing-mcp-command-for-test",
                )
            ],
        ),
    )

    config = _make_config(repo_root, home_dir)
    boundary = McpAccessBoundary(config)

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.UNAVAILABLE
    assert result.reason is McpAccessReason.SERVER_UNAVAILABLE
    assert result.availability is not None
    assert result.availability.available is False
    assert "was not found in PATH" in result.message

    with pytest.raises(McpServerUnavailableError, match="was not found in PATH"):
        boundary.require_access(_request())
