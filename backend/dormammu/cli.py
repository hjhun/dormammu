"""dormammu command-line interface entry point.

This module contains :func:`build_parser` (argparse setup) and :func:`main`
(the ``dormammu`` executable entry point).  All subcommand handler functions
have been moved to :mod:`dormammu._cli_handlers` and shared utility helpers
to :mod:`dormammu._cli_utils`.

Re-exports
----------
Functions that existing callers (tests, scripts) import directly from
``dormammu.cli`` are re-exported here for backward compatibility:

- :func:`_resolve_agent_cli`
- :func:`_emit_resume_state_summary`
- :func:`_TeeStream`
- :func:`_project_log_capture`
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence
import sys

from dormammu.interactive_shell import InteractiveShellRunner
from dormammu._cli_handlers import (
    _handle_daemonize,
    _handle_doctor,
    _handle_init_state,
    _handle_inspect_cli,
    _handle_restore_session,
    _handle_resume_loop,
    _handle_run_loop,
    _handle_run_once,
    _handle_sessions,
    _handle_set_config,
    _handle_show_config,
    _handle_start_session,
)

# Re-export utilities that external callers (tests, integrations) import
# directly from this module so they keep working without changes.
from dormammu._cli_utils import (  # noqa: F401
    _TeeStream,
    _project_log_capture,
    _emit_resume_state_summary,
    _resolve_agent_cli,
)


def _add_repo_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")


def _add_agent_cli(
    parser: argparse.ArgumentParser,
    *,
    help: str = "Path to the external CLI. Optional when active_agent_cli is configured.",
) -> None:
    parser.add_argument("--agent-cli", type=Path, default=None, help=help)


def _add_guidance_files(parser: argparse.ArgumentParser, *, help: str) -> None:
    parser.add_argument(
        "--guidance-file",
        dest="guidance_files",
        action="append",
        type=Path,
        default=None,
        help=help,
    )


def _add_debug(parser: argparse.ArgumentParser, *, help: str) -> None:
    parser.add_argument("--debug", action="store_true", help=help)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dormammu",
        description=(
            "CLI for the dormammu interactive shell, supervised sessions, one-off agent "
            "executions, and daemonized prompt queues."
        ),
        epilog=(
            "Interactive shell:\n"
            "  dormammu                     Start the default interactive shell\n"
            "  dormammu shell               Start the interactive shell explicitly\n"
            "\n"
            "Common command groups:\n"
            "  Runtime config: show-config, doctor, inspect-cli\n"
            "  One-shot / loop runs: run-once, run, resume\n"
            "  Long-running queue worker: daemonize\n"
            "  Session state: init-state, start-session, sessions, restore-session\n"
            "\n"
            "Config injection:\n"
            "  General runtime config is loaded from ./dormammu.json, or from\n"
            "  $DORMAMMU_CONFIG_PATH, or from ~/.dormammu/config.\n"
            "  Daemon queue runs use ~/.dormammu/daemonize.json by default, or\n"
            "  override it with: dormammu daemonize --config daemonize.json\n"
            "\n"
            "Prompt input examples:\n"
            "  dormammu run-once --agent-cli codex --prompt \"Summarize this repo\"\n"
            "  dormammu run --agent-cli codex --prompt-file PROMPT.md\n"
            "  dormammu daemonize --repo-root .\n"
            "  dormammu daemonize --repo-root . --config daemonize.json\n"
            "\n"
            "Use `dormammu <command> --help` for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_config = subparsers.add_parser(
        "show-config",
        help="Print resolved runtime configuration and the config file source.",
        description=(
            "Print the resolved Dormammu runtime configuration as JSON.\n"
            "Config resolution order is:\n"
            "  1. $DORMAMMU_CONFIG_PATH\n"
            "  2. <repo-root>/dormammu.json\n"
            "  3. ~/.dormammu/config"
        ),
        epilog=(
            "Example:\n"
            "  dormammu show-config --repo-root .\n"
            "  DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json dormammu show-config --repo-root ."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_repo_root(show_config)
    _add_guidance_files(show_config, help="Repeatable Markdown guidance file to use instead of repo autodiscovery when it has content.")
    show_config.set_defaults(handler=_handle_show_config)

    set_config = subparsers.add_parser(
        "set-config",
        help="Set a config value in the config file.",
        description=(
            "Write a configuration value to the dormammu config file.\n"
            "Config file resolution order (write target):\n"
            "  1. <repo-root>/dormammu.json (project-level, default)\n"
            "  2. ~/.dormammu/config (global, use --global)\n"
            "\n"
            "Settable keys:\n"
            "  Scalar: active_agent_cli, telegram.bot_token\n"
            "  List:   token_exhaustion_patterns, fallback_agent_clis, telegram.allowed_chat_ids\n"
        ),
        epilog=(
            "Examples:\n"
            "  dormammu set-config active_agent_cli /usr/local/bin/claude\n"
            "  dormammu set-config active_agent_cli --unset\n"
            "  dormammu set-config token_exhaustion_patterns --add 'context window exceeded'\n"
            "  dormammu set-config token_exhaustion_patterns --remove 'usage limit'\n"
            "  dormammu set-config fallback_agent_clis --add gemini\n"
            "  dormammu set-config active_agent_cli /usr/local/bin/claude --global\n"
            "  dormammu set-config telegram.bot_token 123456:ABC-DEF...\n"
            "  dormammu set-config telegram.allowed_chat_ids --add 987654321\n"
            "  dormammu set-config telegram.bot_token --unset\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    set_config.add_argument("key", help="Config key to set (e.g. active_agent_cli, token_exhaustion_patterns).")
    set_config.add_argument(
        "value",
        nargs="?",
        default=None,
        help="Value to assign. For list keys, accepts a JSON array string to replace the full list.",
    )
    set_config.add_argument("--add", metavar="VALUE", default=None, help="Append a value to a list key.")
    set_config.add_argument("--remove", metavar="VALUE", default=None, help="Remove a value from a list key.")
    set_config.add_argument("--unset", action="store_true", help="Remove the key from the config file.")
    set_config.add_argument(
        "--global",
        action="store_true",
        dest="global_scope",
        help="Write to ~/.dormammu/config instead of the project dormammu.json.",
    )
    _add_repo_root(set_config)
    set_config.set_defaults(handler=_handle_set_config)

    init_state = subparsers.add_parser("init-state", help="Create or merge the bootstrap .dev state.")
    _add_repo_root(init_state)
    init_state.add_argument("--goal", default=None, help="Goal text to include in the generated dashboard.")
    init_state.add_argument(
        "--roadmap-phase",
        dest="roadmap_phases",
        action="append",
        default=None,
        help="Active roadmap phase id to record. Repeat for multiple values.",
    )
    _add_guidance_files(init_state, help="Repeatable Markdown guidance file to use instead of repo autodiscovery when it has content.")
    init_state.set_defaults(handler=_handle_init_state)

    start_session = subparsers.add_parser(
        "start-session",
        help="Archive the current active session and start a fresh active `.dev` session.",
    )
    _add_repo_root(start_session)
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
    _add_guidance_files(start_session, help="Repeatable Markdown guidance file to use instead of repo autodiscovery when it has content.")
    start_session.set_defaults(handler=_handle_start_session)

    sessions = subparsers.add_parser(
        "sessions",
        help="List archived and active session snapshots.",
    )
    _add_repo_root(sessions)
    sessions.set_defaults(handler=_handle_sessions)

    restore_session = subparsers.add_parser(
        "restore-session",
        help="Restore a saved session snapshot into the active root `.dev` state.",
    )
    _add_repo_root(restore_session)
    restore_session.add_argument(
        "--session-id",
        required=True,
        help="Saved session id to restore into the active root `.dev` view.",
    )
    restore_session.set_defaults(handler=_handle_restore_session)

    run_once = subparsers.add_parser(
        "run-once",
        help="Run one agent execution with --prompt or --prompt-file and persist the artifacts.",
        description=(
            "Run an external coding-agent CLI once.\n"
            "Provide the prompt inline with --prompt or load it from disk with --prompt-file."
        ),
    )
    _add_repo_root(run_once)
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
    _add_agent_cli(run_once)
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
    _add_guidance_files(run_once, help="Repeatable Markdown guidance file to embed into the run prompt when it has content.")
    _add_debug(run_once, help="Mirror command stderr into a repository-root DORMAMMU.log file.")
    run_once.set_defaults(handler=_handle_run_once)

    run_loop = subparsers.add_parser(
        "run",
        aliases=["run-loop"],
        help="Run the supervised loop with --prompt or --prompt-file input.",
        description=(
            "Run an external coding-agent CLI under the supervised retry loop.\n"
            "Provide the prompt inline with --prompt or load it from disk with --prompt-file."
        ),
    )
    _add_repo_root(run_loop)
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
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum total attempts including the first run. Defaults to 50. Use -1 for infinite retries.",
    )
    run_loop.add_argument(
        "--max-retries",
        type=int,
        default=None,
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
    _add_guidance_files(run_loop, help="Repeatable Markdown guidance file to embed into the run prompt when it has content.")
    _add_debug(run_loop, help="Mirror command stderr into a repository-root DORMAMMU.log file.")
    run_loop.set_defaults(handler=_handle_run_loop)

    resume_loop = subparsers.add_parser(
        "resume",
        aliases=["resume-loop"],
        help="Resume the most recent supervised loop run from saved .dev state.",
    )
    _add_repo_root(resume_loop)
    resume_loop.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Override the saved maximum total attempts including the first run. Use -1 for infinite retries.",
    )
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
    _add_guidance_files(resume_loop, help="Repeatable Markdown guidance file to refresh bootstrap guidance before resuming.")
    _add_debug(resume_loop, help="Mirror command stderr into a repository-root DORMAMMU.log file.")
    resume_loop.set_defaults(handler=_handle_resume_loop)

    inspect_cli = subparsers.add_parser(
        "inspect-cli",
        help="Inspect an external coding-agent CLI for prompt handling and approval hints.",
    )
    _add_repo_root(inspect_cli)
    _add_agent_cli(inspect_cli)
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
    _add_repo_root(doctor)
    _add_agent_cli(doctor, help="Path to the external coding-agent CLI to validate.")
    doctor.set_defaults(handler=_handle_doctor)

    daemonize = subparsers.add_parser(
        "daemonize",
        help="Watch a prompt directory from JSON config and process prompts sequentially.",
        description=(
            "Watch a prompt directory from a daemon JSON config and process queued prompts "
            "sequentially.\n"
            "Use this for long-running operator flows where prompt files arrive in "
            "prompt_path and result reports are written to result_path."
        ),
        epilog=(
            "Config files used by daemonize:\n"
            "  ~/.dormammu/daemonize.json    Default daemon workflow config\n"
            "  --config daemonize.json       Override daemon workflow config\n"
            "  ./dormammu.json               Optional general runtime config\n"
            "  $DORMAMMU_CONFIG_PATH         Optional override for the runtime config above\n"
            "\n"
            "Examples:\n"
            "  dormammu daemonize --repo-root .\n"
            "  dormammu daemonize --repo-root . --config daemonize.json\n"
            "  DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json dormammu daemonize \\\n"
            "    --repo-root . --config ./ops/daemonize.prod.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_repo_root(daemonize)
    daemonize.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to the daemon JSON config file. Defaults to ~/.dormammu/daemonize.json.",
    )
    _add_guidance_files(daemonize, help="Repeatable Markdown guidance file to embed into daemon phase prompts when it has content.")
    _add_debug(daemonize, help="Mirror daemon stderr into <result_path>/../progress/<prompt>_progress.log and reset it for each new prompt session.")
    daemonize.set_defaults(handler=_handle_daemonize)

    shell = subparsers.add_parser(
        "shell",
        help="Start the interactive dormammu shell.",
    )
    _add_repo_root(shell)
    shell.set_defaults(handler=lambda args: InteractiveShellRunner(repo_root=args.repo_root).run())

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if not args_list:
        return InteractiveShellRunner().run()
    args = parser.parse_args(args_list)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
