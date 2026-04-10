from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import Thread
from typing import Callable, TextIO

from dormammu.agent.command_builder import build_command_plan
from dormammu.agent.help_parser import parse_help_text
from dormammu.agent.models import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunStarted,
    CliCapabilities,
)
from dormammu.agent.presets import preset_for_executable_name
from dormammu.config import AppConfig, CliInvocationConfig, FallbackCliConfig


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_label(text: str | None) -> str:
    if not text:
        return "agent-run"
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return normalized or "agent-run"


def _run_id(label: str | None) -> str:
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S-%f")
    return f"{timestamp}-{_safe_label(label)}"


def _recorded_cli_path(cli_path: Path) -> Path:
    text = str(cli_path)
    if cli_path.is_absolute() or "/" in text:
        return Path(os.path.abspath(str(cli_path.expanduser())))
    return cli_path


def _mirror_pipe(
    source: TextIO | None,
    sink: TextIO,
    *,
    mirror: TextIO | None,
) -> None:
    if source is None:
        return
    try:
        for chunk in source:
            sink.write(chunk)
            sink.flush()
            if mirror is not None:
                mirror.write(chunk)
                mirror.flush()
    finally:
        source.close()


class CliAdapter:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.live_output_stream = sys.stderr

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Keep child CLIs anchored to the resolved HOME contract so ~/.foo
        # lookups behave consistently under dormammu.
        env["HOME"] = str(self.config.home_dir)
        return env

    def _run_help_command(
        self,
        argv: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
        )

    def inspect_capabilities(self, cli_path: Path, *, cwd: Path) -> CliCapabilities:
        try:
            completed = self._run_help_command([str(cli_path), "--help"], cwd=cwd)
        except FileNotFoundError as exc:
            raise RuntimeError(f"CLI executable was not found: {cli_path}") from exc

        help_text_parts = [completed.stdout or completed.stderr]
        base_capabilities = parse_help_text(
            help_text_parts[0],
            executable_name=cli_path.name,
            help_exit_code=completed.returncode,
        )
        if base_capabilities.command_prefix:
            try:
                prefixed = self._run_help_command(
                    [str(cli_path), *base_capabilities.command_prefix, "--help"],
                    cwd=cwd,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(f"CLI executable was not found: {cli_path}") from exc
            prefixed_help_text = prefixed.stdout or prefixed.stderr
            if prefixed_help_text:
                help_text_parts.append(prefixed_help_text)

        help_text = "\n".join(part for part in help_text_parts if part)
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
        request = self._apply_cli_override(request, cli_path=request.cli_path)
        candidates = self._build_candidate_requests(request)
        attempted_cli_paths: list[Path] = []
        requested_cli_path = _recorded_cli_path(request.cli_path)
        fallback_trigger: str | None = None

        for index, candidate_request in enumerate(candidates):
            result = self._run_single(candidate_request, on_started=on_started)
            attempted_cli_paths.append(result.cli_path)
            enriched = replace(
                result,
                requested_cli_path=requested_cli_path,
                attempted_cli_paths=tuple(attempted_cli_paths),
                fallback_trigger=fallback_trigger,
            )
            fallback_reason = self._detect_token_exhaustion(enriched)
            if fallback_reason is None or index == len(candidates) - 1:
                return replace(
                    enriched,
                    fallback_trigger=fallback_reason or fallback_trigger,
                )
            fallback_trigger = fallback_reason

        return replace(
            enriched,
            fallback_trigger=fallback_trigger,
        )

    def _run_single(
        self,
        request: AgentRunRequest,
        *,
        on_started: Callable[[AgentRunStarted], None] | None = None,
    ) -> AgentRunResult:
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        effective_workdir = (request.workdir or Path.cwd()).resolve()
        request = replace(request, workdir=effective_workdir)

        run_id = _run_id(request.run_label)
        prompt_path = self.config.logs_dir / f"{run_id}.prompt.txt"
        stdout_path = self.config.logs_dir / f"{run_id}.stdout.log"
        stderr_path = self.config.logs_dir / f"{run_id}.stderr.log"
        metadata_path = self.config.logs_dir / f"{run_id}.meta.json"

        prompt_path.write_text(request.prompt_text, encoding="utf-8")

        run_cwd = effective_workdir
        capabilities = self.inspect_capabilities(request.cli_path, cwd=run_cwd)
        request = self._apply_default_preset_extra_args(request, capabilities)
        command_plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

        started_at = _iso_now()
        started = AgentRunStarted(
            run_id=run_id,
            cli_path=_recorded_cli_path(request.cli_path),
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
            process = subprocess.Popen(
                list(command_plan.argv),
                cwd=run_cwd,
                env=self._subprocess_env(),
                stdin=subprocess.PIPE if command_plan.stdin_input is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            stdout_thread = Thread(
                target=_mirror_pipe,
                args=(process.stdout, stdout_file),
                kwargs={"mirror": self.live_output_stream},
                daemon=True,
            )
            stderr_thread = Thread(
                target=_mirror_pipe,
                args=(process.stderr, stderr_file),
                kwargs={"mirror": self.live_output_stream},
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()

            if process.stdin is not None:
                process.stdin.write(command_plan.stdin_input or "")
                process.stdin.close()

            return_code = process.wait()
            stdout_thread.join()
            stderr_thread.join()
        completed_at = _iso_now()

        result = AgentRunResult(
            run_id=run_id,
            cli_path=_recorded_cli_path(request.cli_path),
            workdir=run_cwd,
            prompt_mode=command_plan.prompt_mode,
            command=tuple(command_plan.argv),
            exit_code=return_code,
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

    def _build_candidate_requests(self, request: AgentRunRequest) -> tuple[AgentRunRequest, ...]:
        candidates = [request]
        seen_paths = {str(request.cli_path)}
        for fallback in self.config.fallback_agent_clis:
            candidate = self._apply_fallback_config(request, fallback)
            key = str(candidate.cli_path)
            if key in seen_paths or not self._cli_candidate_available(candidate.cli_path):
                continue
            seen_paths.add(key)
            candidates.append(candidate)
        return tuple(candidates)

    def _apply_fallback_config(
        self,
        request: AgentRunRequest,
        fallback: FallbackCliConfig,
    ) -> AgentRunRequest:
        fallback_request = replace(
            request,
            cli_path=fallback.path,
            input_mode=fallback.input_mode or "auto",
            prompt_flag=fallback.prompt_flag,
            extra_args=fallback.extra_args,
        )
        return self._apply_cli_override(
            fallback_request,
            cli_path=fallback.path,
        )

    def _apply_cli_override(
        self,
        request: AgentRunRequest,
        *,
        cli_path: Path,
    ) -> AgentRunRequest:
        override = self._resolve_cli_override(cli_path)
        if override is None:
            return request

        input_mode = request.input_mode
        if input_mode == "auto" and override.input_mode is not None:
            input_mode = override.input_mode

        prompt_flag = request.prompt_flag or override.prompt_flag
        extra_args = tuple(override.extra_args) + tuple(request.extra_args)
        return replace(
            request,
            cli_path=cli_path,
            input_mode=input_mode,
            prompt_flag=prompt_flag,
            extra_args=extra_args,
        )

    def _apply_default_preset_extra_args(
        self,
        request: AgentRunRequest,
        capabilities: CliCapabilities,
    ) -> AgentRunRequest:
        preset = preset_for_executable_name(request.cli_path.name)
        if preset is None or not preset.default_extra_args:
            return request

        if preset.key == "codex" and "--skip-git-repo-check" not in capabilities.help_text.lower():
            return request

        extra_args = tuple(request.extra_args)
        normalized_args = {arg.strip().lower() for arg in extra_args if arg.strip()}
        if any(flag.lower() in normalized_args for flag in preset.suppress_default_extra_args_when_present):
            return request

        return replace(
            request,
            extra_args=tuple(preset.default_extra_args) + extra_args,
        )

    def _resolve_cli_override(self, cli_path: Path) -> CliInvocationConfig | None:
        overrides = self.config.cli_overrides or {}
        keys = self._cli_override_keys(cli_path)
        for key in keys:
            override = overrides.get(key)
            if override is not None:
                return override
        return CliInvocationConfig()

    def _cli_override_keys(self, cli_path: Path) -> tuple[str, ...]:
        raw_text = str(cli_path).strip()
        keys = [raw_text.lower(), cli_path.name.lower()]
        if cli_path.is_absolute() or "/" in raw_text:
            keys.append(os.path.abspath(str(cli_path.expanduser())).lower())
        return tuple(dict.fromkeys(key for key in keys if key))

    def _cli_candidate_available(self, cli_path: Path) -> bool:
        raw_text = str(cli_path)
        if cli_path.is_absolute() or "/" in raw_text:
            candidate = cli_path.expanduser()
            return candidate.exists() and os.access(candidate, os.X_OK)
        return shutil.which(raw_text) is not None

    def _detect_token_exhaustion(self, result: AgentRunResult) -> str | None:
        if result.exit_code == 0:
            return None

        combined_output = "\n".join(
            [
                result.stdout_path.read_text(encoding="utf-8"),
                result.stderr_path.read_text(encoding="utf-8"),
            ]
        ).lower()
        for pattern in self.config.token_exhaustion_patterns:
            normalized_pattern = pattern.strip().lower()
            if normalized_pattern and normalized_pattern in combined_output:
                return normalized_pattern
        return None
