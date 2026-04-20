from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dormammu.config import AppConfig
from dormammu.hooks import HookEventName, HookExecutorKind


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
    event: str = "stage start",
    ref: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "event": event,
        "target": {
            "kind": "builtin",
            "ref": ref or f"hooks.{name}",
        },
    }


def test_hook_catalog_is_empty_when_no_hook_config_exists(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    config = _make_config(repo_root, home_dir)

    assert config.hooks is not None
    assert config.hooks.layers == ()
    assert config.hooks.definitions == ()
    assert config.hooks.shadowed == ()


def test_hook_catalog_loads_global_hook_config(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    global_config_path = _write_json(
        home_dir / ".dormammu" / "config",
        {
            "hooks": [
                _hook_payload("global-audit", event="prompt intake"),
            ]
        },
    )

    config = _make_config(repo_root, home_dir)

    assert config.hooks is not None
    assert [layer.scope for layer in config.hooks.layers] == ["global"]
    assert len(config.hooks.definitions) == 1
    hook = config.hooks.definitions[0]
    assert hook.name == "global-audit"
    assert hook.scope == "global"
    assert hook.config_path == global_config_path
    assert hook.event is HookEventName.PROMPT_INTAKE
    assert hook.definition.target.kind is HookExecutorKind.BUILTIN


def test_hook_catalog_loads_project_hook_config(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    project_config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("project-guard", ref="policy.project_guard"),
            ]
        },
    )

    config = _make_config(repo_root, home_dir)

    assert config.hooks is not None
    assert [layer.scope for layer in config.hooks.layers] == ["project"]
    assert len(config.hooks.definitions) == 1
    hook = config.hooks.definitions[0]
    assert hook.name == "project-guard"
    assert hook.scope == "project"
    assert hook.config_path == project_config_path
    assert hook.definition.target.ref == "policy.project_guard"


def test_hook_catalog_prefers_project_hooks_over_global_hooks_by_name(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    global_config_path = _write_json(
        home_dir / ".dormammu" / "config",
        {
            "hooks": [
                _hook_payload("alpha", ref="global.alpha"),
                _hook_payload("shared", ref="global.shared"),
            ]
        },
    )
    project_config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("shared", ref="project.shared"),
                _hook_payload("omega", ref="project.omega"),
            ]
        },
    )

    config = _make_config(repo_root, home_dir)

    assert config.hooks is not None
    assert [item.name for item in config.hooks.definitions] == ["alpha", "shared", "omega"]
    definitions = config.hooks.definitions_by_name()
    assert definitions["alpha"].scope == "global"
    assert definitions["alpha"].config_path == global_config_path
    assert definitions["shared"].scope == "project"
    assert definitions["shared"].config_path == project_config_path
    assert definitions["shared"].definition.target.ref == "project.shared"
    assert definitions["omega"].scope == "project"
    assert len(config.hooks.shadowed) == 1
    assert config.hooks.shadowed[0].name == "shared"
    assert config.hooks.shadowed[0].scope == "global"


def test_hook_catalog_uses_explicit_config_path_as_full_source(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    _write_json(
        home_dir / ".dormammu" / "config",
        {
            "hooks": [
                _hook_payload("shared", ref="global.shared"),
                _hook_payload("global-only", ref="global.only"),
            ]
        },
    )
    _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("shared", ref="project.shared"),
                _hook_payload("project-only", ref="project.only"),
            ]
        },
    )
    explicit_config_path = _write_json(
        repo_root / "ops" / "dormammu.explicit.json",
        {
            "hooks": [
                _hook_payload("shared", ref="explicit.shared"),
                _hook_payload("explicit-only", ref="explicit.only"),
            ]
        },
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
    assert config.hooks is not None
    assert [layer.scope for layer in config.hooks.layers] == ["explicit"]
    assert [item.name for item in config.hooks.definitions] == ["shared", "explicit-only"]
    assert all(item.scope == "explicit" for item in config.hooks.definitions)
    assert config.hooks.definitions_by_name()["shared"].definition.target.ref == "explicit.shared"
    assert config.hooks.shadowed == ()


def test_hook_catalog_reports_malformed_hook_config_with_config_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    config_path = _write_json(
        repo_root / "dormammu.json",
        {
            "hooks": [
                _hook_payload("broken-hook", event="totally unknown"),
            ]
        },
    )

    with pytest.raises(
        RuntimeError,
        match=rf"hooks\[0\]\.event must be one of .* in {config_path}",
    ):
        _make_config(repo_root, home_dir)
