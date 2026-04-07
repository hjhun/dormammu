from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Sequence

from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.app import create_app
from dormammu.config import AppConfig
from dormammu.doctor import run_doctor
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
    init_state.set_defaults(handler=_handle_init_state)

    run_once = subparsers.add_parser(
        "run-once",
        help="Run an external coding-agent CLI once and persist the artifacts.",
    )
    run_once.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    run_once.add_argument("--agent-cli", type=Path, required=True, help="Path to the external CLI.")
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
        choices=("auto", "file", "arg", "stdin"),
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
    run_once.set_defaults(handler=_handle_run_once)

    run_loop = subparsers.add_parser(
        "run",
        aliases=["run-loop"],
        help="Run an external coding-agent CLI under the supervised retry loop.",
    )
    run_loop.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    run_loop.add_argument("--agent-cli", type=Path, required=True, help="Path to the external CLI.")
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
        choices=("auto", "file", "arg", "stdin"),
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
    resume_loop.set_defaults(handler=_handle_resume_loop)

    serve = subparsers.add_parser(
        "ui",
        aliases=["serve"],
        help="Start the local backend app and UI.",
    )
    serve.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    serve.add_argument("--host", default=None, help="Host interface to bind.")
    serve.add_argument("--port", type=int, default=None, help="Port to bind.")
    serve.add_argument(
        "--skip-init-state",
        action="store_true",
        help="Skip the startup bootstrap state initialization.",
    )
    serve.set_defaults(handler=_handle_serve)

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


def _handle_show_config(args: argparse.Namespace) -> int:
    config = _load_config(args.repo_root)
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=True))
    return 0


def _handle_init_state(args: argparse.Namespace) -> int:
    config = _load_config(args.repo_root)
    repository = StateRepository(config)
    artifacts = repository.ensure_bootstrap_state(
        goal=args.goal,
        active_roadmap_phase_ids=args.roadmap_phases,
    )
    print(json.dumps(artifacts.to_dict(), indent=2, ensure_ascii=True))
    return 0


def _read_prompt_text(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if args.prompt_file is not None:
        return args.prompt_file.read_text(encoding="utf-8")
    raise ValueError("Either --prompt or --prompt-file is required.")


def _handle_run_once(args: argparse.Namespace) -> int:
    config = _load_config(args.repo_root)
    repository = StateRepository(config)
    repository.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_3"])

    request = AgentRunRequest(
        cli_path=args.agent_cli,
        prompt_text=_read_prompt_text(args),
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
    config = _load_config(args.repo_root)
    repository = StateRepository(config)
    repository.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_4"])

    request = LoopRunRequest(
        cli_path=args.agent_cli,
        prompt_text=_read_prompt_text(args),
        repo_root=config.repo_root,
        workdir=args.workdir,
        input_mode=args.input_mode,
        prompt_flag=args.prompt_flag,
        extra_args=tuple(args.extra_args or ()),
        run_label=args.run_label,
        max_retries=args.max_retries,
        required_paths=tuple(args.required_paths or ()),
        require_worktree_changes=args.require_worktree_changes,
        expected_roadmap_phase_id="phase_4",
    )

    try:
        result = LoopRunner(config, repository=repository).run(request)
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
    return 0 if result.status == "completed" else 1


def _handle_resume_loop(args: argparse.Namespace) -> int:
    config = _load_config(args.repo_root)
    repository = StateRepository(config)

    try:
        result = RecoveryManager(config, repository=repository).resume(
            max_retries_override=args.max_retries
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
    return 0 if result.status == "completed" else 1


def _handle_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "uvicorn is not installed. Install the project dependencies before "
            "starting the backend app.",
            file=sys.stderr,
        )
        return 2

    config = _load_config(args.repo_root)
    if args.host is not None:
        config = replace(config, host=args.host)
    if args.port is not None:
        config = replace(config, port=args.port)

    if not args.skip_init_state:
        StateRepository(config).ensure_bootstrap_state()

    try:
        app = create_app(config)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    uvicorn.run(app, host=config.host, port=config.port, log_level=config.log_level)
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    config = _load_config(args.repo_root)
    report = run_doctor(repo_root=config.repo_root, agent_cli=args.agent_cli)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
    return 0 if report.status == "ok" else 1
