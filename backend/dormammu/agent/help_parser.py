from __future__ import annotations

from dormammu.agent.models import CliCapabilities


KNOWN_PROMPT_FILE_FLAGS = (
    "--prompt-file",
    "--input-file",
    "--message-file",
)
KNOWN_PROMPT_ARG_FLAGS = (
    "--prompt",
    "--message",
    "--input",
)
KNOWN_WORKDIR_FLAGS = (
    "--workdir",
    "--cwd",
    "-C",
)


def _first_matching_flag(help_text: str, candidates: tuple[str, ...]) -> str | None:
    for flag in candidates:
        if flag in help_text:
            return flag
    return None


def parse_help_text(help_text: str, *, help_exit_code: int = 0) -> CliCapabilities:
    return CliCapabilities(
        help_flag="--help",
        prompt_file_flag=_first_matching_flag(help_text, KNOWN_PROMPT_FILE_FLAGS),
        prompt_arg_flag=_first_matching_flag(help_text, KNOWN_PROMPT_ARG_FLAGS),
        workdir_flag=_first_matching_flag(help_text, KNOWN_WORKDIR_FLAGS),
        help_text=help_text,
        help_exit_code=help_exit_code,
    )
