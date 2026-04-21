from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, TextIO

from dormammu._utils import iso_now
from dormammu.hook_runner import HookRunResult, HookRunner
from dormammu.hooks import HookEventName, HookResultAction, HookInputPayload, HookSubjectRef
from dormammu.lifecycle import (
    HookExecutionPayload,
    LifecycleEventType,
    LifecycleRecorder,
    build_lifecycle_run_id,
)

if TYPE_CHECKING:
    from dormammu.config import AppConfig
    from dormammu.state import StateRepository


_HOOK_HISTORY_LIMIT = 25


@dataclass(frozen=True, slots=True)
class RuntimeHookSummary:
    event: HookEventName
    source: str
    blocked: bool
    message: str | None
    messages: tuple[str, ...]
    warnings: tuple[dict[str, Any], ...]
    annotations: tuple[dict[str, Any], ...]
    background_jobs: tuple[dict[str, Any], ...]
    run_result: HookRunResult

    def to_state_dict(self) -> dict[str, Any]:
        return {
            "recorded_at": iso_now(),
            "source": self.source,
            "event": self.event.public_name,
            "blocked": self.blocked,
            "message": self.message,
            "messages": list(self.messages),
            "warnings": [dict(item) for item in self.warnings],
            "annotations": [dict(item) for item in self.annotations],
            "background_jobs": [dict(item) for item in self.background_jobs],
            "selected_hooks": [hook.name for hook in self.run_result.selected_hooks],
            "subject": (
                self.run_result.hook_input.subject.to_dict()
                if self.run_result.hook_input.subject is not None
                else None
            ),
            "hook_input": self.run_result.hook_input.to_dict(),
            "executed": [record.to_dict() for record in self.run_result.executed],
        }


class RuntimeHookBlocked(RuntimeError):
    def __init__(self, summary: RuntimeHookSummary) -> None:
        self.summary = summary
        super().__init__(
            summary.message
            or f"Runtime hook blocked {summary.event.value} in {summary.source}."
        )


class RuntimeHookController:
    """Centralized runtime hook adapter for lifecycle and governed runtime events."""

    def __init__(
        self,
        config: AppConfig,
        *,
        repository: StateRepository | None = None,
        progress_stream: TextIO | None = None,
        runner: HookRunner | None = None,
    ) -> None:
        self._config = config
        self._repository = repository
        self._progress_stream = progress_stream
        self._runner = runner or HookRunner(config)

    def emit_prompt_intake(
        self,
        *,
        prompt_text: str,
        source: str,
        entrypoint: str,
        session_id: str | None,
        run_id: str | None = None,
        agent_role: str | None,
    ) -> RuntimeHookSummary | None:
        return self._emit(
            event=HookEventName.PROMPT_INTAKE,
            source=source,
            session_id=session_id,
            run_id=run_id,
            agent_role=agent_role,
            subject=HookSubjectRef(kind="prompt", name=entrypoint),
            payload={
                "entrypoint": entrypoint,
                "prompt_text": prompt_text,
            },
        )

    def emit_plan_start(
        self,
        *,
        source: str,
        goal_text: str,
        stem: str,
        date_str: str,
        session_id: str | None,
        run_id: str | None = None,
    ) -> RuntimeHookSummary | None:
        return self._emit(
            event=HookEventName.PLAN_START,
            source=source,
            session_id=session_id,
            run_id=run_id,
            agent_role="planner",
            subject=HookSubjectRef(kind="stage", id="planner", name="planner"),
            payload={
                "goal_text": goal_text,
                "stem": stem,
                "date": date_str,
            },
        )

    def emit_stage_start(
        self,
        *,
        source: str,
        stage_name: str,
        agent_role: str,
        session_id: str | None,
        run_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimeHookSummary | None:
        return self._emit_stage_event(
            event=HookEventName.STAGE_START,
            source=source,
            stage_name=stage_name,
            agent_role=agent_role,
            session_id=session_id,
            run_id=run_id,
            payload=payload,
            metadata=metadata,
        )

    def emit_stage_complete(
        self,
        *,
        source: str,
        stage_name: str,
        agent_role: str,
        session_id: str | None,
        run_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimeHookSummary | None:
        return self._emit_stage_event(
            event=HookEventName.STAGE_COMPLETE,
            source=source,
            stage_name=stage_name,
            agent_role=agent_role,
            session_id=session_id,
            run_id=run_id,
            payload=payload,
            metadata=metadata,
        )

    def emit_tool_execution(
        self,
        *,
        source: str,
        tool_name: str,
        session_id: str | None,
        agent_role: str | None,
        run_id: str | None = None,
        tool_target: str | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        subject: HookSubjectRef | None = None,
    ) -> RuntimeHookSummary | None:
        target = tool_target or tool_name
        tool_payload = {
            "tool_name": tool_name,
            "tool_target": target,
        }
        if payload:
            tool_payload.update(dict(payload))
        return self._emit(
            event=HookEventName.TOOL_EXECUTION,
            source=source,
            session_id=session_id,
            run_id=run_id,
            agent_role=agent_role,
            subject=subject
            or HookSubjectRef(
                kind="tool",
                id=target,
                name=tool_name,
            ),
            payload=tool_payload,
            metadata=metadata,
        )

    def emit_final_verification(
        self,
        *,
        source: str,
        session_id: str | None,
        run_id: str | None,
        agent_role: str,
        attempt_number: int,
        report: Mapping[str, Any],
    ) -> RuntimeHookSummary | None:
        return self._emit(
            event=HookEventName.FINAL_VERIFICATION,
            source=source,
            session_id=session_id,
            run_id=run_id,
            agent_role=agent_role,
            subject=HookSubjectRef(kind="verification", name="final_verification"),
            payload={
                "attempt_number": attempt_number,
                "report": dict(report),
            },
        )

    def emit_session_end(
        self,
        *,
        source: str,
        session_id: str | None,
        run_id: str | None,
        agent_role: str | None,
        result: Mapping[str, Any],
    ) -> RuntimeHookSummary | None:
        return self._emit(
            event=HookEventName.SESSION_END,
            source=source,
            session_id=session_id,
            run_id=run_id,
            agent_role=agent_role,
            subject=HookSubjectRef(kind="session", id=session_id, name=source),
            payload={"result": dict(result)},
        )

    def _emit_stage_event(
        self,
        *,
        event: HookEventName,
        source: str,
        stage_name: str,
        agent_role: str,
        session_id: str | None,
        run_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimeHookSummary | None:
        stage_payload = {"stage_name": stage_name}
        if payload:
            stage_payload.update(dict(payload))
        return self._emit(
            event=event,
            source=source,
            session_id=session_id,
            run_id=run_id,
            agent_role=agent_role,
            subject=HookSubjectRef(kind="stage", id=stage_name, name=stage_name),
            payload=stage_payload,
            metadata=metadata,
        )

    def _emit(
        self,
        *,
        event: HookEventName,
        source: str,
        session_id: str | None,
        run_id: str | None = None,
        agent_role: str | None = None,
        subject: HookSubjectRef | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimeHookSummary | None:
        if not self._has_runtime_hooks():
            return None

        selected_hooks = self._runner.select_sync_hooks(event)
        if not selected_hooks:
            return None

        hook_input = HookInputPayload(
            event=event,
            emitted_at=iso_now(),
            session_id=session_id,
            run_id=run_id,
            agent_role=agent_role,
            subject=subject,
            payload=dict(payload or {}),
            metadata=dict(metadata or {}),
        )
        lifecycle = LifecycleRecorder(
            repository=self._repository,
            run_id=run_id or build_lifecycle_run_id(
                "hook",
                session_id=session_id,
                label=event.value,
            ),
            session_id=session_id,
            default_metadata={"source": source},
        )
        lifecycle.emit(
            event_type=LifecycleEventType.HOOK_EXECUTION_STARTED,
            role=agent_role,
            stage=subject.id if subject is not None else None,
            status="started",
            payload=HookExecutionPayload(
                hook_event=event.public_name,
                selected_hooks=tuple(hook.name for hook in selected_hooks),
            ),
        )
        run_result = self._runner.run_sync(hook_input)

        summary = self._summarize(run_result=run_result, source=source)
        lifecycle.emit(
            event_type=LifecycleEventType.HOOK_EXECUTION_FINISHED,
            role=agent_role,
            stage=subject.id if subject is not None else None,
            status="blocked" if summary.blocked else "completed",
            payload=HookExecutionPayload(
                hook_event=event.public_name,
                selected_hooks=tuple(hook.name for hook in run_result.selected_hooks),
                executed_hooks=tuple(record.hook.name for record in run_result.executed),
                blocking_hook=(
                    run_result.blocking_record.hook.name
                    if run_result.blocking_record is not None
                    else None
                ),
                message=summary.message,
            ),
        )
        if self._repository is not None:
            self._repository.record_hook_event(
                summary.to_state_dict(),
                history_limit=_HOOK_HISTORY_LIMIT,
            )
        self._emit_progress(summary)
        if summary.blocked:
            raise RuntimeHookBlocked(summary)
        return summary

    def _has_runtime_hooks(self) -> bool:
        catalog = getattr(self._config, "hooks", None)
        definitions = getattr(catalog, "definitions", None)
        return isinstance(definitions, tuple) and bool(definitions)

    def _summarize(
        self,
        *,
        run_result: HookRunResult,
        source: str,
    ) -> RuntimeHookSummary:
        messages: list[str] = []
        warnings: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []
        background_jobs: list[dict[str, Any]] = []

        for record in run_result.executed:
            result = record.result
            if result.message:
                messages.append(result.message)
            if result.action is HookResultAction.WARN:
                warnings.append(
                    {
                        "hook": record.hook.name,
                        "message": result.message,
                        "metadata": dict(result.metadata),
                    }
                )
            if result.action is HookResultAction.ANNOTATE:
                annotations.append(
                    {
                        "hook": record.hook.name,
                        "annotations": dict(result.annotations),
                        "message": result.message,
                    }
                )
            if result.action is HookResultAction.BACKGROUND_STARTED:
                background_jobs.append(
                    {
                        "hook": record.hook.name,
                        "background_job": (
                            result.background_job.to_dict()
                            if result.background_job is not None
                            else None
                        ),
                        "message": result.message,
                    }
                )

        message = None
        if run_result.blocking_record is not None:
            message = run_result.blocking_record.result.message
        elif messages:
            message = messages[-1]

        return RuntimeHookSummary(
            event=run_result.event,
            source=source,
            blocked=run_result.blocked,
            message=message,
            messages=tuple(messages),
            warnings=tuple(warnings),
            annotations=tuple(annotations),
            background_jobs=tuple(background_jobs),
            run_result=run_result,
        )

    def _emit_progress(self, summary: RuntimeHookSummary) -> None:
        if self._progress_stream is None:
            return
        prefix = f"hooks[{summary.source}] {summary.event.value}:"
        if summary.blocked:
            print(
                f"{prefix} blocked by {summary.run_result.blocking_record.hook.name if summary.run_result.blocking_record else 'unknown'}"
                f" ({summary.message or 'no message'})",
                file=self._progress_stream,
            )
        for item in summary.warnings:
            print(
                f"{prefix} warning from {item['hook']}: {item.get('message') or 'no message'}",
                file=self._progress_stream,
            )
        for item in summary.annotations:
            print(
                f"{prefix} annotations from {item['hook']}",
                file=self._progress_stream,
            )
        for item in summary.background_jobs:
            print(
                f"{prefix} background job started by {item['hook']}",
                file=self._progress_stream,
            )
        self._progress_stream.flush()
