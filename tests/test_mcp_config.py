from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dormammu.config import AppConfig
from dormammu.mcp import (
    McpFailurePolicy,
    McpStdioTransport,
    McpStreamableHttpTransport,
    McpTransportKind,
)


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
    enabled: bool = True,
    transport: dict[str, object] | None = None,
    profiles: list[str] | None = None,
    failure_policy: str = "fail",
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": server_id,
        "enabled": enabled,
        "transport": transport
        or {
            "kind": "stdio",
            "command": "npx",
            "args": ["-y", f"@mcp/{server_id}"],
        },
        "access": {"profiles": profiles or ["developer"]},
        "failure_policy": failure_policy,
        "metadata": metadata or {"owner": "platform"},
    }


def test_mcp_catalog_is_empty_when_no_mcp_config_exists(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    config = _make_config(repo_root, home_dir)

    assert config.mcp is not None
    assert config.mcp.layers == ()
    assert config.mcp.servers == ()
    assert config.mcp.shadowed == ()


def test_mcp_catalog_loads_project_config_and_normalizes_transport(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    _server_payload(
                        "github",
                        transport={
                            "kind": "stdio",
                            "command": "uvx",
                            "args": ["mcp-server-github"],
                            "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
                            "cwd": "./tools/mcp",
                        },
                        profiles=["developer", "reviewer"],
                        failure_policy="warn",
                        metadata={"owner": "platform", "team": "code"},
                    ),
                    _server_payload(
                        "docs",
                        enabled=False,
                        transport={
                            "kind": "streamable_http",
                            "url": "https://mcp.example.test",
                            "headers": {"Authorization": "Bearer test"},
                        },
                        profiles=["planner"],
                        failure_policy="ignore",
                    ),
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)

    assert config.config_file == config_path
    assert config.mcp is not None
    assert [layer.scope for layer in config.mcp.layers] == ["project"]
    assert [server.id for server in config.mcp.servers] == ["github", "docs"]

    github = config.mcp.definitions_by_id()["github"]
    assert github.scope == "project"
    assert github.config_path == config_path
    assert github.enabled is True
    assert github.definition.failure_policy is McpFailurePolicy.WARN
    assert github.definition.access.profiles == ("developer", "reviewer")
    assert github.definition.metadata == {"owner": "platform", "team": "code"}
    assert isinstance(github.definition.transport, McpStdioTransport)
    assert github.definition.transport.kind is McpTransportKind.STDIO
    assert github.definition.transport.command == "uvx"
    assert github.definition.transport.args == ("mcp-server-github",)
    assert github.definition.transport.env == {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    assert github.definition.transport.cwd == (repo_root / "tools" / "mcp").resolve()
    assert github.is_visible_to_profile("developer") is True
    assert github.is_visible_to_profile("planner") is False

    docs_server = config.mcp.definitions_by_id()["docs"]
    assert docs_server.enabled is False
    assert docs_server.definition.failure_policy is McpFailurePolicy.IGNORE
    assert isinstance(docs_server.definition.transport, McpStreamableHttpTransport)
    assert config.mcp.enabled_servers() == (github,)

    payload = config.to_dict()
    assert payload["mcp"] is not None
    assert payload["mcp"]["servers"][0]["id"] == "github"
    assert payload["mcp"]["servers"][1]["definition"]["transport"]["kind"] == "streamable_http"


def test_mcp_catalog_preserves_repeated_stdio_args(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    _server_payload(
                        "github",
                        transport={
                            "kind": "stdio",
                            "command": "uvx",
                            "args": ["--flag", "A", "--flag", "B"],
                        },
                    )
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)

    github = config.mcp.definitions_by_id()["github"]
    assert isinstance(github.definition.transport, McpStdioTransport)
    assert github.definition.transport.args == ("--flag", "A", "--flag", "B")


def test_mcp_catalog_prefers_project_over_global_by_server_id(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    global_config_path = _write_json(
        home_dir / ".dormammu" / "config",
        {
            "mcp": {
                "servers": [
                    _server_payload("shared", profiles=["developer"]),
                    _server_payload("global-only", profiles=["reviewer"]),
                ]
            }
        },
    )
    project_config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    _server_payload(
                        "shared",
                        transport={
                            "kind": "sse",
                            "url": "https://project.example.test/sse",
                        },
                        profiles=["planner"],
                    ),
                    _server_payload("project-only", profiles=["developer"]),
                ]
            }
        },
    )

    config = _make_config(repo_root, home_dir)

    assert config.mcp is not None
    assert [layer.scope for layer in config.mcp.layers] == ["global", "project"]
    assert [server.id for server in config.mcp.servers] == ["shared", "global-only", "project-only"]
    assert config.mcp.definitions_by_id()["shared"].scope == "project"
    assert config.mcp.definitions_by_id()["shared"].config_path == project_config_path
    assert config.mcp.shadowed[0].scope == "global"
    assert config.mcp.shadowed[0].config_path == global_config_path


def test_mcp_catalog_uses_explicit_config_path_as_full_source(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        home_dir / ".dormammu" / "config",
        {"mcp": {"servers": [_server_payload("global-only", profiles=["developer"])]}},
    )
    _write_json(
        repo_root / "dormammu.json",
        {"mcp": {"servers": [_server_payload("project-only", profiles=["developer"])]}},
    )
    explicit_config_path = _write_json(
        repo_root / "ops" / "dormammu.explicit.json",
        {"mcp": {"servers": [_server_payload("explicit-only", profiles=["reviewer"])]}},
    )

    config = AppConfig.load(
        repo_root=repo_root,
        env={
            "HOME": str(home_dir),
            "DORMAMMU_CONFIG_PATH": str(explicit_config_path),
            **{key: value for key, value in os.environ.items() if key != "HOME"},
        },
    )

    assert config.config_file == explicit_config_path
    assert config.mcp is not None
    assert [layer.scope for layer in config.mcp.layers] == ["explicit"]
    assert [server.id for server in config.mcp.servers] == ["explicit-only"]
    assert config.mcp.shadowed == ()


def test_mcp_catalog_reports_missing_required_transport_field(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    {
                        "id": "broken",
                        "transport": {"kind": "stdio"},
                        "access": {"profiles": ["developer"]},
                    }
                ]
            }
        },
    )

    with pytest.raises(
        RuntimeError,
        match=rf"mcp\.servers\[0\]\.transport\.command must be a non-empty string in {config_path}",
    ):
        _make_config(repo_root, home_dir)


def test_mcp_catalog_reports_invalid_field_type(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    _server_payload(
                        "broken",
                        transport={"kind": "stdio", "command": "npx", "args": "not-a-list"},
                    )
                ]
            }
        },
    )

    with pytest.raises(
        RuntimeError,
        match=rf"mcp\.servers\[0\]\.transport\.args must be a JSON array in {config_path}",
    ):
        _make_config(repo_root, home_dir)


def test_mcp_catalog_rejects_unknown_profile_reference(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    _server_payload("github", profiles=["missing-profile"])
                ]
            }
        },
    )

    with pytest.raises(
        RuntimeError,
        match=rf"mcp\.servers\[0\]\.access\.profiles\[0\] references unknown profile 'missing-profile' in {config_path}",
    ):
        _make_config(repo_root, home_dir)


def test_mcp_catalog_rejects_duplicate_server_ids_within_one_layer(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "mcp": {
                "servers": [
                    _server_payload("dup", profiles=["developer"]),
                    _server_payload("dup", profiles=["reviewer"]),
                ]
            }
        },
    )

    with pytest.raises(
        RuntimeError,
        match=rf"Duplicate MCP server id 'dup' in project MCP config {config_path}",
    ):
        _make_config(repo_root, home_dir)
