"""Unit tests for the workflow simplification policy (dormammu.workflow_policy).

Validates:
- Phase selection per request class (required vs skipped)
- Skip rationale is populated for every skipped phase
- Minimal workflow sequences match the declared policy
- Policy is stable across serialize/deserialize (JSON round-trip)
- State integration: workflow_policy block is included in workflow_state.json
- Simple requests do not generate full workflow state
- Complex requests still receive full workflow protection
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

from dormammu.workflow_policy import (
    ALL_PHASES,
    MINIMAL_WORKFLOWS,
    SKIP_POLICY,
    WorkflowPolicy,
    resolve_workflow_policy,
    default_workflow_policy_state,
)
from dormammu.state.models import default_workflow_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy(request_class: str) -> WorkflowPolicy:
    return resolve_workflow_policy(request_class)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# direct_response policy
# ---------------------------------------------------------------------------


class TestDirectResponsePolicy:
    """direct_response: all heavy phases are skipped."""

    def test_returns_policy_instance(self) -> None:
        assert isinstance(_policy("direct_response"), WorkflowPolicy)

    def test_request_class_preserved(self) -> None:
        assert _policy("direct_response").request_class == "direct_response"

    def test_develop_is_skipped(self) -> None:
        p = _policy("direct_response")
        assert p.is_phase_skipped("develop")

    def test_commit_is_skipped(self) -> None:
        p = _policy("direct_response")
        assert p.is_phase_skipped("commit")

    def test_plan_is_skipped(self) -> None:
        p = _policy("direct_response")
        assert p.is_phase_skipped("plan")

    def test_design_is_skipped(self) -> None:
        p = _policy("direct_response")
        assert p.is_phase_skipped("design")

    def test_test_author_is_skipped(self) -> None:
        p = _policy("direct_response")
        assert p.is_phase_skipped("test_author")

    def test_required_phases_is_empty(self) -> None:
        # direct_response requires no formal pipeline phases.
        p = _policy("direct_response")
        assert len(p.required_phases) == 0

    def test_all_phases_have_skip_rationale(self) -> None:
        p = _policy("direct_response")
        for phase in p.skipped_phases:
            assert p.skip_reason(phase), f"Missing rationale for skipped phase {phase!r}"

    def test_minimal_workflow_is_empty_for_direct_response(self) -> None:
        assert MINIMAL_WORKFLOWS["direct_response"] == []

    def test_dashboard_summary_contains_request_class(self) -> None:
        p = _policy("direct_response")
        summary = p.dashboard_summary()
        assert "direct_response" in summary


# ---------------------------------------------------------------------------
# planning_only policy
# ---------------------------------------------------------------------------


class TestPlanningOnlyPolicy:
    """planning_only: refine and plan are required; implementation loops are skipped."""

    def test_returns_policy_instance(self) -> None:
        assert isinstance(_policy("planning_only"), WorkflowPolicy)

    def test_request_class_preserved(self) -> None:
        assert _policy("planning_only").request_class == "planning_only"

    def test_refine_and_plan_are_required(self) -> None:
        p = _policy("planning_only")
        assert p.is_phase_required("refine")
        assert p.is_phase_required("plan")

    def test_develop_and_test_are_skipped(self) -> None:
        p = _policy("planning_only")
        assert p.is_phase_skipped("develop")
        assert p.is_phase_skipped("test_author")
        assert p.is_phase_skipped("test_and_review")

    def test_commit_is_skipped(self) -> None:
        p = _policy("planning_only")
        assert p.is_phase_skipped("commit")

    def test_minimal_workflow_stops_after_plan(self) -> None:
        assert MINIMAL_WORKFLOWS["planning_only"] == ["refine", "plan"]


# ---------------------------------------------------------------------------
# light_edit policy
# ---------------------------------------------------------------------------


class TestLightEditPolicy:
    """light_edit: plan, develop, test_and_review, final_verify, commit are required."""

    def test_returns_policy_instance(self) -> None:
        assert isinstance(_policy("light_edit"), WorkflowPolicy)

    def test_request_class_preserved(self) -> None:
        assert _policy("light_edit").request_class == "light_edit"

    def test_plan_is_required(self) -> None:
        p = _policy("light_edit")
        assert p.is_phase_required("plan")

    def test_develop_is_required(self) -> None:
        p = _policy("light_edit")
        assert p.is_phase_required("develop")

    def test_test_and_review_is_required(self) -> None:
        p = _policy("light_edit")
        assert p.is_phase_required("test_and_review")

    def test_final_verify_is_required(self) -> None:
        p = _policy("light_edit")
        assert p.is_phase_required("final_verify")

    def test_commit_is_required(self) -> None:
        p = _policy("light_edit")
        assert p.is_phase_required("commit")

    def test_evaluator_check_is_skipped(self) -> None:
        p = _policy("light_edit")
        assert p.is_phase_skipped("evaluator_check")

    def test_design_is_skipped(self) -> None:
        p = _policy("light_edit")
        assert p.is_phase_skipped("design")

    def test_evaluate_is_skipped(self) -> None:
        # Post-commit evaluator is goals-scheduler only.
        p = _policy("light_edit")
        assert p.is_phase_skipped("evaluate")

    def test_skipped_phases_have_rationale(self) -> None:
        p = _policy("light_edit")
        for phase in p.skipped_phases:
            assert p.skip_reason(phase), f"Missing rationale for skipped phase {phase!r}"

    def test_required_phase_has_no_skip_rationale(self) -> None:
        p = _policy("light_edit")
        for phase in p.required_phases:
            assert p.skip_reason(phase) is None, (
                f"Required phase {phase!r} unexpectedly has a skip rationale"
            )

    def test_minimal_workflow_matches_required_phases(self) -> None:
        p = _policy("light_edit")
        minimal = MINIMAL_WORKFLOWS["light_edit"]
        for phase in minimal:
            assert p.is_phase_required(phase), (
                f"Phase {phase!r} is in MINIMAL_WORKFLOWS but not required by policy"
            )

    def test_fewer_required_phases_than_full_workflow(self) -> None:
        light = _policy("light_edit")
        full = _policy("full_workflow")
        assert len(light.required_phases) < len(full.required_phases)


# ---------------------------------------------------------------------------
# full_workflow policy
# ---------------------------------------------------------------------------


class TestFullWorkflowPolicy:
    """full_workflow: almost all phases are required; only evaluate (goals-scheduler) is skipped."""

    def test_returns_policy_instance(self) -> None:
        assert isinstance(_policy("full_workflow"), WorkflowPolicy)

    def test_request_class_preserved(self) -> None:
        assert _policy("full_workflow").request_class == "full_workflow"

    def test_refine_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("refine")

    def test_plan_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("plan")

    def test_evaluator_check_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("evaluator_check")

    def test_design_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("design")

    def test_develop_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("develop")

    def test_test_author_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("test_author")

    def test_test_and_review_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("test_and_review")

    def test_final_verify_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("final_verify")

    def test_commit_is_required(self) -> None:
        p = _policy("full_workflow")
        assert p.is_phase_required("commit")

    def test_evaluate_is_skipped_for_manual_runs(self) -> None:
        # Goals-scheduler evaluator must be skipped for manually-invoked runs.
        p = _policy("full_workflow")
        assert p.is_phase_skipped("evaluate")

    def test_required_phases_are_superset_of_light_edit(self) -> None:
        light_required = set(_policy("light_edit").required_phases)
        full_required = set(_policy("full_workflow").required_phases)
        assert light_required.issubset(full_required)

    def test_all_required_phases_have_no_skip_rationale(self) -> None:
        p = _policy("full_workflow")
        for phase in p.required_phases:
            assert p.skip_reason(phase) is None

    def test_minimal_workflow_matches_required_phases_subset(self) -> None:
        p = _policy("full_workflow")
        minimal = MINIMAL_WORKFLOWS["full_workflow"]
        for phase in minimal:
            assert p.is_phase_required(phase)


# ---------------------------------------------------------------------------
# Policy invariants across all classes
# ---------------------------------------------------------------------------


class TestPolicyInvariants:
    """Structural invariants that must hold for all request classes."""

    @pytest.mark.parametrize(
        "rc", ["direct_response", "planning_only", "light_edit", "full_workflow"]
    )
    def test_every_phase_is_either_required_or_skipped(self, rc: str) -> None:
        p = _policy(rc)
        all_known = set(ALL_PHASES)
        required = set(p.required_phases)
        skipped = set(p.skipped_phases)
        assert required | skipped == all_known, (
            f"[{rc}] Phases not accounted for: {all_known - required - skipped}"
        )

    @pytest.mark.parametrize(
        "rc", ["direct_response", "planning_only", "light_edit", "full_workflow"]
    )
    def test_required_and_skipped_are_disjoint(self, rc: str) -> None:
        p = _policy(rc)
        overlap = set(p.required_phases) & set(p.skipped_phases)
        assert not overlap, f"[{rc}] Phases in both required and skipped: {overlap}"

    @pytest.mark.parametrize(
        "rc", ["direct_response", "planning_only", "light_edit", "full_workflow"]
    )
    def test_skipped_phases_all_have_rationale(self, rc: str) -> None:
        p = _policy(rc)
        for phase in p.skipped_phases:
            reason = p.skip_reason(phase)
            assert reason and reason.strip(), (
                f"[{rc}] Skipped phase {phase!r} has empty rationale"
            )

    @pytest.mark.parametrize(
        "rc", ["direct_response", "planning_only", "light_edit", "full_workflow"]
    )
    def test_to_dict_has_required_keys(self, rc: str) -> None:
        p = _policy(rc)
        d = p.to_dict()
        assert "request_class" in d
        assert "required_phases" in d
        assert "skipped_phases" in d
        assert "skip_rationale" in d

    def test_full_workflow_has_more_required_phases_than_light_edit(self) -> None:
        full = _policy("full_workflow")
        light = _policy("light_edit")
        assert len(full.required_phases) > len(light.required_phases)

    def test_light_edit_has_more_required_phases_than_direct_response(self) -> None:
        light = _policy("light_edit")
        direct = _policy("direct_response")
        assert len(light.required_phases) > len(direct.required_phases)

    def test_planning_only_has_no_developer_or_tester_phases(self) -> None:
        planning = _policy("planning_only")
        assert "develop" not in planning.required_phases
        assert "test_author" not in planning.required_phases
        assert "test_and_review" not in planning.required_phases

    def test_invalid_request_class_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown request_class"):
            resolve_workflow_policy("unknown_class")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# default_workflow_policy_state
# ---------------------------------------------------------------------------


class TestDefaultWorkflowPolicyState:
    """default_workflow_policy_state returns a JSON-serializable dict."""

    def test_returns_dict(self) -> None:
        state = default_workflow_policy_state("full_workflow")
        assert isinstance(state, dict)

    def test_has_required_phases_key(self) -> None:
        state = default_workflow_policy_state("light_edit")
        assert "required_phases" in state

    def test_has_skipped_phases_key(self) -> None:
        state = default_workflow_policy_state("direct_response")
        assert "skipped_phases" in state

    def test_has_skip_rationale_key(self) -> None:
        state = default_workflow_policy_state("full_workflow")
        assert "skip_rationale" in state

    def test_json_serializable(self) -> None:
        state = default_workflow_policy_state("full_workflow")
        json_str = json.dumps(state)
        recovered = json.loads(json_str)
        assert recovered["required_phases"] == state["required_phases"]


# ---------------------------------------------------------------------------
# State integration
# ---------------------------------------------------------------------------


class TestStateIntegration:
    """workflow_policy block is included in workflow_state.json."""

    def _build_state(self, prompt: str) -> dict[str, Any]:
        return default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=["phase_1"],
            goal="Test goal",
            state_root=".dev",
            prompt_text=prompt,
        )

    def test_workflow_state_includes_workflow_policy_block(self) -> None:
        state = self._build_state("Implement the adaptive intake system.")
        assert "workflow_policy" in state

    def test_workflow_policy_has_correct_request_class(self) -> None:
        state = self._build_state("Implement the intake classifier with tests.")
        assert state["workflow_policy"]["request_class"] == "full_workflow"

    def test_analysis_prompt_skips_develop_and_commit(self) -> None:
        state = self._build_state("Analyze the supervisor logic and explain it.")
        policy = state["workflow_policy"]
        assert "develop" in policy["skipped_phases"]
        assert "commit" in policy["skipped_phases"]

    def test_implementation_prompt_requires_develop_and_commit(self) -> None:
        state = self._build_state("Implement the memory writer service.")
        policy = state["workflow_policy"]
        assert "develop" in policy["required_phases"]
        assert "commit" in policy["required_phases"]

    def test_light_edit_prompt_skips_design_and_evaluator_check(self) -> None:
        state = self._build_state("Fix the typo in config.py.")
        policy = state["workflow_policy"]
        assert "design" in policy["skipped_phases"]
        assert "evaluator_check" in policy["skipped_phases"]

    def test_skip_rationale_is_populated_in_state(self) -> None:
        state = self._build_state("Explain the workflow.")
        policy = state["workflow_policy"]
        for phase in policy["skipped_phases"]:
            assert policy["skip_rationale"].get(phase), (
                f"Missing skip rationale for {phase!r} in workflow_state"
            )

    def test_json_round_trip_preserves_policy(self) -> None:
        state = self._build_state("Build the multi-stage pipeline.")
        serialized = json.dumps(state)
        recovered = json.loads(serialized)
        assert recovered["workflow_policy"]["required_phases"] == (
            state["workflow_policy"]["required_phases"]
        )

    def test_policy_written_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "workflow_state.json"
            state = self._build_state("Implement the feature with tests.")
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            assert "workflow_policy" in loaded
            assert "required_phases" in loaded["workflow_policy"]


# ---------------------------------------------------------------------------
# Simple vs complex workflow differentiation (system-level)
# ---------------------------------------------------------------------------


class TestWorkflowDepthProtection:
    """Verify that simple prompts have fewer required phases than complex ones."""

    def _required_phases(self, prompt: str) -> list[str]:
        state = default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=["phase_1"],
            goal="Test",
            state_root=".dev",
            prompt_text=prompt,
        )
        return state["workflow_policy"]["required_phases"]

    def test_analysis_prompt_has_fewer_required_phases_than_implementation(self) -> None:
        analysis_phases = self._required_phases("Explain how the supervisor works.")
        impl_phases = self._required_phases(
            "Implement the phase-aware continuation prompt selector."
        )
        assert len(analysis_phases) < len(impl_phases)

    def test_implementation_prompt_requires_test_author(self) -> None:
        phases = self._required_phases(
            "Implement the memory archive service with full tests."
        )
        assert "test_author" in phases

    def test_analysis_prompt_skips_test_author(self) -> None:
        phases = self._required_phases("Summarize the test coverage results.")
        assert "test_author" not in phases

    def test_full_workflow_prompt_does_not_skip_evaluator_check(self) -> None:
        phases = self._required_phases(
            "Implement the intake API interface with schema changes and integration tests."
        )
        assert "evaluator_check" in phases

    def test_light_edit_prompt_skips_evaluator_check(self) -> None:
        phases = self._required_phases("Fix the typo in the docstring.")
        assert "evaluator_check" not in phases

    def test_all_request_classes_produce_disjoint_required_phases_count(self) -> None:
        direct = self._required_phases("Describe the architecture.")
        light = self._required_phases("Fix the typo in config.py.")
        full = self._required_phases("Implement the adaptive workflow engine.")
        # direct ≤ light ≤ full (by design)
        assert len(direct) <= len(light) <= len(full)
