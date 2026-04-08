from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from typing import Callable

from dormammu.agent.command_builder import build_command_plan
from dormammu.agent.help_parser import parse_help_text
from dormammu.agent.models import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunStarted,
    CliCapabilities,
)
from dormammu.config import AppConfig


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_label(text: str | None) -> str:
    if not text:
        return "agent-run"
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return normalized or "agent-run"


def _run_id(label: str | None) -> str:
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{_safe_label(label)}"


class CliAdapter:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def inspect_capabilities(self, cli_path: Path, *, cwd: Path) -> CliCapabilities:
        try:
            completed = subprocess.run(
                [str(cli_path), "--help"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"CLI executable was not found: {cli_path}") from exc

        help_text = completed.stdout or completed.stderr
        return parse_help_text(
            help_text,
            executable_name=cli_path.name,
            help_exit_code=completed.returncode,
        )

    def run_once(
        self,
        request: AgentRunRequest,
        *,
        on_started: Callable[[AgentRunStarted], None] | None = None,
    ) -> AgentRunResult:
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)

        run_id = _run_id(request.run_label)
        prompt_path = self.config.logs_dir / f"{run_id}.prompt.txt"
        stdout_path = self.config.logs_dir / f"{run_id}.stdout.log"
        stderr_path = self.config.logs_dir / f"{run_id}.stderr.log"
        metadata_path = self.config.logs_dir / f"{run_id}.meta.json"

        prompt_path.write_text(request.prompt_text, encoding="utf-8")

        run_cwd = (request.workdir or request.repo_root).resolve()
        capabilities = self.inspect_capabilities(request.cli_path, cwd=run_cwd)
        command_plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

        started_at = _iso_now()
        started = AgentRunStarted(
            run_id=run_id,
            cli_path=request.cli_path.resolve(),
            workdir=run_cwd,
            prompt_mode=command_plan.prompt_mode,
            command=tuple(command_plan.argv),
            started_at=started_at,
            prompt_path=prompt_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
            capabilities=capabilities,
        )
        if on_started is not None:
            on_started(started)

        with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
            "w",
            encoding="utf-8",
        ) as stderr_file:
            completed = subprocess.run(
                list(command_plan.argv),
                cwd=run_cwd,
                input=command_plan.stdin_input,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                check=False,
            )
        completed_at = _iso_now()

        result = AgentRunResult(
            run_id=run_id,
            cli_path=request.cli_path.resolve(),
            workdir=run_cwd,
            prompt_mode=command_plan.prompt_mode,
            command=tuple(command_plan.argv),
            exit_code=completed.returncode,
            started_at=started_at,
            completed_at=completed_at,
            prompt_path=prompt_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
            capabilities=capabilities,
        )

        metadata_path.write_text(
            json.dumps(result.to_dict(include_help_text=True), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return result
