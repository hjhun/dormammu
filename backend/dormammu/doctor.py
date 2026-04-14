from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
from typing import Any


MINIMUM_PYTHON = (3, 10)


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    ok: bool
    summary: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class DoctorReport:
    status: str
    repo_root: Path
    home_dir: Path
    checks: tuple[DoctorCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "repo_root": str(self.repo_root),
            "home_dir": str(self.home_dir),
            "checks": [check.to_dict() for check in self.checks],
        }


def run_doctor(
    *,
    repo_root: Path,
    home_dir: Path | None = None,
    agent_cli: Path | None = None,
    active_agent_cli_from_config: Path | None = None,
) -> DoctorReport:
    resolved_home_dir = (
        home_dir
        or Path(os.environ.get("HOME", "")).expanduser()
        if os.environ.get("HOME")
        else Path.home()
    )
    checks = (
        _check_python_version(),
        _check_home_directory(resolved_home_dir),
        _check_agent_cli(agent_cli),
        _check_configured_agent_cli(active_agent_cli_from_config),
        _check_agent_directory(repo_root),
        _check_repo_writable(repo_root),
    )
    required_check_names = {
        "python_version",
        "home_directory",
        "agent_cli",
        "agent_directory",
        "repo_writable",
    }
    status = (
        "ok"
        if all(check.ok for check in checks if check.name in required_check_names)
        else "issues_found"
    )
    return DoctorReport(status=status, repo_root=repo_root, home_dir=resolved_home_dir, checks=checks)


def _check_python_version() -> DoctorCheck:
    current = sys.version_info[:3]
    ok = current >= MINIMUM_PYTHON
    summary = (
        f"Python {current[0]}.{current[1]}.{current[2]} meets the minimum requirement."
        if ok
        else (
            f"Python {current[0]}.{current[1]}.{current[2]} is too old; "
            f"{MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}+ is required."
        )
    )
    return DoctorCheck(
        name="python_version",
        ok=ok,
        summary=summary,
        details={
            "current": ".".join(str(value) for value in current),
            "required_minimum": ".".join(str(value) for value in MINIMUM_PYTHON),
            "executable": sys.executable,
        },
    )


def _check_home_directory(home_dir: Path) -> DoctorCheck:
    expanded = home_dir.expanduser()
    exists = expanded.exists()
    is_dir = expanded.is_dir()
    ok = exists and is_dir
    if ok:
        summary = f"HOME resolves to a usable directory: {expanded}."
    elif not exists:
        summary = f"HOME directory does not exist: {expanded}."
    else:
        summary = f"HOME path is not a directory: {expanded}."

    return DoctorCheck(
        name="home_directory",
        ok=ok,
        summary=summary,
        details={
            "path": str(expanded),
            "exists": exists,
            "is_directory": is_dir,
        },
    )


def _check_agent_cli(agent_cli: Path | None) -> DoctorCheck:
    if agent_cli is None:
        return DoctorCheck(
            name="agent_cli",
            ok=False,
            summary="No agent CLI path was provided. Pass --agent-cli to validate one.",
            details={
                "path": None,
                "exists": False,
                "executable": False,
            },
        )

    resolved = agent_cli.expanduser()
    raw_text = str(agent_cli)
    if resolved.is_absolute() or "/" in raw_text:
        if not resolved.is_absolute():
            resolved = Path(os.path.abspath(str(Path.cwd() / resolved)))
        exists = resolved.exists()
        executable = exists and os.access(resolved, os.X_OK)
    else:
        located = shutil.which(raw_text)
        if located is not None:
            resolved = Path(located)
            exists = True
            executable = os.access(resolved, os.X_OK)
        else:
            exists = False
            executable = False
    ok = exists and executable
    if ok:
        summary = f"Agent CLI is available at {resolved}."
    elif not exists:
        summary = f"Agent CLI path does not exist: {resolved}."
    else:
        summary = f"Agent CLI is not executable: {resolved}."

    return DoctorCheck(
        name="agent_cli",
        ok=ok,
        summary=summary,
        details={
            "path": str(resolved),
            "exists": exists,
            "executable": executable,
        },
    )


def _check_configured_agent_cli(agent_cli: Path | None) -> DoctorCheck:
    if agent_cli is None:
        return DoctorCheck(
            name="configured_agent_cli",
            ok=False,
            summary=(
                "active_agent_cli is not set in dormammu.json or ~/.dormammu/config. "
                "Run: dormammu set-config active_agent_cli <path>"
            ),
            details={
                "path": None,
                "configured": False,
                "hint": "dormammu set-config active_agent_cli /usr/local/bin/claude",
            },
        )

    resolved = agent_cli.expanduser()
    raw_text = str(agent_cli)
    if resolved.is_absolute() or "/" in raw_text:
        if not resolved.is_absolute():
            resolved = Path(os.path.abspath(str(Path.cwd() / resolved)))
        exists = resolved.exists()
        executable = exists and os.access(resolved, os.X_OK)
    else:
        located = shutil.which(raw_text)
        if located is not None:
            resolved = Path(located)
            exists = True
            executable = os.access(resolved, os.X_OK)
        else:
            exists = False
            executable = False

    ok = exists and executable
    if ok:
        summary = f"Configured active_agent_cli is available: {resolved}."
    elif not exists:
        summary = f"Configured active_agent_cli does not exist: {resolved}."
    else:
        summary = f"Configured active_agent_cli is not executable: {resolved}."

    return DoctorCheck(
        name="configured_agent_cli",
        ok=ok,
        summary=summary,
        details={
            "path": str(resolved),
            "configured": True,
            "exists": exists,
            "executable": executable,
        },
    )


def _check_agent_directory(repo_root: Path) -> DoctorCheck:
    candidates = (repo_root / ".agent", repo_root / ".agents")
    found = next((path for path in candidates if path.exists()), None)
    ok = found is not None
    summary = (
        f"Found agent workspace directory at {found}."
        if found is not None
        else "Neither .agent nor .agents exists under the repository root."
    )
    return DoctorCheck(
        name="agent_directory",
        ok=ok,
        summary=summary,
        details={
            "checked_paths": [str(path) for path in candidates],
            "found_path": str(found) if found else None,
        },
    )


def _check_repo_writable(repo_root: Path) -> DoctorCheck:
    probe_path = repo_root / ".dormammu-doctor-write-check"
    try:
        probe_path.write_text("ok\n", encoding="utf-8")
        probe_path.unlink()
    except OSError as exc:
        return DoctorCheck(
            name="repo_writable",
            ok=False,
            summary=f"Repository root is not writable: {exc}",
            details={
                "path": str(repo_root),
            },
        )

    return DoctorCheck(
        name="repo_writable",
        ok=True,
        summary=f"Repository root is writable: {repo_root}.",
        details={
            "path": str(repo_root),
        },
    )
