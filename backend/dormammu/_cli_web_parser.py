from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable


def add_terminal_and_web_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    add_repo_root: Callable[[argparse.ArgumentParser], None],
    add_debug: Callable[[argparse.ArgumentParser], None],
    handle_terminal: Callable[[argparse.Namespace], int],
    handle_web: Callable[[argparse.Namespace], int],
) -> None:
    terminal = subparsers.add_parser(
        "terminal",
        help="Manage persistent tmux-backed Dormammu terminal sessions.",
        description=(
            "Create, list, attach to, send commands to, and close the same "
            "tmux-backed terminal sessions used by the web UI."
        ),
    )
    terminal_subparsers = terminal.add_subparsers(
        dest="terminal_command",
        required=True,
    )

    terminal_open = terminal_subparsers.add_parser(
        "open",
        help="Create a persistent terminal session.",
    )
    add_repo_root(terminal_open)
    terminal_open.add_argument("--cwd", type=Path, default=None, help="Working directory for the session.")
    terminal_open.add_argument("--cols", type=int, default=120, help="Initial terminal width.")
    terminal_open.add_argument("--rows", type=int, default=32, help="Initial terminal height.")
    terminal_open.set_defaults(handler=handle_terminal)

    terminal_list = terminal_subparsers.add_parser("list", help="List persistent terminal sessions.")
    add_repo_root(terminal_list)
    terminal_list.set_defaults(handler=handle_terminal)

    terminal_attach = terminal_subparsers.add_parser("attach", help="Attach tmux to a terminal session.")
    add_repo_root(terminal_attach)
    terminal_attach.add_argument("session_id", help="Terminal session id.")
    terminal_attach.set_defaults(handler=handle_terminal)

    terminal_send = terminal_subparsers.add_parser("send", help="Send a command to a terminal session.")
    add_repo_root(terminal_send)
    terminal_send.add_argument("session_id", help="Terminal session id.")
    terminal_send.add_argument("text", nargs="+", help="Command text to send.")
    terminal_send.set_defaults(handler=handle_terminal)

    terminal_run = terminal_subparsers.add_parser("run", help="Run Dormammu in an existing terminal session.")
    add_repo_root(terminal_run)
    terminal_run.add_argument("session_id", help="Terminal session id.")
    terminal_run_prompt = terminal_run.add_mutually_exclusive_group(required=True)
    terminal_run_prompt.add_argument("--prompt", help="Prompt text to pass to dormammu run.")
    terminal_run_prompt.add_argument("--prompt-file", help="Prompt file to pass to dormammu run.")
    terminal_run.set_defaults(handler=handle_terminal)

    terminal_run_once = terminal_subparsers.add_parser(
        "run-once",
        help="Run one Dormammu turn in an existing terminal session.",
    )
    add_repo_root(terminal_run_once)
    terminal_run_once.add_argument("session_id", help="Terminal session id.")
    terminal_run_once_prompt = terminal_run_once.add_mutually_exclusive_group(required=True)
    terminal_run_once_prompt.add_argument("--prompt", help="Prompt text to pass to dormammu run-once.")
    terminal_run_once_prompt.add_argument("--prompt-file", help="Prompt file to pass to dormammu run-once.")
    terminal_run_once.set_defaults(handler=handle_terminal)

    terminal_resume = terminal_subparsers.add_parser("resume", help="Resume Dormammu in an existing terminal session.")
    add_repo_root(terminal_resume)
    terminal_resume.add_argument("session_id", help="Terminal session id.")
    terminal_resume.set_defaults(handler=handle_terminal)

    terminal_close = terminal_subparsers.add_parser("close", help="Close a terminal session.")
    add_repo_root(terminal_close)
    terminal_close.add_argument("session_id", help="Terminal session id.")
    terminal_close.set_defaults(handler=handle_terminal)

    web = subparsers.add_parser(
        "web",
        help="Start the Dormammu web terminal and settings server.",
        description=(
            "Serve the TypeScript web terminal, settings UI, and web APIs. "
            "Authentication uses the configured web password or an optional token."
        ),
    )
    add_repo_root(web)
    web.add_argument("--host", default=None, help="Host to bind. Defaults to web.host or 0.0.0.0.")
    web.add_argument("--port", type=int, default=None, help="Port to bind. Defaults to web.port or 9001.")
    web.add_argument("--token", default=None, help="Access token for HTTP and WebSocket auth.")
    add_debug(web)
    web.set_defaults(handler=handle_web)

