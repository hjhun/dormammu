"""Utility helpers shared across dormammu CLI handler functions.

This module contains pure helper functions and context managers that do not
register argparse subparsers or contain top-level command dispatch logic.
Handler functions that implement individual subcommands live in
:mod:`dormammu._cli_handlers`.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import shutil
import sys
from typing import Iterator, Sequence, TextIO

from dormammu._utils import iso_now as _iso_now
from dormammu.config import AppConfig
from dormammu.guidance import resolve_guidance_files
from dormammu.state import StateRepository


# ---------------------------------------------------------------------------
# Progress logging
# ---------------------------------------------------------------------------

class _TeeStream:
    """Write-through stream that fans out to multiple underlying streams."""

    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams
        self.encoding = getattr(streams[0], "encoding", "utf-8") if streams else "utf-8"

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()

    def isatty(self) -> bool:
        return any(getattr(stream, "isatty", lambda: False)() for stream in self._streams)


@contextlib.contextmanager
def _project_log_capture(repo_root: Path, command_name: str, *, enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    log_path = repo_root / "DORMAMMU.log"
    started_at = _iso_now()
    with log_path.open("a", encoding="utf-8") as project_log:
        project_log.write(f"=== dormammu {command_name} started {started_at} ===\n")
        project_log.flush()
        with contextlib.redirect_stderr(_TeeStream(sys.stderr, project_log)):
            try:
                yield
            finally:
                project_log.write(f"=== dormammu {command_name} finished {_iso_now()} ===\n")
                project_log.flush()


# ---------------------------------------------------------------------------
# Config and state helpers
# ---------------------------------------------------------------------------

def _load_config(repo_root: Path | None, *, discover: bool = True) -> AppConfig:
    return AppConfig.load(repo_root=repo_root, discover=discover)


def _with_guidance_overrides(config: AppConfig, guidance_files: Sequence[Path] | None) -> AppConfig:
    if not guidance_files:
        resolved = resolve_guidance_files(config)
        return config.with_overrides(guidance_files=resolved)
    resolved = resolve_guidance_files(config, explicit_paths=guidance_files)
    return config.with_overrides(guidance_files=resolved)


def _load_state_scope(
    repo_root: Path | None,
    *,
    session_id: str | None = None,
    prefer_active_session: bool = False,
) -> tuple[AppConfig, StateRepository]:
    config = _load_config(repo_root)
    resolved_session_id = session_id
    if resolved_session_id is None and prefer_active_session:
        marker_session_id = _read_session_marker(config.repo_root)
        if marker_session_id is not None:
            resolved_session_id = marker_session_id
        session_path = config.base_dev_dir / "session.json"
        if resolved_session_id is None and session_path.exists():
            try:
                payload = json.loads(session_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            candidate = payload.get("active_session_id") or payload.get("session_id")
            if isinstance(candidate, str) and candidate.strip():
                resolved_session_id = candidate
    repository = StateRepository(config, session_id=session_id)
    if resolved_session_id is not None:
        repository = StateRepository(config, session_id=resolved_session_id)
        config = config.with_overrides(dev_dir=repository.dev_dir, logs_dir=repository.logs_dir)
        repository = StateRepository(config, session_id=resolved_session_id)
    return config, repository


# ---------------------------------------------------------------------------
# Session marker helpers
# ---------------------------------------------------------------------------

def _session_marker_path(repo_root: Path) -> Path:
    return repo_root / ".session"


def _ensure_gitignore_entry(repo_root: Path, entry: str) -> None:
    gitignore_path = repo_root / ".gitignore"
    if gitignore_path.exists():
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    if entry in lines:
        return

    if lines:
        gitignore_path.write_text(
            "\n".join([*lines, entry]) + "\n",
            encoding="utf-8",
        )
        return

    gitignore_path.write_text(f"{entry}\n", encoding="utf-8")


def _read_session_marker(repo_root: Path) -> str | None:
    marker_path = _session_marker_path(repo_root)
    if not marker_path.exists():
        return None
    value = marker_path.read_text(encoding="utf-8").strip()
    return value or None


def _write_session_marker(repo_root: Path, session_id: str) -> None:
    _ensure_gitignore_entry(repo_root, ".session")
    _session_marker_path(repo_root).write_text(f"{session_id}\n", encoding="utf-8")


def _active_session_id(repository: StateRepository) -> str:
    session_state = repository.read_session_state()
    session_id = session_state.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise RuntimeError("No active session id is available.")
    return session_id


def _scoped_session_repository(
    config: AppConfig,
    session_id: str,
) -> tuple[AppConfig, StateRepository]:
    session_repository = StateRepository(config, session_id=session_id)
    scoped_config = config.with_overrides(
        dev_dir=session_repository.dev_dir,
        logs_dir=session_repository.logs_dir,
    )
    return scoped_config, StateRepository(scoped_config, session_id=session_id)


def _ensure_resume_session_scope(
    config: AppConfig,
    repository: StateRepository,
) -> tuple[AppConfig, StateRepository]:
    if repository.session_id is None:
        repository.ensure_bootstrap_state()
        config, repository = _resolve_runtime_session_scope(config, repository)
    else:
        StateRepository(config).restore_session(repository.session_id)
        config, repository = _scoped_session_repository(config, repository.session_id)
    _write_session_marker(config.repo_root, _active_session_id(repository))
    return config, repository


def _clear_dev_dir(base_dev_dir: Path) -> None:
    """Remove all contents under base_dev_dir for a fresh run."""
    if not base_dev_dir.exists():
        return
    for item in base_dev_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _prepare_run_session_scope(
    config: AppConfig,
    *,
    requested_session_id: str | None,
    goal: str | None,
    prompt_text: str,
    roadmap_phases: Sequence[str] | None,
    default_phase: str,
) -> tuple[AppConfig, StateRepository]:
    # Clear all .dev/ state for a fresh run (skip when a specific session_id
    # is requested, which signals intentional continuation).
    if requested_session_id is None:
        _clear_dev_dir(config.base_dev_dir)

    root_repository = StateRepository(config)
    active_roadmap_phases = list(roadmap_phases or [default_phase])

    if requested_session_id is None:
        root_repository.start_new_session(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=active_roadmap_phases,
        )
        session_id = _active_session_id(root_repository)
    else:
        session_repository = StateRepository(config, session_id=requested_session_id)
        session_repository.ensure_bootstrap_state(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=active_roadmap_phases,
        )
        root_repository.restore_session(requested_session_id)
        session_id = requested_session_id

    _write_session_marker(config.repo_root, session_id)
    return _scoped_session_repository(config, session_id)


def _resolve_runtime_workdir(workdir: Path | None, *, repo_root: Path) -> Path:
    return (workdir or repo_root).resolve()


def _prompt_with_default(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def _resolve_loop_retry_budget(
    *,
    max_iterations: int | None,
    max_retries: int | None,
    default_max_iterations: int = 50,
) -> int:
    if max_iterations is not None and max_retries is not None:
        raise ValueError("Use either --max-iterations or --max-retries, not both.")

    if max_iterations is not None:
        if max_iterations == -1:
            return -1
        if max_iterations < 1:
            raise ValueError("max_iterations must be -1 or greater than 0.")
        return max_iterations - 1

    if max_retries is not None:
        if max_retries < -1:
            raise ValueError("max_retries must be -1 or greater.")
        return max_retries

    return default_max_iterations - 1


def _resolve_bootstrap_inputs(
    *,
    repository: StateRepository,
    goal: str | None,
    roadmap_phases: Sequence[str] | None,
    default_phase: str,
    prompt_text_provided: bool = False,
) -> tuple[str | None, Sequence[str] | None]:
    session_exists = repository.state_file("workflow_state.json").exists()
    resolved_goal = goal
    resolved_roadmap_phases = list(roadmap_phases) if roadmap_phases else None

    if not session_exists and sys.stdin.isatty() and not prompt_text_provided:
        if resolved_goal is None:
            resolved_goal = _prompt_with_default(
                "Initial workflow goal",
                "Bootstrap dormammu in the current repository.",
            )
        if resolved_roadmap_phases is None:
            roadmap_input = _prompt_with_default(
                "Active roadmap phase ids (comma separated)",
                default_phase,
            )
            resolved_roadmap_phases = [
                item.strip()
                for item in roadmap_input.split(",")
                if item.strip()
            ]

    return resolved_goal, resolved_roadmap_phases


# ---------------------------------------------------------------------------
# Runtime display helpers
# ---------------------------------------------------------------------------

def _read_prompt_input(args: object) -> tuple[str, Path | None]:
    if getattr(args, "prompt", None) is not None:
        return args.prompt, None  # type: ignore[union-attr]
    if getattr(args, "prompt_file", None) is not None:
        return args.prompt_file.read_text(encoding="utf-8"), args.prompt_file  # type: ignore[union-attr]
    raise ValueError("Either --prompt or --prompt-file is required.")


import os  # noqa: E402  (placed here to keep the public API at the top)


def _display_cli_path(cli_path: Path) -> str:
    candidate = cli_path.expanduser()
    if candidate.is_absolute() or "/" in str(cli_path):
        return os.path.abspath(str(candidate))
    return str(candidate)


def _emit_resume_state_summary(workflow_state: dict, loop_state: dict) -> None:
    attempts = loop_state.get("attempts_completed", 0)
    retries_used = loop_state.get("retries_used", 0)
    max_retries = loop_state.get("max_retries", 0)
    status = loop_state.get("status", "unknown")
    verdict = loop_state.get("latest_supervisor_verdict", "none")
    next_action = loop_state.get("next_action") or workflow_state.get("next_action", "")
    report_path = loop_state.get("latest_supervisor_report_path", ".dev/supervisor_report.md")
    print("=== dormammu resume state ===", file=sys.stderr)
    print(f"last status: {status}", file=sys.stderr)
    print(f"attempts completed: {attempts}", file=sys.stderr)
    print(f"retries used: {retries_used}/{max_retries if max_retries != -1 else 'infinite'}", file=sys.stderr)
    print(f"last supervisor verdict: {verdict}", file=sys.stderr)
    if next_action:
        print(f"next action: {next_action}", file=sys.stderr)
    print(f"supervisor report: {report_path}", file=sys.stderr)
    sys.stderr.flush()


def _emit_runtime_banner(
    *,
    command_name: str,
    repo_root: Path,
    repository: StateRepository,
    cli_path: Path,
    workdir: Path | None,
) -> None:
    print("=== dormammu run ===", file=sys.stderr)
    print(f"command: {command_name}", file=sys.stderr)
    print(f"target project: {repo_root.resolve()}", file=sys.stderr)
    print(f"session: {repository.session_id or 'active-root'}", file=sys.stderr)
    print(f"cli: {_display_cli_path(cli_path)}", file=sys.stderr)
    print(f"workdir: {(workdir or repo_root).resolve()}", file=sys.stderr)
    sys.stderr.flush()


def _resolve_agent_cli(config: AppConfig, cli_path: Path | None) -> Path:
    if cli_path is not None:
        return cli_path
    if config.active_agent_cli is not None:
        return config.active_agent_cli
    raise ValueError(
        "No agent CLI is configured.\n"
        "Fix: dormammu set-config active_agent_cli /path/to/agent\n"
        "  or pass --agent-cli /path/to/agent on the command line.\n"
        "Run 'dormammu doctor' to diagnose your configuration."
    )


def _resolve_runtime_session_scope(
    config: AppConfig,
    repository: StateRepository,
) -> tuple[AppConfig, StateRepository]:
    if repository.session_id is not None:
        return config, repository
    session_index_path = config.base_dev_dir / "session.json"
    if not session_index_path.exists():
        return config, repository
    try:
        payload = json.loads(session_index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return config, repository
    session_id = payload.get("active_session_id") or payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return config, repository
    session_repository = StateRepository(config, session_id=session_id)
    scoped_config = config.with_overrides(
        dev_dir=session_repository.dev_dir,
        logs_dir=session_repository.logs_dir,
    )
    return scoped_config, StateRepository(scoped_config, session_id=session_id)
