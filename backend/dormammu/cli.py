from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.config import AppConfig
from dormammu.doctor import run_doctor
from dormammu.guidance import build_guidance_prompt, resolve_guidance_files
from dormammu.loop_runner import LoopRunRequest, LoopRunner
from dormammu.recovery import RecoveryManager
from dormammu.state import StateRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dormammu",
        description="Bootstrap CLI for the dormammu orchestrator.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_config = subparsers.add_parser("show-config", help="Print resolved runtime configuration.")
    show_config.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    show_config.add_argument(
        "--guidance-file",
        dest="guidance_files",
        action="append",
        type=Path,
        default=None,
        help="Repeatable Markdown guidance file to use instead of repo autodiscovery when it has content.",
    )
    show_config.set_defaults(handler=_handle_show_config)

    init_state = subparsers.add_parser("init-state", help="Create or merge the bootstrap .dev state.")
    init_state.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    init_state.add_argument("--goal", default=None, help="Goal text to include in the generated dashboard.")
    init_state.add_argument(
        "--roadmap-phase",
        dest="roadmap_phases",
        action="append",
        default=None,
        help="Active roadmap phase id to record. Repeat for multiple values.",
    )
    init_state.add_argument(
        "--guidance-file",
        dest="guidance_files",
        action="append",
        type=Path,
        default=None,
        help="Repeatable Markdown guidance file to use instead of repo autodiscovery when it has content.",
    )
    init_state.set_defaults(handler=_handle_init_state)

    start_session = subparsers.add_parser(
        "start-session",
        help="Archive the current active session and start a fresh active `.dev` session.",
    )
    start_session.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    start_session.add_argument("--goal", default=None, help="Goal text to include in the generated dashboard.")
    start_session.add_argument(
        "--roadmap-phase",
        dest="roadmap_phases",
        action="append",
        default=None,
        help="Active roadmap phase id to record. Repeat for multiple values.",
    )
    start_session.add_argument(
        "--session-id",
        default=None,
        help="Optional explicit session id for the new active session.",
    )
    start_session.add_argument(
        "--guidance-file",
        dest="guidance_files",
        action="append",
        type=Path,
        default=None,
        help="Repeatable Markdown guidance file to use instead of repo autodiscovery when it has content.",
    )
    start_session.set_defaults(handler=_handle_start_session)

    sessions = subparsers.add_parser(
        "sessions",
        help="List archived and active session snapshots.",
    )
    sessions.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    sessions.set_defaults(handler=_handle_sessions)

    restore_session = subparsers.add_parser(
        "restore-session",
        help="Restore a saved session snapshot into the active root `.dev` state.",
    )
    restore_session.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    restore_session.add_argument(
        "--session-id",
        required=True,
        help="Saved session id to restore into the active root `.dev` view.",
    )
    restore_session.set_defaults(handler=_handle_restore_session)

    run_once = subparsers.add_parser(
        "run-once",
        help="Run an external coding-agent CLI once and persist the artifacts.",
    )
    run_once.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    run_once.add_argument(
        "--session-id",
        default=None,
        help="Optional saved session id to use for isolated `.dev` state.",
    )
    run_once.add_argument(
        "--goal",
        default=None,
        help="Bootstrap goal used when the target session has no saved state yet.",
    )
    run_once.add_argument(
        "--roadmap-phase",
        dest="roadmap_phases",
        action="append",
        default=None,
        help="Bootstrap roadmap phase id when the target session has no saved state yet.",
    )
    run_once.add_argument(
        "--agent-cli",
        type=Path,
        default=None,
        help="Path to the external CLI. Optional when active_agent_cli is configured.",
    )
    prompt_group = run_once.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", default=None, help="Prompt text to execute.")
    prompt_group.add_argument(
        "--prompt-file",
        type=Path,
        default=None,
        help="Read prompt text from a file.",
    )
    run_once.add_argument(
        "--input-mode",
        choices=("auto", "file", "arg", "stdin", "positional"),
        default="auto",
        help="How to send the prompt to the external CLI.",
    )
    run_once.add_argument(
        "--prompt-flag",
        default=None,
        help="Override the prompt flag used in file or arg mode.",
    )
    run_once.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Working directory for the external CLI run.",
    )
    run_once.add_argument(
        "--run-label",
        default=None,
        help="Optional label for the generated log artifact names.",
    )
    run_once.add_argument(
        "--extra-arg",
        dest="extra_args",
        action="append",
        default=None,
        help=(
            "Repeatable extra argument passed through to the external CLI. "
            "Use --extra-arg=VALUE when the value starts with '-'."
        ),
    )
    run_once.add_argument(
        "--guidance-file",
        dest="guidance_files",
        action="append",
        type=Path,
        default=None,
        help="Repeatable Markdown guidance file to embed into the run prompt when it has content.",
    )
    run_once.set_defaults(handler=_handle_run_once)

    run_loop = subparsers.add_parser(
        "run",
        aliases=["run-loop"],
        help="Run an external coding-agent CLI under the supervised retry loop.",
    )
    run_loop.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    run_loop.add_argument(
        "--session-id",
        default=None,
        help="Optional saved session id to use for isolated `.dev` state.",
    )
    run_loop.add_argument(
        "--goal",
        default=None,
        help="Bootstrap goal used when the target session has no saved state yet.",
    )
    run_loop.add_argument(
        "--roadmap-phase",
        dest="roadmap_phases",
        action="append",
        default=None,
        help="Bootstrap roadmap phase id when the target session has no saved state yet.",
    )
    run_loop.add_argument(
        "--agent-cli",
        type=Path,
        default=None,
        help="Path to the external CLI. Optional when active_agent_cli is configured.",
    )
    loop_prompt_group = run_loop.add_mutually_exclusive_group(required=True)
    loop_prompt_group.add_argument("--prompt", default=None, help="Prompt text to execute.")
    loop_prompt_group.add_argument(
        "--prompt-file",
        type=Path,
        default=None,
        help="Read prompt text from a file.",
    )
    run_loop.add_argument(
        "--input-mode",
        choices=("auto", "file", "arg", "stdin", "positional"),
        default="auto",
        help="How to send the prompt to the external CLI.",
    )
    run_loop.add_argument(
        "--prompt-flag",
        default=None,
        help="Override the prompt flag used in file or arg mode.",
    )
    run_loop.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Working directory for the external CLI run.",
    )
    run_loop.add_argument(
        "--run-label",
        default=None,
        help="Optional label for the generated log artifact names.",
    )
    run_loop.add_argument(
        "--extra-arg",
        dest="extra_args",
        action="append",
        default=None,
        help=(
            "Repeatable extra argument passed through to the external CLI. "
            "Use --extra-arg=VALUE when the value starts with '-'."
        ),
    )
    run_loop.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Additional retries after the first attempt. Use -1 for infinite retries.",
    )
    run_loop.add_argument(
        "--required-path",
        dest="required_paths",
        action="append",
        default=None,
        help="Repeatable path that must exist before the supervisor approves the run.",
    )
    run_loop.add_argument(
        "--require-worktree-changes",
        action="store_true",
        help="Require git worktree changes before the supervisor approves the run.",
    )
    run_loop.add_argument(
        "--guidance-file",
        dest="guidance_files",
        action="append",
        type=Path,
        default=None,
        help="Repeatable Markdown guidance file to embed into the run prompt when it has content.",
    )
    run_loop.set_defaults(handler=_handle_run_loop)

    resume_loop = subparsers.add_parser(
        "resume",
        aliases=["resume-loop"],
        help="Resume the most recent supervised loop run from saved .dev state.",
    )
    resume_loop.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    resume_loop.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Override the saved retry configuration before resuming.",
    )
    resume_loop.add_argument(
        "--session-id",
        default=None,
        help="Resume this saved session id without switching the active root `.dev` view.",
    )
    resume_loop.add_argument(
        "--guidance-file",
        dest="guidance_files",
        action="append",
        type=Path,
        default=None,
        help="Repeatable Markdown guidance file to refresh bootstrap guidance before resuming.",
    )
    resume_loop.set_defaults(handler=_handle_resume_loop)

    inspect_cli = subparsers.add_parser(
        "inspect-cli",
        help="Inspect an external coding-agent CLI for prompt handling and approval hints.",
    )
    inspect_cli.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    inspect_cli.add_argument(
        "--agent-cli",
        type=Path,
        default=None,
        help="Path to the external CLI. Optional when active_agent_cli is configured.",
    )
    inspect_cli.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Working directory to use while invoking the CLI help command.",
    )
    inspect_cli.add_argument(
        "--include-help-text",
        action="store_true",
        help="Include the raw CLI help text in the JSON output.",
    )
    inspect_cli.set_defaults(handler=_handle_inspect_cli)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check whether the local environment is ready to run dormammu.",
    )
    doctor.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    doctor.add_argument(
        "--agent-cli",
        type=Path,
        default=None,
        help="Path to the external coding-agent CLI to validate.",
    )
    doctor.set_defaults(handler=_handle_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.handler(args)


def _load_config(repo_root: Path | None) -> AppConfig:
    return AppConfig.load(repo_root=repo_root)


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
        session_path = config.base_dev_dir / "session.json"
        if session_path.exists():
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


def _prompt_with_default(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def _resolve_bootstrap_inputs(
    *,
    repository: StateRepository,
    goal: str | None,
    roadmap_phases: Sequence[str] | None,
    default_phase: str,
) -> tuple[str | None, Sequence[str] | None]:
    session_exists = repository.state_file("workflow_state.json").exists()
    resolved_goal = goal
    resolved_roadmap_phases = list(roadmap_phases) if roadmap_phases else None

    if not session_exists and sys.stdin.isatty():
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


def _handle_show_config(args: argparse.Namespace) -> int:
    config = _with_guidance_overrides(_load_config(args.repo_root), args.guidance_files)
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=True))
    return 0


def _handle_init_state(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(args.repo_root)
    config = _with_guidance_overrides(config, args.guidance_files)
    repository = StateRepository(config, session_id=repository.session_id)
    goal, roadmap_phases = _resolve_bootstrap_inputs(
        repository=repository,
        goal=args.goal,
        roadmap_phases=args.roadmap_phases,
        default_phase="phase_1",
    )
    artifacts = repository.ensure_bootstrap_state(
        goal=goal,
        active_roadmap_phase_ids=roadmap_phases,
    )
    print(json.dumps(artifacts.to_dict(), indent=2, ensure_ascii=True))
    return 0


def _handle_start_session(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(args.repo_root)
    config = _with_guidance_overrides(config, args.guidance_files)
    repository = StateRepository(config, session_id=repository.session_id)
    bootstrap_repository = repository.for_session(args.session_id) if args.session_id else repository
    goal, roadmap_phases = _resolve_bootstrap_inputs(
        repository=bootstrap_repository,
        goal=args.goal,
        roadmap_phases=args.roadmap_phases,
        default_phase="phase_7",
    )
    try:
        artifacts = repository.start_new_session(
            goal=goal,
            active_roadmap_phase_ids=roadmap_phases,
            session_id=args.session_id,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = artifacts.to_dict()
    payload["session"] = repository.read_session_state()
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


def _handle_sessions(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(args.repo_root)
    repository.ensure_bootstrap_state()
    payload = {
        "sessions": repository.list_sessions(),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


def _handle_restore_session(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(args.repo_root)
    try:
        artifacts = repository.restore_session(args.session_id)
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = artifacts.to_dict()
    payload["session"] = repository.read_session_state()
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


def _read_prompt_text(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if args.prompt_file is not None:
        return args.prompt_file.read_text(encoding="utf-8")
    raise ValueError("Either --prompt or --prompt-file is required.")


def _display_cli_path(cli_path: Path) -> str:
    candidate = cli_path.expanduser()
    if candidate.is_absolute() or "/" in str(cli_path):
        return os.path.abspath(str(candidate))
    return str(candidate)


def _resolve_agent_cli(config: AppConfig, cli_path: Path | None) -> Path:
    if cli_path is not None:
        return cli_path
    if config.active_agent_cli is not None:
        return config.active_agent_cli
    raise ValueError(
        "No agent CLI was provided and no active_agent_cli is configured. "
        "Set ~/.dormammu/config or pass --agent-cli."
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


def _handle_run_once(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(
        args.repo_root,
        session_id=args.session_id,
        prefer_active_session=True,
    )
    config = _with_guidance_overrides(config, args.guidance_files)
    repository = StateRepository(config, session_id=repository.session_id)
    goal, roadmap_phases = _resolve_bootstrap_inputs(
        repository=repository,
        goal=args.goal,
        roadmap_phases=args.roadmap_phases,
        default_phase="phase_3",
    )
    repository.ensure_bootstrap_state(
        goal=goal,
        active_roadmap_phase_ids=roadmap_phases or ["phase_3"],
    )
    config, repository = _resolve_runtime_session_scope(config, repository)
    try:
        agent_cli = _resolve_agent_cli(config, args.agent_cli)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    request = AgentRunRequest(
        cli_path=agent_cli,
        prompt_text=build_guidance_prompt(
            _read_prompt_text(args),
            guidance_files=config.guidance_files,
            repo_root=config.repo_root,
        ),
        repo_root=config.repo_root,
        workdir=args.workdir,
        input_mode=args.input_mode,
        prompt_flag=args.prompt_flag,
        extra_args=tuple(args.extra_args or ()),
        run_label=args.run_label,
    )

    try:
        result = CliAdapter(config).run_once(request, on_started=repository.record_current_run)
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    repository.record_latest_run(result)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
    return 0 if result.exit_code == 0 else result.exit_code


def _handle_run_loop(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(
        args.repo_root,
        session_id=args.session_id,
        prefer_active_session=True,
    )
    config = _with_guidance_overrides(config, args.guidance_files)
    repository = StateRepository(config, session_id=repository.session_id)
    goal, roadmap_phases = _resolve_bootstrap_inputs(
        repository=repository,
        goal=args.goal,
        roadmap_phases=args.roadmap_phases,
        default_phase="phase_4",
    )
    repository.ensure_bootstrap_state(
        goal=goal,
        active_roadmap_phase_ids=roadmap_phases or ["phase_4"],
    )
    config, repository = _resolve_runtime_session_scope(config, repository)
    try:
        agent_cli = _resolve_agent_cli(config, args.agent_cli)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    request = LoopRunRequest(
        cli_path=agent_cli,
        prompt_text=build_guidance_prompt(
            _read_prompt_text(args),
            guidance_files=config.guidance_files,
            repo_root=config.repo_root,
        ),
        repo_root=config.repo_root,
        workdir=args.workdir,
        input_mode=args.input_mode,
        prompt_flag=args.prompt_flag,
        extra_args=tuple(args.extra_args or ()),
        run_label=args.run_label,
        max_retries=args.max_retries,
        required_paths=tuple(args.required_paths or ()),
        require_worktree_changes=args.require_worktree_changes,
        expected_roadmap_phase_id=(roadmap_phases[0] if roadmap_phases else "phase_4"),
    )

    try:
        result = LoopRunner(config, repository=repository).run(request)
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
    return 0 if result.status == "completed" else 1


def _handle_resume_loop(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(
        args.repo_root,
        session_id=args.session_id,
        prefer_active_session=True,
    )
    config = _with_guidance_overrides(config, args.guidance_files)
    repository = StateRepository(config, session_id=repository.session_id)
    repository.ensure_bootstrap_state()
    config, repository = _resolve_runtime_session_scope(config, repository)

    try:
        result = RecoveryManager(config, repository=repository).resume(
            max_retries_override=args.max_retries,
            session_id=None,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
    return 0 if result.status == "completed" else 1


def _handle_inspect_cli(args: argparse.Namespace) -> int:
    config, _ = _load_state_scope(args.repo_root)
    workdir = (args.workdir or config.repo_root).resolve()
    try:
        agent_cli = _resolve_agent_cli(config, args.agent_cli)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        capabilities = CliAdapter(config).inspect_capabilities(agent_cli, cwd=workdir)
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = {
        "cli_path": _display_cli_path(agent_cli),
        "workdir": str(workdir),
        "capabilities": capabilities.to_dict(include_help_text=args.include_help_text),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    config, _ = _load_state_scope(args.repo_root)
    report = run_doctor(
        repo_root=config.repo_root,
        agent_cli=args.agent_cli or config.active_agent_cli,
    )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
    return 0 if report.status == "ok" else 1
