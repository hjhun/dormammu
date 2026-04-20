from __future__ import annotations

import pytest

from dormammu.hooks import (
    HookEventName,
    HookExecutionMode,
    HookExecutorKind,
    HookResultAction,
    normalize_hook_event_name,
    parse_hook_definitions,
    parse_hook_input_payload,
    parse_hook_result_payload,
)


def test_normalize_hook_event_name_accepts_public_name_and_internal_alias() -> None:
    assert normalize_hook_event_name("prompt intake") is HookEventName.PROMPT_INTAKE
    assert normalize_hook_event_name("stage_completion") is HookEventName.STAGE_COMPLETE
    assert normalize_hook_event_name("config changes") is HookEventName.CONFIG_CHANGE


def test_normalize_hook_event_name_rejects_unknown_event() -> None:
    with pytest.raises(RuntimeError, match=r"hook\.event must be one of"):
        normalize_hook_event_name("worktree create")


def test_parse_hook_definitions_validates_typed_hook_config_shape() -> None:
    hooks = parse_hook_definitions(
        [
            {
                "name": "policy-guard",
                "event": "stage start",
                "target": {
                    "kind": "builtin",
                    "ref": "policy.stage_guard",
                    "settings": {
                        "severity": "warn",
                    },
                },
                "execution_mode": "sync",
                "timeout_seconds": 15,
                "enabled": True,
                "metadata": {
                    "owner": "policy",
                },
            }
        ],
        source="inline hooks",
    )

    assert len(hooks) == 1
    hook = hooks[0]
    assert hook.name == "policy-guard"
    assert hook.event is HookEventName.STAGE_START
    assert hook.target.kind is HookExecutorKind.BUILTIN
    assert hook.target.ref == "policy.stage_guard"
    assert hook.execution_mode is HookExecutionMode.SYNC
    assert hook.timeout_seconds == 15
    assert hook.metadata == {"owner": "policy"}


def test_parse_hook_definitions_rejects_invalid_event() -> None:
    with pytest.raises(RuntimeError, match=r"hooks\[0\]\.event must be one of"):
        parse_hook_definitions(
            [
                {
                    "name": "broken",
                    "event": "totally unknown",
                    "target": {"kind": "builtin", "ref": "policy.guard"},
                }
            ],
            source="inline hooks",
        )


def test_parse_hook_definitions_rejects_null_hook_list() -> None:
    with pytest.raises(RuntimeError, match=r"hooks must be a JSON array"):
        parse_hook_definitions(
            None,
            source="inline hooks",
        )


def test_parse_hook_definitions_rejects_boolean_timeout_seconds() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"hooks\[0\]\.timeout_seconds must be a positive integer",
    ):
        parse_hook_definitions(
            [
                {
                    "name": "policy-guard",
                    "event": "stage start",
                    "target": {"kind": "builtin", "ref": "policy.stage_guard"},
                    "timeout_seconds": True,
                }
            ],
            source="inline hooks",
        )


def test_parse_hook_input_payload_validates_event_subject_and_payload_shape() -> None:
    payload = parse_hook_input_payload(
        {
            "event": "tool execution",
            "emitted_at": "2026-04-21T02:36:00+09:00",
            "session_id": "session-123",
            "run_id": "run-456",
            "agent_role": "developer",
            "subject": {
                "kind": "tool",
                "name": "rg",
                "metadata": {"source": "cli"},
            },
            "payload": {"argv": ["rg", "hook"]},
            "metadata": {"attempt": 1},
        },
        source="tool event",
    )

    assert payload.event is HookEventName.TOOL_EXECUTION
    assert payload.subject is not None
    assert payload.subject.kind == "tool"
    assert payload.subject.name == "rg"
    assert payload.payload == {"argv": ["rg", "hook"]}
    assert payload.metadata == {"attempt": 1}


def test_parse_hook_result_payload_accepts_warn_and_background_started() -> None:
    warned = parse_hook_result_payload(
        {
            "action": "warn",
            "message": "Policy warning.",
            "annotations": {"policy": "soft-warning"},
        },
        source="hook result",
    )
    background = parse_hook_result_payload(
        {
            "action": "background_started",
            "message": "Audit export queued.",
            "background_job": {
                "job_id": "audit-1",
                "kind": "audit-export",
            },
        },
        source="hook result",
    )

    assert warned.action is HookResultAction.WARN
    assert warned.message == "Policy warning."
    assert warned.annotations == {"policy": "soft-warning"}
    assert background.action is HookResultAction.BACKGROUND_STARTED
    assert background.background_job is not None
    assert background.background_job.job_id == "audit-1"


def test_parse_hook_result_payload_rejects_invalid_action() -> None:
    with pytest.raises(RuntimeError, match=r"hook_result\.action must be one of"):
        parse_hook_result_payload(
            {
                "action": "ask",
            },
            source="hook result",
        )


def test_parse_hook_result_payload_rejects_background_started_without_job() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"hook_result\.background_job is required when action is background_started",
    ):
        parse_hook_result_payload(
            {
                "action": "background_started",
            },
            source="hook result",
        )


def test_parse_hook_result_payload_rejects_annotate_without_annotations() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"hook_result\.annotations must be non-empty when action is annotate",
    ):
        parse_hook_result_payload(
            {
                "action": "annotate",
                "message": "Missing annotation payload.",
            },
            source="hook result",
        )
