"""Helpers for request-class-aware runtime routing."""

from __future__ import annotations

from typing import Any, Mapping

from dormammu.intake import RequestClass, classify_request

_VALID_REQUEST_CLASSES: tuple[RequestClass, ...] = (
    "direct_response",
    "light_edit",
    "full_workflow",
)


def resolve_request_class(
    prompt_text: str,
    *,
    workflow_state: Mapping[str, Any] | None = None,
) -> RequestClass:
    """Resolve the effective request class for *prompt_text*.

    Prefer the intake classification already persisted in ``workflow_state``
    when available so resumed or daemonized runs stay aligned with the active
    session. Fall back to deterministic prompt classification otherwise.
    """

    if isinstance(workflow_state, Mapping):
        intake = workflow_state.get("intake")
        if isinstance(intake, Mapping):
            request_class = intake.get("request_class")
            confidence = intake.get("confidence")
            if (
                request_class == "direct_response"
                and isinstance(confidence, (int, float))
                and float(confidence) < 0.5
            ):
                return "full_workflow"
            if request_class in _VALID_REQUEST_CLASSES:
                return request_class
    classification = classify_request(prompt_text)
    if (
        classification.request_class == "direct_response"
        and classification.confidence < 0.5
    ):
        return "full_workflow"
    return classification.request_class
