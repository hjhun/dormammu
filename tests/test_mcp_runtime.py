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
    McpRuntimeAdapter,
    McpRuntimeFailureReason,
    McpRuntimeInvocationError,
    McpRuntimeRequest,
    McpRuntimeResponse,
    McpRuntimeStatus,
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


def test_mcp_access_boundary_reports_server_not_configured_when_catalog_is_empty(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    config = _make_config(repo_root, home_dir)
    boundary = McpAccessBoundary(config)

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.UNAVAILABLE
    assert result.reason is McpAccessReason.SERVER_NOT_CONFIGURED
    assert result.server is None
    assert result.permission is None
    assert result.hook_summary is None
    assert result.availability is None
    assert result.diagnostics["tool_target"] == "mcp:github"

    with pytest.raises(McpServerUnavailableError, match="is not configured"):
        boundary.require_access(_request())


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


def test_mcp_access_boundary_reports_disabled_server(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            mcp_servers=[_server_payload("github", enabled=False)],
        ),
    )

    config = _make_config(repo_root, home_dir)
    boundary = McpAccessBoundary(config)

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.UNAVAILABLE
    assert result.reason is McpAccessReason.SERVER_DISABLED
    assert result.server is not None
    assert result.server.id == "github"
    assert result.permission is None
    assert result.hook_summary is None
    assert result.availability is None
    assert "configured but disabled" in result.message

    with pytest.raises(McpServerUnavailableError, match="configured but disabled"):
        boundary.require_access(_request())


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


def test_mcp_access_boundary_reports_permission_ask_for_server(tmp_path: Path) -> None:
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
                    "rules": [{"tool": "mcp", "decision": "ask"}],
                }
            },
        ),
    )

    config = _make_config(repo_root, home_dir)
    boundary = McpAccessBoundary(config)

    result = boundary.evaluate_access(_request())

    assert result.status is McpAccessStatus.DENIED
    assert result.reason is McpAccessReason.PERMISSION_ASK
    assert result.permission is not None
    assert result.permission.matched_tool_name == "mcp"
    assert result.permission.source == "family_rule"
    assert result.hook_summary is None
    assert result.availability is None
    assert "requires approval" in result.message

    with pytest.raises(McpAccessDeniedError, match="requires approval"):
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


def test_mcp_runtime_adapter_runs_stdio_interaction(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            mcp_servers=[
                _server_payload(
                    "github",
                    command=sys.executable,
                )
            ],
        ),
    )
    config_path = repo_root / "dormammu.json"
    config_path.write_text(
        json.dumps(
            {
                "mcp": {
                    "servers": [
                        {
                            "id": "github",
                            "enabled": True,
                            "transport": {
                                "kind": "stdio",
                                "command": sys.executable,
                                "args": [
                                    "-c",
                                    (
                                        "import sys; "
                                        "payload = sys.stdin.read(); "
                                        "sys.stderr.write('stderr-line\\n'); "
                                        "sys.stdout.write('echo:' + payload)"
                                    ),
                                ],
                                "env": {"MCP_MODE": "runtime-test"},
                            },
                            "access": {"profiles": ["developer"]},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]
    adapter = McpRuntimeAdapter()

    result = adapter.invoke(
        McpRuntimeRequest(
            server=server,
            operation="ping",
            payload={"jsonrpc": "2.0", "method": "ping"},
            stdin='{"jsonrpc":"2.0","method":"ping"}',
        )
    )

    assert result.status is McpRuntimeStatus.SUCCEEDED
    assert result.response is not None
    assert result.response.exit_code == 0
    assert result.response.stdout == 'echo:{"jsonrpc":"2.0","method":"ping"}'
    assert result.response.stderr == "stderr-line\n"
    assert result.interaction.transport_kind == "stdio"
    assert result.interaction.target["command"] == sys.executable
    assert result.interaction.target["env_keys"] == ["MCP_MODE"]
    assert result.to_dict()["request"]["stdin_present"] is True


def test_mcp_runtime_adapter_reports_missing_stdio_command(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            mcp_servers=[
                _server_payload(
                    "github",
                    command="definitely-missing-mcp-command-for-runtime-test",
                )
            ],
        ),
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]
    adapter = McpRuntimeAdapter()

    result = adapter.invoke(McpRuntimeRequest(server=server))

    assert result.status is McpRuntimeStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason is McpRuntimeFailureReason.COMMAND_NOT_FOUND
    assert result.diagnostics["target"]["command"] == "definitely-missing-mcp-command-for-runtime-test"

    with pytest.raises(McpRuntimeInvocationError, match="could not be started"):
        result.raise_for_status()


def test_mcp_runtime_adapter_reports_stdio_timeout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    {
                        "id": "github",
                        "enabled": True,
                        "transport": {
                            "kind": "stdio",
                            "command": sys.executable,
                            "args": ["-c", "import time; time.sleep(1)"],
                        },
                        "access": {"profiles": ["developer"]},
                    }
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]
    adapter = McpRuntimeAdapter()

    result = adapter.invoke(
        McpRuntimeRequest(
            server=server,
            operation="ping",
            timeout_seconds=0.01,
        )
    )

    assert result.status is McpRuntimeStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason is McpRuntimeFailureReason.TIMEOUT
    assert result.failure.diagnostics["timeout_seconds"] == 0.01
    assert result.diagnostics["target"]["command"] == sys.executable
    assert "timed out after 0.01 seconds" in result.message

    with pytest.raises(McpRuntimeInvocationError, match="timed out after 0.01 seconds"):
        result.raise_for_status()


def test_mcp_runtime_adapter_reports_nonzero_stdio_exit(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    {
                        "id": "github",
                        "enabled": True,
                        "transport": {
                            "kind": "stdio",
                            "command": sys.executable,
                            "args": [
                                "-c",
                                (
                                    "import sys; "
                                    "sys.stdout.write('partial output'); "
                                    "sys.stderr.write('runtime failed\\n'); "
                                    "raise SystemExit(7)"
                                ),
                            ],
                        },
                        "access": {"profiles": ["developer"]},
                    }
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]
    adapter = McpRuntimeAdapter()

    result = adapter.invoke(McpRuntimeRequest(server=server, operation="ping"))

    assert result.status is McpRuntimeStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason is McpRuntimeFailureReason.PROCESS_ERROR
    assert result.failure.diagnostics["returncode"] == 7
    assert result.failure.diagnostics["stdout"] == "partial output"
    assert result.failure.diagnostics["stderr"] == "runtime failed\n"
    assert result.diagnostics["target"]["command"] == sys.executable
    assert "failed with exit code 7" in result.message

    with pytest.raises(McpRuntimeInvocationError, match="failed with exit code 7"):
        result.raise_for_status()


def test_mcp_runtime_adapter_reports_permission_error_as_launch_error(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        _config_payload(
            mcp_servers=[
                _server_payload(
                    "github",
                    command=sys.executable,
                )
            ],
        ),
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]

    def _raise_permission_error(
        _request: McpRuntimeRequest,
        _interaction: object,
    ) -> object:
        raise PermissionError("permission denied")

    adapter = McpRuntimeAdapter(executors={"stdio": _raise_permission_error})

    result = adapter.invoke(McpRuntimeRequest(server=server))

    assert result.status is McpRuntimeStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason is McpRuntimeFailureReason.LAUNCH_ERROR
    assert result.failure.diagnostics["exception_type"] == "PermissionError"
    assert result.diagnostics["target"]["command"] == sys.executable
    assert "insufficient permissions" in result.message


def test_mcp_runtime_adapter_reports_unsupported_transport(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    {
                        "id": "github",
                        "enabled": True,
                        "transport": {
                            "kind": "streamable_http",
                            "url": "https://mcp.example.test",
                            "headers": {"Authorization": "Bearer test"},
                        },
                        "access": {"profiles": ["developer"]},
                    }
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]
    adapter = McpRuntimeAdapter()

    result = adapter.invoke(McpRuntimeRequest(server=server, operation="list_tools"))

    assert result.status is McpRuntimeStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason is McpRuntimeFailureReason.TRANSPORT_UNSUPPORTED
    assert result.interaction.target == {
        "url": "https://mcp.example.test",
        "header_keys": ["Authorization"],
    }


def test_mcp_runtime_adapter_handles_custom_http_executor_launch_failure(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    {
                        "id": "github",
                        "enabled": True,
                        "transport": {
                            "kind": "streamable_http",
                            "url": "https://mcp.example.test",
                            "headers": {"Authorization": "Bearer test"},
                        },
                        "access": {"profiles": ["developer"]},
                    }
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]

    def _raise_missing_target(
        _request: McpRuntimeRequest,
        _interaction: object,
    ) -> object:
        raise FileNotFoundError("helper not found")

    adapter = McpRuntimeAdapter(
        executors={"streamable_http": _raise_missing_target}
    )

    result = adapter.invoke(McpRuntimeRequest(server=server, operation="list_tools"))

    assert result.status is McpRuntimeStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason is McpRuntimeFailureReason.COMMAND_NOT_FOUND
    assert result.failure.diagnostics["exception_type"] == "FileNotFoundError"
    assert result.diagnostics["target"] == {
        "url": "https://mcp.example.test",
        "header_keys": ["Authorization"],
    }
    assert "https://mcp.example.test" in result.message


def test_mcp_runtime_adapter_reports_invalid_custom_executor_response(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    {
                        "id": "github",
                        "enabled": True,
                        "transport": {
                            "kind": "streamable_http",
                            "url": "https://mcp.example.test",
                            "headers": {"Authorization": "Bearer test"},
                        },
                        "access": {"profiles": ["developer"]},
                    }
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]
    adapter = McpRuntimeAdapter(
        executors={"streamable_http": lambda *_args: {"oops": "not-a-response"}}
    )

    result = adapter.invoke(McpRuntimeRequest(server=server, operation="list_tools"))

    assert result.status is McpRuntimeStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason is McpRuntimeFailureReason.EXECUTION_ERROR
    assert result.failure.diagnostics["response_type"] == "dict"
    assert result.diagnostics["target"] == {
        "url": "https://mcp.example.test",
        "header_keys": ["Authorization"],
    }
    assert "invalid response object" in result.message


@pytest.mark.parametrize(
    ("response", "invalid_field", "invalid_type"),
    [
        (
            McpRuntimeResponse(stdout=None),  # type: ignore[arg-type]
            "stdout",
            "NoneType",
        ),
        (
            McpRuntimeResponse(stderr=["bad"]),  # type: ignore[arg-type]
            "stderr",
            "list",
        ),
        (
            McpRuntimeResponse(exit_code="zero"),  # type: ignore[arg-type]
            "exit_code",
            "str",
        ),
    ],
)
def test_mcp_runtime_adapter_reports_invalid_custom_executor_response_fields(
    tmp_path: Path,
    response: McpRuntimeResponse,
    invalid_field: str,
    invalid_type: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    {
                        "id": "github",
                        "enabled": True,
                        "transport": {
                            "kind": "streamable_http",
                            "url": "https://mcp.example.test",
                            "headers": {"Authorization": "Bearer test"},
                        },
                        "access": {"profiles": ["developer"]},
                    }
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)
    server = config.mcp.definitions_by_id()["github"]
    adapter = McpRuntimeAdapter(executors={"streamable_http": lambda *_args: response})

    result = adapter.invoke(McpRuntimeRequest(server=server, operation="list_tools"))

    assert result.status is McpRuntimeStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason is McpRuntimeFailureReason.EXECUTION_ERROR
    assert result.failure.diagnostics["response_type"] == "McpRuntimeResponse"
    assert result.failure.diagnostics[f"{invalid_field}_type"] == invalid_type
    assert result.diagnostics["target"] == {
        "url": "https://mcp.example.test",
        "header_keys": ["Authorization"],
    }
    assert f"invalid response '{invalid_field}'" in result.message


def test_mcp_runtime_request_can_be_built_from_access_boundary_result(tmp_path: Path) -> None:
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
            mcp_servers=[
                {
                    "id": "github",
                    "enabled": True,
                    "transport": {
                        "kind": "stdio",
                        "command": sys.executable,
                        "args": [
                            "-c",
                            "import sys; sys.stdout.write('governed:' + sys.stdin.read())",
                        ],
                    },
                    "access": {"profiles": ["developer"]},
                }
            ],
        ),
    )

    config = _make_config(repo_root, home_dir)
    hook_runner = HookRunner(
        config,
        builtin_handlers={
            "hooks.annotate": lambda payload, _hook: {
                "action": "annotate",
                "message": "annotated request",
                "annotations": {"tool_target": payload.payload["tool_target"]},
            },
        },
    )
    boundary = McpAccessBoundary(
        config,
        hook_controller=RuntimeHookController(config, runner=hook_runner),
    )
    access_result = boundary.require_access(_request())
    adapter = McpRuntimeAdapter()

    runtime_request = McpRuntimeRequest.from_access_result(
        access_result,
        stdin="payload",
        metadata={"origin": "test"},
    )
    result = adapter.invoke(runtime_request)

    assert access_result.hook_summary is not None
    assert access_result.hook_summary.annotations == (
        {
            "hook": "annotate",
            "annotations": {"tool_target": "mcp:github"},
            "message": "annotated request",
        },
    )
    assert runtime_request.server.id == access_result.server.id
    assert runtime_request.metadata["origin"] == "test"
    assert result.status is McpRuntimeStatus.SUCCEEDED
    assert result.response is not None
    assert result.response.stdout == "governed:payload"
