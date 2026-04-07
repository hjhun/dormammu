from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Sequence

from dormammu.app import create_app
from dormammu.config import AppConfig
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

    serve = subparsers.add_parser("serve", help="Start the local backend app.")
    serve.add_argument("--repo-root", type=Path, default=None, help="Repository root to use.")
    serve.add_argument("--host", default=None, help="Host interface to bind.")
    serve.add_argument("--port", type=int, default=None, help="Port to bind.")
    serve.add_argument(
        "--skip-init-state",
        action="store_true",
        help="Skip the startup bootstrap state initialization.",
    )
    serve.set_defaults(handler=_handle_serve)

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
