from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class AutoApproveCandidate:
    value: str
    risk: str
    source: str
    summary: str

    def to_dict(self) -> dict[str, str]:
        return {
            "value": self.value,
            "risk": self.risk,
            "source": self.source,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class AutoApproveInfo:
    supported: bool
    requires_confirmation: bool
    candidates: Sequence[AutoApproveCandidate] = ()
    notes: Sequence[str] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "requires_confirmation": self.requires_confirmation,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class CliCapabilities:
    help_flag: str
    prompt_file_flag: str | None
    prompt_arg_flag: str | None
    workdir_flag: str | None
    help_text: str
    help_exit_code: int
    command_prefix: Sequence[str] = ()
    prompt_positional: bool = False
    preset_key: str | None = None
    preset_label: str | None = None
    preset_source: str | None = None
    auto_approve: AutoApproveInfo | None = None

    def to_dict(self, *, include_help_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "help_flag": self.help_flag,
            "prompt_file_flag": self.prompt_file_flag,
            "prompt_arg_flag": self.prompt_arg_flag,
            "workdir_flag": self.workdir_flag,
            "help_exit_code": self.help_exit_code,
            "command_prefix": list(self.command_prefix),
            "prompt_positional": self.prompt_positional,
            "preset": (
                {
                    "key": self.preset_key,
                    "label": self.preset_label,
                    "source": self.preset_source,
                }
                if self.preset_key is not None
                else None
            ),
            "auto_approve": (
                self.auto_approve.to_dict()
                if self.auto_approve is not None
                else {
                    "supported": False,
                    "requires_confirmation": False,
                    "candidates": [],
                    "notes": [],
                }
            ),
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
class AgentRunStarted:
    run_id: str
    cli_path: Path
    workdir: Path
    prompt_mode: str
    command: Sequence[str]
    started_at: str
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
            "started_at": self.started_at,
            "artifacts": {
                "prompt": str(self.prompt_path),
                "stdout": str(self.stdout_path),
                "stderr": str(self.stderr_path),
                "metadata": str(self.metadata_path),
            },
            "capabilities": self.capabilities.to_dict(include_help_text=include_help_text),
        }


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
    requested_cli_path: Path | None = None
    attempted_cli_paths: Sequence[Path] = ()
    fallback_trigger: str | None = None
    timed_out: bool = False

    def to_dict(self, *, include_help_text: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "cli_path": str(self.cli_path),
            "requested_cli_path": (
                str(self.requested_cli_path) if self.requested_cli_path else str(self.cli_path)
            ),
            "attempted_cli_paths": [
                str(path) for path in (self.attempted_cli_paths or (self.cli_path,))
            ],
            "fallback_trigger": self.fallback_trigger,
            "timed_out": self.timed_out,
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
