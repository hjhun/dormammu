from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.cli import build_parser
from dormammu.operator_commands import COMMAND_MATRIX, command_names_for_surface
from dormammu.telegram.bot import _HELP_TEXT


def test_cli_subcommands_are_registered_in_operator_command_matrix() -> None:
    parser = build_parser()
    subparser_actions = [
        action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
    ]
    assert len(subparser_actions) == 1
    parser_commands = set(subparser_actions[0].choices)

    matrix_commands = set(command_names_for_surface("cli"))

    assert parser_commands <= matrix_commands


def test_telegram_help_commands_are_registered_in_operator_command_matrix() -> None:
    matrix_commands = set(command_names_for_surface("telegram"))

    for command in (
        "/status",
        "/run",
        "/queue",
        "/tail",
        "/result",
        "/sessions",
        "/repo",
        "/clear_sessions",
        "/goals",
        "/shutdown",
    ):
        assert command in matrix_commands
        assert command in _HELP_TEXT


def test_operator_command_matrix_defines_service_and_state_transition() -> None:
    assert COMMAND_MATRIX
    for item in COMMAND_MATRIX:
        assert item.surface in {"cli", "shell", "telegram"}
        assert item.command
        assert item.domain
        assert item.service
        assert item.state_transition in {"read", "write"}
