from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
import inspect
import json
import os
import subprocess
import time
from typing import Any, Callable, Mapping

from dormammu._utils import iso_now
from dormammu.config import AppConfig
from dormammu.hooks import (
    EffectiveHookDefinition,
    HookEventName,
    HookExecutionMode,
    HookExecutorKind,
    HookInputPayload,
    HookResult,
    parse_hook_result_payload,
)

HookHandler = Callable[[HookInputPayload, EffectiveHookDefinition], HookResult | Mapping[str, Any]]


class HookExecutionError(RuntimeError):
    """Raised when a configured hook cannot be executed or normalized safely."""


@dataclass(frozen=True, slots=True)
class HookExecutionRecord:
    hook: EffectiveHookDefinition
    result: HookResult
    raw_result: dict[str, Any]
    started_at: str
    completed_at: str
    duration_seconds: float
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.result.is_blocking

    def to_dict(self) -> dict[str, object]:
        return {
            "hook": self.hook.to_dict(),
            "result": self.result.to_dict(),
            "raw_result": dict(self.raw_result),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "diagnostics": dict(self.diagnostics),
            "is_blocking": self.is_blocking,
        }


@dataclass(frozen=True, slots=True)
class HookRunResult:
    event: HookEventName
    hook_input: HookInputPayload
    selected_hooks: tuple[EffectiveHookDefinition, ...] = ()
    executed: tuple[HookExecutionRecord, ...] = ()
    blocked: bool = False
    blocking_record: HookExecutionRecord | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event": self.event.value,
            "hook_input": self.hook_input.to_dict(),
            "selected_hooks": [hook.to_dict() for hook in self.selected_hooks],
            "executed": [record.to_dict() for record in self.executed],
            "blocked": self.blocked,
            "blocking_record": self.blocking_record.to_dict() if self.blocking_record else None,
        }


@dataclass(frozen=True, slots=True)
class _NormalizedExecutionOutcome:
    result: HookResult
    raw_result: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class HookRunner:
    def __init__(
        self,
        config: AppConfig,
        *,
        builtin_handlers: Mapping[str, HookHandler] | None = None,
    ) -> None:
        self._config = config
        self._builtin_handlers = dict(builtin_handlers or {})

    def run_sync(self, hook_input: HookInputPayload) -> HookRunResult:
        selected_hooks = tuple(self._select_sync_hooks(hook_input.event))
        executed: list[HookExecutionRecord] = []

        for hook in selected_hooks:
            record = self._execute_hook(hook, hook_input)
            executed.append(record)
            if record.is_blocking:
                return HookRunResult(
                    event=hook_input.event,
                    hook_input=hook_input,
                    selected_hooks=selected_hooks,
                    executed=tuple(executed),
                    blocked=True,
                    blocking_record=record,
                )

        return HookRunResult(
            event=hook_input.event,
            hook_input=hook_input,
            selected_hooks=selected_hooks,
            executed=tuple(executed),
            blocked=False,
            blocking_record=None,
        )

    def _select_sync_hooks(self, event: HookEventName) -> tuple[EffectiveHookDefinition, ...]:
        catalog = self._config.hooks
        if catalog is None:
            return ()
        return tuple(
            hook
            for hook in catalog.definitions
            if hook.event is event
            and hook.definition.enabled
            and hook.definition.execution_mode is HookExecutionMode.SYNC
        )

    def _execute_hook(
        self,
        hook: EffectiveHookDefinition,
        hook_input: HookInputPayload,
    ) -> HookExecutionRecord:
        started_at = iso_now()
        started_monotonic = time.monotonic()
        outcome = self._dispatch_hook(hook, hook_input)
        completed_at = iso_now()
        duration_seconds = time.monotonic() - started_monotonic
        return HookExecutionRecord(
            hook=hook,
            result=outcome.result,
            raw_result=outcome.raw_result,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            diagnostics=outcome.diagnostics,
        )

    def _dispatch_hook(
        self,
        hook: EffectiveHookDefinition,
        hook_input: HookInputPayload,
    ) -> _NormalizedExecutionOutcome:
        kind = hook.definition.target.kind
        if kind is HookExecutorKind.BUILTIN:
            return self._execute_builtin_hook(hook, hook_input)
        if kind is HookExecutorKind.COMMAND:
            return self._execute_command_hook(hook, hook_input)
        if kind is HookExecutorKind.PYTHON:
            return self._execute_python_hook(hook, hook_input)
        raise HookExecutionError(f"Unsupported hook executor kind for {self._hook_label(hook)}: {kind.value}")

    def _execute_builtin_hook(
        self,
        hook: EffectiveHookDefinition,
        hook_input: HookInputPayload,
    ) -> _NormalizedExecutionOutcome:
        handler = self._builtin_handlers.get(hook.definition.target.ref)
        if handler is None:
            raise HookExecutionError(
                f"No builtin hook handler is registered for {self._hook_label(hook)}"
            )
        try:
            raw_output = self._invoke_callable(handler, hook_input, hook)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise HookExecutionError(
                f"Builtin hook execution failed for {self._hook_label(hook)}: {exc}"
            ) from exc
        return self._normalize_execution_output(
            raw_output,
            hook,
            diagnostics={
                "executor": "builtin",
                "ref": hook.definition.target.ref,
            },
        )

    def _execute_python_hook(
        self,
        hook: EffectiveHookDefinition,
        hook_input: HookInputPayload,
    ) -> _NormalizedExecutionOutcome:
        target = self._resolve_python_target(hook.definition.target.ref, hook=hook)
        try:
            raw_output = self._invoke_callable(target, hook_input, hook)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise HookExecutionError(
                f"Python hook execution failed for {self._hook_label(hook)}: {exc}"
            ) from exc
        return self._normalize_execution_output(
            raw_output,
            hook,
            diagnostics={
                "executor": "python",
                "ref": hook.definition.target.ref,
            },
        )

    def _execute_command_hook(
        self,
        hook: EffectiveHookDefinition,
        hook_input: HookInputPayload,
    ) -> _NormalizedExecutionOutcome:
        command = self._command_argv(hook)
        try:
            serialized_input = json.dumps(hook_input.to_dict())
        except (TypeError, ValueError) as exc:
            raise HookExecutionError(
                f"Command hook input could not be JSON-serialized for {self._hook_label(hook)}: {exc}"
            ) from exc
        try:
            completed = subprocess.run(
                command,
                input=serialized_input,
                capture_output=True,
                text=True,
                check=False,
                cwd=self._config.repo_root,
                env=self._subprocess_env(),
                timeout=hook.definition.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise HookExecutionError(
                f"Command hook executable was not found for {self._hook_label(hook)}: {hook.definition.target.ref}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HookExecutionError(
                f"Command hook timed out for {self._hook_label(hook)} after {hook.definition.timeout_seconds} seconds"
            ) from exc

        diagnostics = {
            "executor": "command",
            "command": command,
            "cwd": str(self._config.repo_root),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            raise HookExecutionError(
                f"Command hook exited with status {completed.returncode} for {self._hook_label(hook)}"
            )

        stdout_text = completed.stdout.strip()
        if not stdout_text:
            raise HookExecutionError(
                f"Command hook produced empty stdout for {self._hook_label(hook)}"
            )
        try:
            raw_output = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            raise HookExecutionError(
                f"Command hook returned invalid JSON for {self._hook_label(hook)}"
            ) from exc

        return self._normalize_execution_output(
            raw_output,
            hook,
            diagnostics=diagnostics,
        )

    def _normalize_execution_output(
        self,
        raw_output: HookResult | Mapping[str, Any],
        hook: EffectiveHookDefinition,
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> _NormalizedExecutionOutcome:
        if isinstance(raw_output, HookResult):
            return _NormalizedExecutionOutcome(
                result=raw_output,
                raw_result=raw_output.to_dict(),
                diagnostics=dict(diagnostics or {}),
            )
        if not isinstance(raw_output, Mapping):
            raise HookExecutionError(
                f"Malformed hook output from {self._hook_label(hook)}: "
                f"expected HookResult or JSON object, got {type(raw_output).__name__}"
            )
        raw_result = dict(raw_output)
        try:
            result = parse_hook_result_payload(raw_result, source=self._hook_label(hook))
        except RuntimeError as exc:
            raise HookExecutionError(
                f"Malformed hook output from {self._hook_label(hook)}: {exc}"
            ) from exc
        return _NormalizedExecutionOutcome(
            result=result,
            raw_result=raw_result,
            diagnostics=dict(diagnostics or {}),
        )

    def _command_argv(self, hook: EffectiveHookDefinition) -> list[str]:
        settings = hook.definition.target.settings
        raw_args = settings.get("args", [])
        if not isinstance(raw_args, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw_args
        ):
            raise HookExecutionError(
                f"Command hook args must be a list of non-empty strings for {self._hook_label(hook)}"
            )
        return [hook.definition.target.ref, *raw_args]

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["HOME"] = str(self._config.home_dir)
        env["DORMAMMU_SESSIONS_DIR"] = str(self._config.sessions_dir)
        env["DORMAMMU_BASE_DEV_DIR"] = str(self._config.base_dev_dir)
        env["DORMAMMU_WORKSPACE_ROOT"] = str(self._config.workspace_root)
        env["DORMAMMU_WORKSPACE_PROJECT_ROOT"] = str(self._config.workspace_project_root)
        env["DORMAMMU_TMP_DIR"] = str(self._config.workspace_tmp_dir)
        env["DORMAMMU_RESULTS_DIR"] = str(self._config.results_dir)
        return env

    def _resolve_python_target(
        self,
        ref: str,
        *,
        hook: EffectiveHookDefinition,
    ) -> HookHandler:
        module_name, separator, attribute_path = ref.partition(":")
        if not separator or not module_name.strip() or not attribute_path.strip():
            raise HookExecutionError(
                f"Python hook target must use 'module:callable' for {self._hook_label(hook)}"
            )
        try:
            module = import_module(module_name)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise HookExecutionError(
                f"Failed to import Python hook module for {self._hook_label(hook)}: {module_name}"
            ) from exc

        target: Any = module
        for part in attribute_path.split("."):
            if not hasattr(target, part):
                raise HookExecutionError(
                    f"Python hook target attribute was not found for {self._hook_label(hook)}: {ref}"
                )
            target = getattr(target, part)

        if not callable(target):
            raise HookExecutionError(
                f"Python hook target is not callable for {self._hook_label(hook)}: {ref}"
            )
        return target

    def _invoke_callable(
        self,
        handler: HookHandler,
        hook_input: HookInputPayload,
        hook: EffectiveHookDefinition,
    ) -> HookResult | Mapping[str, Any]:
        try:
            signature = inspect.signature(handler)
        except (TypeError, ValueError):  # pragma: no cover - fallback for unusual callables
            return handler(hook_input, hook)

        positional_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        has_varargs = any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
        if has_varargs or len(positional_params) >= 2:
            return handler(hook_input, hook)
        return handler(hook_input)

    def _hook_label(self, hook: EffectiveHookDefinition) -> str:
        return (
            f"hook {hook.name!r} "
            f"(scope={hook.scope}, config={hook.config_path}, target={hook.definition.target.ref})"
        )
