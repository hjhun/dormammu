from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class CliCapabilities:
    help_flag: str
    prompt_file_flag: str | None
    prompt_arg_flag: str | None
    workdir_flag: str | None
    help_text: str
    help_exit_code: int

    def to_dict(self, *, include_help_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "help_flag": self.help_flag,
            "prompt_file_flag": self.prompt_file_flag,
            "prompt_arg_flag": self.prompt_arg_flag,
            "workdir_flag": self.workdir_flag,
            "help_exit_code": self.help_exit_code,
        }
        if include_help_text:
            payload["help_text"] = self.help_text
        return payload


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    cli_path: Path
    prompt_text: str
    repo_root: Path
    workdir: Path | None = None
    input_mode: str = "auto"
    prompt_flag: str | None = None
    extra_args: Sequence[str] = ()
    run_label: str | None = None


@dataclass(frozen=True, slots=True)
class CommandPlan:
    argv: Sequence[str]
    prompt_mode: str
    stdin_input: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "prompt_mode": self.prompt_mode,
            "stdin_input": self.stdin_input,
        }


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run_id: str
    cli_path: Path
    workdir: Path
    prompt_mode: str
    command: Sequence[str]
    exit_code: int
    started_at: str
    completed_at: str
    prompt_path: Path
    stdout_path: Path
    stderr_path: Path
    metadata_path: Path
    capabilities: CliCapabilities

    def to_dict(self, *, include_help_text: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "cli_path": str(self.cli_path),
            "workdir": str(self.workdir),
            "prompt_mode": self.prompt_mode,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "artifacts": {
                "prompt": str(self.prompt_path),
                "stdout": str(self.stdout_path),
                "stderr": str(self.stderr_path),
                "metadata": str(self.metadata_path),
            },
            "capabilities": self.capabilities.to_dict(include_help_text=include_help_text),
        }
