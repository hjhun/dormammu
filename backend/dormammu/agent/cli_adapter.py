from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import time
import threading
from threading import Thread
from typing import Callable, TextIO

from dormammu._utils import iso_now as _iso_now
from dormammu.agent.command_builder import build_command_plan
from dormammu.agent.help_parser import parse_help_text
from dormammu.agent.models import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunStarted,
    CliCapabilities,
)
from dormammu.agent.prompt_identity import prepend_cli_identity
from dormammu.agent.presets import preset_for_executable_name
from dormammu.artifacts import ArtifactWriter
from dormammu.config import AppConfig, CliInvocationConfig, FallbackCliConfig


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


CLI_RETRY_DELAY_SECONDS = 1.0
CLI_RETRY_DELAY_MESSAGE = (
    f"Taking a short break for {int(CLI_RETRY_DELAY_SECONDS)} seconds before the next agent CLI call."
)
CLI_WAIT_POLL_INTERVAL_SECONDS = 0.1
CLI_SHUTDOWN_GRACE_SECONDS = 2.0
CLI_SHUTDOWN_MESSAGE = (
    "\n[dormammu] Agent CLI process interrupted by daemon shutdown request.\n"
)


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
    def __init__(
        self,
        config: AppConfig,
        *,
        live_output_stream: TextIO | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.config = config
        self.live_output_stream = live_output_stream if live_output_stream is not None else sys.stderr
        self.stop_event = stop_event
        self._cli_calls_started = 0

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Keep child CLIs anchored to the resolved HOME contract so ~/.foo
        # lookups behave consistently under dormammu.
        env["HOME"] = str(self.config.home_dir)
        env["DORMAMMU_SESSIONS_DIR"] = str(self.config.sessions_dir)
        env["DORMAMMU_BASE_DEV_DIR"] = str(self.config.base_dev_dir)
        env["DORMAMMU_WORKSPACE_ROOT"] = str(self.config.workspace_root)
        env["DORMAMMU_WORKSPACE_PROJECT_ROOT"] = str(self.config.workspace_project_root)
        env["DORMAMMU_TMP_DIR"] = str(self.config.workspace_tmp_dir)
        env["DORMAMMU_RESULTS_DIR"] = str(self.config.results_dir)
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
            if (
                fallback_reason is None
                and self.config.fallback_on_nonzero_exit
                and enriched.exit_code != 0
                and not enriched.timed_out
            ):
                fallback_reason = f"non-zero exit code {enriched.exit_code}"
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

    def _pause_before_next_cli_call_if_needed(self) -> None:
        if self._cli_calls_started == 0:
            self._cli_calls_started += 1
            return

        if self.live_output_stream is not None:
            print(CLI_RETRY_DELAY_MESSAGE, file=self.live_output_stream)
            self.live_output_stream.flush()
        time.sleep(CLI_RETRY_DELAY_SECONDS)
        self._cli_calls_started += 1

    def _run_single(
        self,
        request: AgentRunRequest,
        *,
        on_started: Callable[[AgentRunStarted], None] | None = None,
    ) -> AgentRunResult:
        self._pause_before_next_cli_call_if_needed()
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        effective_workdir = (request.workdir or Path.cwd()).resolve()
        request = replace(
            request,
            workdir=effective_workdir,
            prompt_text=prepend_cli_identity(request.prompt_text, request.cli_path),
        )

        run_id = _run_id(request.run_label)
        artifact_writer = ArtifactWriter(
            base_dir=self.config.base_dev_dir,
            logs_dir=self.config.logs_dir,
        )
        prompt_path = artifact_writer.run_prompt_path(run_id=run_id)
        stdout_path = artifact_writer.run_stdout_path(run_id=run_id)
        stderr_path = artifact_writer.run_stderr_path(run_id=run_id)
        metadata_path = artifact_writer.run_metadata_path(run_id=run_id)

        artifact_writer.write_text_output(
            kind="prompt",
            text=request.prompt_text,
            path=prompt_path,
            label="prompt",
            run_id=run_id,
        )

        run_cwd = effective_workdir
        capabilities = self.inspect_capabilities(request.cli_path, cwd=run_cwd)
        request = self._apply_default_preset_extra_args(request, capabilities)
        command_plan = build_command_plan(request, capabilities, prompt_path=prompt_path)

        started_at = _iso_now()
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.touch()
        stderr_path.touch()
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
        artifact_writer.write_json_metadata(
            kind="metadata",
            payload=started.to_dict(include_help_text=True),
            path=metadata_path,
            label="metadata",
            run_id=run_id,
        )
        if on_started is not None:
            on_started(started)

        timed_out = False
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
                start_new_session=(os.name == "posix"),
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

            timeout = self.config.process_timeout_seconds
            shutdown_requested = False
            try:
                return_code = self._wait_for_process(
                    process,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                self._kill_process(process)
                process.wait()
                timed_out = True
                return_code = -1
                timeout_message = (
                    f"\n[dormammu] Agent CLI process timed out after {timeout} seconds "
                    "and was forcefully terminated.\n"
                )
                stdout_file.write(timeout_message)
                stdout_file.flush()
                if self.live_output_stream is not None:
                    self.live_output_stream.write(timeout_message)
                    self.live_output_stream.flush()
            except KeyboardInterrupt:
                shutdown_requested = True
                self._terminate_process(process)
                try:
                    process.wait(timeout=CLI_SHUTDOWN_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    self._kill_process(process)
                    process.wait()
                stdout_file.write(CLI_SHUTDOWN_MESSAGE)
                stdout_file.flush()
                if self.live_output_stream is not None:
                    self.live_output_stream.write(CLI_SHUTDOWN_MESSAGE)
                    self.live_output_stream.flush()
                return_code = process.returncode if process.returncode is not None else 130
            stdout_thread.join()
            stderr_thread.join()
            if shutdown_requested:
                raise KeyboardInterrupt()
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
            timed_out=timed_out,
        )

        artifact_writer.write_json_metadata(
            kind="metadata",
            payload=result.to_dict(include_help_text=True),
            path=metadata_path,
            label="metadata",
            run_id=run_id,
        )
        return result

    def _wait_for_process(
        self,
        process: subprocess.Popen[str],
        *,
        timeout: int | None,
    ) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        idle_waiter = threading.Event()
        while True:
            if self.stop_event is not None and self.stop_event.is_set():
                raise KeyboardInterrupt()
            return_code = process.poll()
            if return_code is not None:
                return return_code
            wait_timeout = CLI_WAIT_POLL_INTERVAL_SECONDS
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, timeout)
                wait_timeout = min(wait_timeout, remaining)
            if self.stop_event is not None:
                if self.stop_event.wait(timeout=wait_timeout):
                    raise KeyboardInterrupt()
                continue
            idle_waiter.wait(timeout=wait_timeout)

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        self._signal_process(process, signal.SIGTERM)

    def _kill_process(self, process: subprocess.Popen[str]) -> None:
        self._signal_process(process, signal.SIGKILL)

    def _signal_process(self, process: subprocess.Popen[str], signum: int) -> None:
        if process.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signum)
                return
            except ProcessLookupError:
                return
            except OSError:
                pass
        try:
            process.send_signal(signum)
        except OSError:
            pass

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
        extra_args = self._merge_override_extra_args(
            tuple(override.extra_args),
            tuple(request.extra_args),
        )
        return replace(
            request,
            cli_path=cli_path,
            input_mode=input_mode,
            prompt_flag=prompt_flag,
            extra_args=extra_args,
        )

    def _merge_override_extra_args(
        self,
        override_args: tuple[str, ...],
        request_args: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not override_args:
            return request_args
        if not request_args:
            return override_args

        explicit_flags = {
            arg.strip().lower()
            for arg in request_args
            if arg.startswith("-") and arg.strip()
        }

        merged: list[str] = []
        index = 0
        while index < len(override_args):
            arg = override_args[index]
            normalized = arg.strip().lower()
            if normalized in explicit_flags:
                index += 1
                if index < len(override_args) and not override_args[index].startswith("-"):
                    index += 1
                continue
            merged.append(arg)
            index += 1

        return tuple(merged) + request_args

    def _apply_default_preset_extra_args(
        self,
        request: AgentRunRequest,
        capabilities: CliCapabilities,
    ) -> AgentRunRequest:
        preset = preset_for_executable_name(request.cli_path.name)
        if preset is None or not preset.default_extra_args:
            return request

        extra_args = self._sanitize_preset_extra_args(
            preset_key=preset.key,
            extra_args=tuple(request.extra_args),
        )
        default_args = self._default_preset_args_to_prepend(
            preset_key=preset.key,
            default_extra_args=preset.default_extra_args,
            suppress_flags=preset.suppress_default_extra_args_when_present,
            capabilities=capabilities,
            extra_args=extra_args,
        )
        merged_extra_args = tuple(default_args) + extra_args if default_args else extra_args
        if merged_extra_args == tuple(request.extra_args):
            return request
        return replace(request, extra_args=merged_extra_args)

    def _sanitize_preset_extra_args(
        self,
        *,
        preset_key: str,
        extra_args: tuple[str, ...],
    ) -> tuple[str, ...]:
        if preset_key != "gemini" or not extra_args:
            return extra_args

        parsed_args: list[tuple[str, ...]] = []
        index = 0
        while index < len(extra_args):
            current = extra_args[index]
            if current in {"--approval-mode", "--include-directories"} and index + 1 < len(extra_args):
                parsed_args.append((current, extra_args[index + 1]))
                index += 2
                continue
            parsed_args.append((current,))
            index += 1

        last_approval_index = max(
            (
                item_index
                for item_index, item in enumerate(parsed_args)
                if item[0] in {"--approval-mode", "--yolo"}
            ),
            default=None,
        )
        last_include_index = max(
            (
                item_index
                for item_index, item in enumerate(parsed_args)
                if item[0] == "--include-directories"
            ),
            default=None,
        )

        sanitized: list[str] = []
        for item_index, item in enumerate(parsed_args):
            flag = item[0]
            if flag in {"--approval-mode", "--yolo"} and item_index != last_approval_index:
                continue
            if flag == "--include-directories" and item_index != last_include_index:
                continue
            sanitized.extend(item)
        return tuple(sanitized)

    def _default_preset_args_to_prepend(
        self,
        *,
        preset_key: str,
        default_extra_args: tuple[str, ...],
        suppress_flags: tuple[str, ...],
        capabilities: CliCapabilities,
        extra_args: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized_args = {arg.strip().lower() for arg in extra_args if arg.strip()}

        if preset_key == "codex":
            default_args: list[str] = []
            if not any(
                flag in normalized_args
                for flag in (
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--full-auto",
                    "--ask-for-approval",
                    "-a",
                    "--sandbox",
                    "-s",
                )
            ):
                default_args.append("--dangerously-bypass-approvals-and-sandbox")
            if (
                "--skip-git-repo-check" not in normalized_args
                and "--skip-git-repo-check" in capabilities.help_text.lower()
            ):
                default_args.append("--skip-git-repo-check")
            return tuple(default_args)

        if preset_key == "gemini":
            has_approval_arg, has_include_directories = self._gemini_explicit_arg_state(extra_args)
            default_args = []
            if not has_approval_arg:
                default_args.extend(["--approval-mode", "yolo"])
            if not has_include_directories:
                default_args.extend(["--include-directories", "/"])
            return tuple(default_args)

        if preset_key == "claude_code":
            if any(
                flag in normalized_args
                for flag in (
                    "--permission-mode",
                    "--dangerously-skip-permissions",
                    "--allow-dangerously-skip-permissions",
                )
            ):
                return ()
            return ("--dangerously-skip-permissions",)

        if any(flag.lower() in normalized_args for flag in suppress_flags):
            return ()
        return default_extra_args

    def _gemini_explicit_arg_state(
        self,
        extra_args: tuple[str, ...],
    ) -> tuple[bool, bool]:
        has_approval_arg = False
        has_include_directories = False
        index = 0
        while index < len(extra_args):
            current = extra_args[index].strip().lower()
            if current == "--approval-mode":
                has_approval_arg = True
                index += 2
                continue
            if current == "--yolo":
                has_approval_arg = True
                index += 1
                continue
            if current == "--include-directories":
                has_include_directories = True
                index += 2
                continue
            index += 1
        return has_approval_arg, has_include_directories

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
