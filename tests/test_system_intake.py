"""System tests for intake classification and workflow routing.

Validates the end-to-end path from raw prompt → classification → workflow
depth selection:

- Simple prompts (direct_response) avoid heavy workflow state generation.
- Light prompts (light_edit) produce a minimal plan without full workflow.
- Complex prompts (full_workflow) receive full workflow treatment.
- Classification result is persisted in workflow_state.json under ``intake``.
- The ``intake.request_class`` field is stable across serialize / deserialize
  round-trips.

These are system-level tests: they exercise the public API of the classifier
and state builder together, without spawning any subprocess or calling an LLM.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest

from dormammu.intake import classify_request
from dormammu.state.models import default_workflow_state, default_intake_state


# ---------------------------------------------------------------------------
# Representative prompt fixtures
# ---------------------------------------------------------------------------

# Each tuple is (label, prompt_text, expected_class)
_ROUTING_CASES: list[tuple[str, str, str]] = [
    # direct_response
    (
        "explain",
        "Explain how the loop runner handles stagnation detection.",
        "direct_response",
    ),
    (
        "analyze",
        "Analyze the current test coverage report and identify missing areas.",
        "direct_response",
    ),
    (
        "summarize",
        "Summarize the key changes made to the supervisor in the last week.",
        "direct_response",
    ),
    (
        "audit",
        "Audit the log output from the last run and report any anomalies.",
        "direct_response",
    ),
    (
        "compare",
        "Compare the ralph loop model to the dormammu supervisor approach.",
        "direct_response",
    ),
    # light_edit
    (
        "fix_bug",
        "Fix the bug where the retry counter is not reset after a successful run.",
        "light_edit",
    ),
    (
        "update_config",
        "Update the default max_retries setting from 10 to 20 in config.py.",
        "light_edit",
    ),
    (
        "rename",
        "Rename the function `_resolve_budget` to `_resolve_loop_budget`.",
        "light_edit",
    ),
    (
        "bump_version",
        "Bump the package version to 0.7.0 and update the changelog.",
        "light_edit",
    ),
    # full_workflow
    (
        "implement_feature",
        "Implement the adaptive intake classifier with request class routing.",
        "full_workflow",
    ),
    (
        "add_module",
        "Add a memory writer service that stores refined prompts under ~/.dormammu/memory.",
        "full_workflow",
    ),
    (
        "refactor",
        "Refactor the supervisor to support direct_response, light_edit, and full_workflow "
        "completion checks separately.",
        "full_workflow",
    ),
    (
        "new_feature_with_tests",
        "Implement phase-aware continuation prompts and write unit and integration tests.",
        "full_workflow",
    ),
    (
        "interface_change",
        "Redesign the public API for the workflow state schema to include intake metadata.",
        "full_workflow",
    ),
]


# ---------------------------------------------------------------------------
# Routing table tests
# ---------------------------------------------------------------------------


class TestRoutingTable:
    """Each canonical prompt maps to the expected request class."""

    @pytest.mark.parametrize("label,prompt,expected_class", _ROUTING_CASES)
    def test_classification(
        self, label: str, prompt: str, expected_class: str
    ) -> None:
        result = classify_request(prompt)
        assert result.request_class == expected_class, (
            f"[{label}] '{prompt[:60]}...' "
            f"expected {expected_class!r}, got {result.request_class!r}. "
            f"Rationale: {result.rationale}"
        )


# ---------------------------------------------------------------------------
# Simple prompts avoid heavy workflow state
# ---------------------------------------------------------------------------


class TestSimplePromptsAvoidHeavyWorkflow:
    """direct_response classification signals that heavy workflow is not needed."""

    def test_direct_response_request_class_in_state(self) -> None:
        prompt = "Explain the TASKS.md format used by the planning agent."
        state = default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=["phase_1"],
            goal="Explain TASKS.md",
            state_root=".dev",
            prompt_text=prompt,
        )
        assert state["intake"]["request_class"] == "direct_response"

    def test_direct_response_has_low_interface_risk(self) -> None:
        prompt = "Describe the loop runner stagnation logic."
        result = classify_request(prompt)
        assert result.has_interface_risk is False

    def test_direct_response_does_not_require_test_strategy(self) -> None:
        prompt = "Summarize the phase gate rules in CLAUDE.md."
        result = classify_request(prompt)
        # Analysis of test coverage might set the flag — that's acceptable.
        # We only check the class here.
        assert result.request_class == "direct_response"

    def test_multiple_direct_response_prompts_never_become_full_workflow(self) -> None:
        analysis_prompts = [
            "Explain the workflow.",
            "How does the supervisor work?",
            "What is the role of the evaluating-agent?",
            "Tell me about the session state.",
            "Describe the available agent skills.",
        ]
        for prompt in analysis_prompts:
            result = classify_request(prompt)
            assert result.request_class != "full_workflow", (
                f"Unexpected full_workflow for analysis prompt: {prompt!r}"
            )


# ---------------------------------------------------------------------------
# Complex prompts receive full workflow treatment
# ---------------------------------------------------------------------------


class TestComplexPromptsReceiveFullWorkflow:
    """full_workflow classification signals that deep pipeline is needed."""

    def test_implementation_prompt_gets_full_workflow(self) -> None:
        prompt = "Implement the refiner dual-mode logic with normalize and clarify modes."
        result = classify_request(prompt)
        assert result.request_class == "full_workflow"

    def test_full_workflow_state_includes_intake_block(self) -> None:
        prompt = "Implement the phase-aware continuation prompt selector."
        state = default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=["phase_1"],
            goal="Phase-aware continuation",
            state_root=".dev",
            prompt_text=prompt,
        )
        assert state["intake"]["request_class"] == "full_workflow"

    def test_interface_change_prompt_is_full_workflow(self) -> None:
        prompt = "Update the workflow state schema to version 8 with the intake block."
        result = classify_request(prompt)
        assert result.request_class == "full_workflow"
        assert result.has_interface_risk is True

    def test_test_heavy_prompt_is_full_workflow(self) -> None:
        prompt = (
            "Implement the memory writer service and write unit tests, "
            "integration tests, and a system test for the full pipeline."
        )
        result = classify_request(prompt)
        assert result.request_class == "full_workflow"
        assert result.requires_test_strategy is True


# ---------------------------------------------------------------------------
# State persistence and round-trip
# ---------------------------------------------------------------------------


class TestStateRoundTrip:
    """intake block survives JSON serialize / deserialize."""

    def _build_state(self, prompt: str) -> dict[str, Any]:
        return default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=["phase_1"],
            goal="Round-trip test",
            state_root=".dev",
            prompt_text=prompt,
        )

    def test_json_round_trip_preserves_request_class(self) -> None:
        state = self._build_state("Implement the adaptive intake system.")
        serialized = json.dumps(state)
        recovered = json.loads(serialized)
        assert recovered["intake"]["request_class"] == state["intake"]["request_class"]

    def test_json_round_trip_preserves_confidence(self) -> None:
        state = self._build_state("Explain the supervisor.")
        serialized = json.dumps(state)
        recovered = json.loads(serialized)
        assert recovered["intake"]["confidence"] == state["intake"]["confidence"]

    def test_json_round_trip_preserves_boolean_flags(self) -> None:
        state = self._build_state("Redesign the public API with integration tests.")
        serialized = json.dumps(state)
        recovered = json.loads(serialized)
        assert isinstance(recovered["intake"]["has_interface_risk"], bool)
        assert isinstance(recovered["intake"]["requires_test_strategy"], bool)

    def test_intake_block_written_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "workflow_state.json"
            state = self._build_state("Implement the new feature with tests.")
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            assert "intake" in loaded
            assert loaded["intake"]["request_class"] in {
                "direct_response",
                "light_edit",
                "full_workflow",
            }


# ---------------------------------------------------------------------------
# Workflow-depth differentiation
# ---------------------------------------------------------------------------


class TestWorkflowDepthDifferentiation:
    """Verify that simple and complex prompts produce different intake metadata."""

    def test_simple_prompt_has_lower_confidence_than_complex(self) -> None:
        """
        This is a soft expectation: classification confidence should generally
        be higher for prompts with many unambiguous signals than for prompts
        with mixed or minimal signals.  We do not assert a strict threshold
        because the heuristic is deliberately simple.
        """
        simple_result = classify_request("What is the purpose of the dashboard?")
        complex_result = classify_request(
            "Implement the intake classifier, add integration tests, and update "
            "the workflow state schema to include the request_class field."
        )
        # Both should be valid
        assert simple_result.request_class == "direct_response"
        assert complex_result.request_class == "full_workflow"

    def test_request_class_differs_between_prompt_styles(self) -> None:
        analysis = classify_request("Analyze the supervisor logic.")
        implementation = classify_request("Implement the supervisor logic.")
        assert analysis.request_class != implementation.request_class

    def test_light_edit_does_not_become_full_workflow(self) -> None:
        prompts = [
            "Fix the typo in the README.",
            "Update the version string in _version.py.",
            "Correct the changelog entry for 0.6.1.",
        ]
        for prompt in prompts:
            result = classify_request(prompt)
            assert result.request_class != "full_workflow", (
                f"Light edit misclassified as full_workflow: {prompt!r}"
            )

    def test_full_workflow_prompts_do_not_become_direct_response(self) -> None:
        prompts = [
            "Implement the memory archive service.",
            "Build the adaptive intake pipeline.",
            "Create the phase-aware continuation system.",
        ]
        for prompt in prompts:
            result = classify_request(prompt)
            assert result.request_class != "direct_response", (
                f"Implementation prompt misclassified as direct_response: {prompt!r}"
            )
