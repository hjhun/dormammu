"""Subcommand handler functions for the dormammu CLI.

Each ``_handle_*`` function in this module corresponds to one dormammu
subcommand and is registered via ``argparse.ArgumentParser.set_defaults``
in :func:`dormammu.cli.build_parser`.

Utility helpers shared among handlers (session scope resolution, config
loading, progress banners, etc.) live in :mod:`dormammu._cli_utils`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import sys
from typing import TextIO

from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.agent.models import AgentRunStarted
from dormammu.config import (
    AppConfig,
    detect_available_agent_cli,
    set_config_value,
    write_active_agent_cli_config,
)
from dormammu.daemon import DaemonRunner, SessionProgressLogStream, load_daemon_config
from dormammu.telegram.stream import TelegramProgressStream
from dormammu.doctor import run_doctor
from dormammu.guidance import build_guidance_prompt
from dormammu.loop_runner import LoopRunRequest, LoopRunner
from dormammu.recovery import RecoveryManager
from dormammu.state import StateRepository

from dormammu._cli_utils import (
    _active_session_id,
    _emit_resume_state_summary,
    _emit_runtime_banner,
    _ensure_resume_session_scope,
    _load_config,
    _load_state_scope,
    _prepare_run_session_scope,
    _project_log_capture,
    _read_prompt_input,
    _read_session_marker,
    _display_cli_path,
    _resolve_agent_cli,
    _resolve_bootstrap_inputs,
    _resolve_loop_retry_budget,
    _resolve_runtime_session_scope,
    _resolve_runtime_workdir,
    _scoped_session_repository,
    _with_guidance_overrides,
    _write_session_marker,
)


def _handle_show_config(args: argparse.Namespace) -> int:
    config = _with_guidance_overrides(_load_config(args.repo_root), args.guidance_files)
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=True))
    return 0


def _handle_set_config(args: argparse.Namespace) -> int:
    config = _load_config(args.repo_root)
    try:
        config_path = set_config_value(
            config,
            args.key,
            value=args.value,
            add=args.add,
            remove=args.remove,
            unset=args.unset,
            global_scope=args.global_scope,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(str(config_path))
    return 0


def _handle_init_state(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(args.repo_root)
    config = _with_guidance_overrides(config, args.guidance_files)
    detected_cli = detect_available_agent_cli()
    config_path = None
    if detected_cli is not None:
        config_path = write_active_agent_cli_config(config, detected_cli)
        config = config.with_overrides(
            config_file=config_path,
            active_agent_cli=detected_cli,
        )
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
    _write_session_marker(config.repo_root, _active_session_id(repository))
    payload = artifacts.to_dict()
    payload["active_agent_cli"] = str(detected_cli) if detected_cli is not None else None
    payload["config_file"] = str(config_path) if config_path is not None else None
    print(json.dumps(payload, indent=2, ensure_ascii=True))
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
    _write_session_marker(config.repo_root, _active_session_id(repository))
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
    _write_session_marker(config.repo_root, _active_session_id(repository))
    payload["session"] = repository.read_session_state()
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


def _handle_run_once(args: argparse.Namespace) -> int:
    config, repository = _load_state_scope(
        args.repo_root,
        session_id=args.session_id,
        prefer_active_session=True,
    )
    config = _with_guidance_overrides(config, args.guidance_files)
    repository = StateRepository(config, session_id=repository.session_id)
    prompt_text, prompt_source_path = _read_prompt_input(args)
    with _project_log_capture(config.repo_root, "run-once", enabled=args.debug):
        goal, roadmap_phases = _resolve_bootstrap_inputs(
            repository=repository,
            goal=args.goal,
            roadmap_phases=args.roadmap_phases,
            default_phase="phase_3",
            prompt_text_provided=True,
        )
        repository.ensure_bootstrap_state(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=roadmap_phases or ["phase_3"],
        )
        config, repository = _resolve_runtime_session_scope(config, repository)
        _write_session_marker(config.repo_root, _active_session_id(repository))
        workdir = _resolve_runtime_workdir(args.workdir, repo_root=config.repo_root)
        repository.persist_input_prompt(
            prompt_text=prompt_text,
            source_path=prompt_source_path,
        )
        try:
            agent_cli = _resolve_agent_cli(config, args.agent_cli)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _emit_runtime_banner(
            command_name="run-once",
            repo_root=config.repo_root,
            repository=repository,
            cli_path=agent_cli,
            workdir=workdir,
        )

        request = AgentRunRequest(
            cli_path=agent_cli,
            prompt_text=build_guidance_prompt(
                prompt_text,
                guidance_files=config.guidance_files,
                repo_root=config.repo_root,
            ),
            repo_root=config.repo_root,
            workdir=workdir,
            input_mode=args.input_mode,
            prompt_flag=args.prompt_flag,
            extra_args=tuple(args.extra_args or ()),
            run_label=args.run_label,
        )

        try:
            def _handle_started(started: AgentRunStarted) -> None:
                repository.record_current_run(started)
                print("=== dormammu command ===", file=sys.stderr)
                print(f"run id: {started.run_id}", file=sys.stderr)
                print(f"cli path: {started.cli_path}", file=sys.stderr)
                print(f"workdir: {started.workdir}", file=sys.stderr)
                print(f"prompt mode: {started.prompt_mode}", file=sys.stderr)
                print(f"command: {' '.join(started.command)}", file=sys.stderr)
                sys.stderr.flush()

            result = CliAdapter(config).run_once(request, on_started=_handle_started)
        except (RuntimeError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2

        repository.record_latest_run(result)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
        return 0 if result.exit_code == 0 else result.exit_code


def _handle_run_loop(args: argparse.Namespace) -> int:
    config = _load_config(args.repo_root)
    config = _with_guidance_overrides(config, args.guidance_files)
    prompt_text, prompt_source_path = _read_prompt_input(args)
    with _project_log_capture(config.repo_root, "run", enabled=args.debug):
        requested_session_id = args.session_id or _read_session_marker(config.repo_root)
        goal, roadmap_phases = _resolve_bootstrap_inputs(
            repository=(
                StateRepository(config, session_id=requested_session_id)
                if requested_session_id is not None
                else StateRepository(config)
            ),
            goal=args.goal,
            roadmap_phases=args.roadmap_phases,
            default_phase="phase_4",
            prompt_text_provided=True,
        )
        config, repository = _prepare_run_session_scope(
            config,
            requested_session_id=requested_session_id,
            goal=goal,
            prompt_text=prompt_text,
            roadmap_phases=roadmap_phases,
            default_phase="phase_4",
        )
        workdir = _resolve_runtime_workdir(args.workdir, repo_root=config.repo_root)
        repository.persist_input_prompt(
            prompt_text=prompt_text,
            source_path=prompt_source_path,
        )
        try:
            agent_cli = _resolve_agent_cli(config, args.agent_cli)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        try:
            max_retries = _resolve_loop_retry_budget(
                max_iterations=args.max_iterations,
                max_retries=args.max_retries,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _emit_runtime_banner(
            command_name="run",
            repo_root=config.repo_root,
            repository=repository,
            cli_path=agent_cli,
            workdir=workdir,
        )

        request = LoopRunRequest(
            cli_path=agent_cli,
            prompt_text=build_guidance_prompt(
                prompt_text,
                guidance_files=config.guidance_files,
                repo_root=config.repo_root,
            ),
            repo_root=config.repo_root,
            workdir=workdir,
            input_mode=args.input_mode,
            prompt_flag=args.prompt_flag,
            extra_args=tuple(args.extra_args or ()),
            run_label=args.run_label,
            max_retries=max_retries,
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
    with _project_log_capture(config.repo_root, "resume", enabled=args.debug):
        config, repository = _ensure_resume_session_scope(config, repository)

        workflow_state = repository.read_workflow_state()
        loop_state = workflow_state.get("loop", {})
        cli_path_text = loop_state.get("request", {}).get("cli_path")
        workdir_text = loop_state.get("request", {}).get("workdir")
        if isinstance(cli_path_text, str) and cli_path_text.strip():
            _emit_runtime_banner(
                command_name="resume",
                repo_root=config.repo_root,
                repository=repository,
                cli_path=Path(cli_path_text),
                workdir=Path(workdir_text) if isinstance(workdir_text, str) and workdir_text.strip() else None,
            )
        _emit_resume_state_summary(workflow_state, loop_state)

        try:
            max_retries_override = (
                _resolve_loop_retry_budget(
                    max_iterations=args.max_iterations,
                    max_retries=args.max_retries,
                )
                if (args.max_iterations is not None or args.max_retries is not None)
                else None
            )
            result = RecoveryManager(config, repository=repository).resume(
                max_retries_override=max_retries_override,
                session_id=None,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2

        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
        return 0 if result.status == "completed" else 1


def _handle_inspect_cli(args: argparse.Namespace) -> int:
    config, _ = _load_state_scope(args.repo_root)
    workdir = _resolve_runtime_workdir(args.workdir, repo_root=config.repo_root)
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
        home_dir=config.home_dir,
        agent_cli=args.agent_cli or config.active_agent_cli,
        active_agent_cli_from_config=config.active_agent_cli,
    )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
    return 0 if report.status == "ok" else 1


def _handle_daemonize(args: argparse.Namespace) -> int:
    config = _with_guidance_overrides(_load_config(args.repo_root), args.guidance_files)
    try:
        daemon_config = load_daemon_config(args.config, app_config=config)
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    progress_stream: TextIO = sys.stderr
    with contextlib.ExitStack() as stack:
        if args.debug:
            session_log_stream = SessionProgressLogStream(sys.stderr)
            stack.enter_context(contextlib.redirect_stderr(session_log_stream))
            progress_stream = session_log_stream

        if config.telegram_config is not None:
            tg_stream = TelegramProgressStream(
                progress_stream,
                chunk_size=config.telegram_config.chunk_size,
            )
            progress_stream = tg_stream
        else:
            tg_stream = None

        runner = DaemonRunner(config, daemon_config, progress_stream=progress_stream)

        if tg_stream is not None and config.telegram_config is not None:
            from dormammu.telegram.bot import TelegramBot

            bot = TelegramBot(
                config.telegram_config,
                daemon_config=daemon_config,
                app_config=config,
                stream=tg_stream,
                runner=runner,
            )
            try:
                bot.start()
                bot.notify_started()
                print("Telegram bot started.", file=sys.stderr)
            except Exception as exc:
                print(f"warning: Telegram bot failed to start: {exc}", file=sys.stderr)
                print(
                    "hint: verify that telegram.bot_token in your config is a valid token "
                    "from @BotFather and has not been revoked.",
                    file=sys.stderr,
                )

        try:
            return runner.run_forever()
        except KeyboardInterrupt:
            print("daemonize interrupted", file=sys.stderr)
            return 130
        except (RuntimeError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
