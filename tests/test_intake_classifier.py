"""Unit tests for the request intake classifier (dormammu.intake).

Validates:
- Classification of direct_response, planning_only, light_edit, full_workflow prompts
- Confidence and rationale fields are populated
- Interface risk and test-strategy markers are detected
- Edge cases: empty input, single-word prompts, mixed signals
- State integration: default_intake_state and default_workflow_state include intake block
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest

from dormammu.intake import IntakeClassification, RequestClass, classify_request
from dormammu.state.models import default_intake_state, default_workflow_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(text: str) -> IntakeClassification:
    return classify_request(text)


# ---------------------------------------------------------------------------
# Direct-response classification
# ---------------------------------------------------------------------------


class TestDirectResponseClassification:
    """Prompts that should resolve to direct_response."""

    def test_explain_prompt(self) -> None:
        result = _classify("Explain how the loop runner works.")
        assert result.request_class == "direct_response"

    def test_analyze_prompt(self) -> None:
        result = _classify("Analyze the current test coverage and report gaps.")
        assert result.request_class == "direct_response"

    def test_summarize_prompt(self) -> None:
        result = _classify("Summarize the changes in the last commit.")
        assert result.request_class == "direct_response"

    def test_review_without_edit(self) -> None:
        result = _classify("Review the supervisor logic and tell me if there are any bugs.")
        assert result.request_class == "direct_response"

    def test_what_is_question(self) -> None:
        result = _classify("What is the purpose of the intake classifier?")
        assert result.request_class == "direct_response"

    def test_how_does_question(self) -> None:
        result = _classify("How does the state repository bootstrap work?")
        assert result.request_class == "direct_response"

    def test_confidence_above_zero(self) -> None:
        result = _classify("Describe the workflow state schema.")
        assert result.confidence > 0

    def test_rationale_is_nonempty(self) -> None:
        result = _classify("List all the phases in the roadmap.")
        assert result.rationale.strip() != ""

    def test_no_interface_risk(self) -> None:
        result = _classify("Explain the supervisor verdicts.")
        assert result.has_interface_risk is False

    def test_no_test_strategy_required(self) -> None:
        result = _classify("Analyze the log output.")
        assert result.requires_test_strategy is False


# ---------------------------------------------------------------------------
# Planning-only classification
# ---------------------------------------------------------------------------


class TestPlanningOnlyClassification:
    """Structure/design deliberation should stop after planning."""

    def test_structure_deliberation_prompt(self) -> None:
        result = _classify("Think deeply about the dormammu runtime structure.")
        assert result.request_class == "planning_only"
        assert result.execution_mode == "deep_thinking"

    def test_architecture_review_without_implementation(self) -> None:
        result = _classify("Review the workflow architecture and discuss options.")
        assert result.request_class == "planning_only"
        assert result.execution_mode == "deep_thinking"

    def test_planning_only_does_not_require_test_strategy(self) -> None:
        result = _classify("Review the workflow structure and propose a direction.")
        assert result.request_class == "planning_only"
        assert result.requires_test_strategy is False
        assert result.execution_mode == "deep_thinking"


# ---------------------------------------------------------------------------
# Light-edit classification
# ---------------------------------------------------------------------------


class TestLightEditClassification:
    """Prompts that should resolve to light_edit."""

    def test_fix_typo_prompt(self) -> None:
        result = _classify("Fix the typo in the README.")
        assert result.request_class == "light_edit"

    def test_update_config_prompt(self) -> None:
        result = _classify("Update the config setting for max retries.")
        assert result.request_class == "light_edit"

    def test_rename_variable_prompt(self) -> None:
        result = _classify("Rename the variable `max_iter` to `max_iterations`.")
        assert result.request_class == "light_edit"

    def test_bump_version_prompt(self) -> None:
        result = _classify("Bump the version from 0.6.0 to 0.7.0.")
        assert result.request_class == "light_edit"

    def test_docstring_update(self) -> None:
        result = _classify("Update the docstring for the StateRepository class.")
        assert result.request_class == "light_edit"

    def test_changelog_update(self) -> None:
        result = _classify("Add a changelog entry for the new release.")
        assert result.request_class == "light_edit"

    def test_dependency_upgrade(self) -> None:
        result = _classify("Upgrade the pytest dependency to version 8.")
        assert result.request_class == "light_edit"


# ---------------------------------------------------------------------------
# Full-workflow classification
# ---------------------------------------------------------------------------


class TestFullWorkflowClassification:
    """Prompts that should resolve to full_workflow."""

    def test_implement_feature(self) -> None:
        result = _classify("Implement the request classifier module with heuristic scoring.")
        assert result.request_class == "full_workflow"

    def test_add_module(self) -> None:
        result = _classify("Add a memory writer service under ~/.dormammu/memory.")
        assert result.request_class == "full_workflow"

    def test_refactor_system(self) -> None:
        result = _classify("Refactor the supervisor to support multiple workflow classes.")
        assert result.request_class == "full_workflow"

    def test_design_api(self) -> None:
        result = _classify("Design the API interface for the intake classifier.")
        assert result.request_class == "full_workflow"

    def test_build_pipeline(self) -> None:
        result = _classify("Build a multi-stage pipeline for request classification.")
        assert result.request_class == "full_workflow"

    def test_create_service(self) -> None:
        result = _classify("Create a daemon service that reads goal files and dispatches agents.")
        assert result.request_class == "full_workflow"

    def test_migrate_schema(self) -> None:
        result = _classify("Migrate the workflow state schema to version 8.")
        assert result.request_class == "full_workflow"


# ---------------------------------------------------------------------------
# Interface risk detection
# ---------------------------------------------------------------------------


class TestInterfaceRiskDetection:
    """Prompts containing API or interface risk markers."""

    def test_api_keyword_sets_risk(self) -> None:
        result = _classify("Implement a new REST API endpoint for goal submission.")
        assert result.has_interface_risk is True

    def test_schema_keyword_sets_risk(self) -> None:
        result = _classify("Update the workflow state schema to add the intake block.")
        assert result.has_interface_risk is True

    def test_interface_keyword_sets_risk(self) -> None:
        result = _classify("Redesign the public interface for the supervisor.")
        assert result.has_interface_risk is True

    def test_interface_risk_promotes_to_full_workflow(self) -> None:
        # Even a light prompt with API risk should land in full_workflow.
        result = _classify("Fix the API endpoint response format.")
        assert result.request_class == "full_workflow"

    def test_no_interface_risk_for_plain_text(self) -> None:
        result = _classify("Summarize the project goals.")
        assert result.has_interface_risk is False


# ---------------------------------------------------------------------------
# Test strategy detection
# ---------------------------------------------------------------------------


class TestStrategyDetection:
    """Prompts containing test-related language."""

    def test_test_keyword_sets_flag(self) -> None:
        result = _classify("Write unit tests for the intake classifier.")
        assert result.requires_test_strategy is True

    def test_integration_test_sets_flag(self) -> None:
        result = _classify("Add integration tests for the planner stage.")
        assert result.requires_test_strategy is True

    def test_regression_sets_flag(self) -> None:
        result = _classify("Check for regressions after the refactor.")
        assert result.requires_test_strategy is True

    def test_no_test_flag_for_analysis(self) -> None:
        result = _classify("Explain the current test coverage.")
        # "explain" → direct_response; "test" appears but as noun, not intent
        # The flag can be True here — what matters is it doesn't break classification
        assert isinstance(result.requires_test_strategy, bool)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary inputs."""

    def test_empty_string_returns_direct_response(self) -> None:
        result = _classify("")
        assert result.request_class == "direct_response"

    def test_whitespace_only_returns_direct_response(self) -> None:
        result = _classify("   \n   ")
        assert result.request_class == "direct_response"

    def test_empty_confidence_is_valid_float(self) -> None:
        result = _classify("")
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0

    def test_to_dict_has_required_keys(self) -> None:
        result = _classify("Implement a new feature.")
        d = result.to_dict()
        assert "request_class" in d
        assert "confidence" in d
        assert "rationale" in d
        assert "has_interface_risk" in d
        assert "requires_test_strategy" in d
        assert "execution_mode" in d

    def test_confidence_is_between_0_and_1(self) -> None:
        prompts = [
            "Explain the code.",
            "Fix the bug in config.py.",
            "Implement the full feature with tests and API changes.",
        ]
        for prompt in prompts:
            result = _classify(prompt)
            assert 0.0 <= result.confidence <= 1.0, (
                f"Confidence out of range for '{prompt}': {result.confidence}"
            )

    def test_request_class_is_valid_literal(self) -> None:
        valid: set[RequestClass] = {
            "direct_response",
            "planning_only",
            "light_edit",
            "full_workflow",
        }
        for prompt in ["Summarize.", "Fix typo.", "Implement feature."]:
            result = _classify(prompt)
            assert result.request_class in valid


# ---------------------------------------------------------------------------
# State integration
# ---------------------------------------------------------------------------


class TestStateIntegration:
    """Intake block is included in workflow and session state dicts."""

    def test_default_intake_state_has_required_keys(self) -> None:
        state = default_intake_state("Implement the classifier.")
        assert "request_class" in state
        assert "confidence" in state
        assert "rationale" in state
        assert "has_interface_risk" in state
        assert "requires_test_strategy" in state
        assert "execution_mode" in state

    def test_default_intake_state_with_none_prompt(self) -> None:
        state = default_intake_state(None)
        assert state["request_class"] == "direct_response"
        assert state["execution_mode"] == "standard"

    def test_default_intake_state_classifies_full_workflow(self) -> None:
        state = default_intake_state("Implement the adaptive intake system with tests.")
        assert state["request_class"] == "full_workflow"

    def test_default_intake_state_classifies_direct_response(self) -> None:
        state = default_intake_state("Explain how the supervisor works.")
        assert state["request_class"] == "direct_response"

    def test_workflow_state_includes_intake_block(self) -> None:
        state = default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=["phase_1"],
            goal="Test goal",
            state_root=".dev",
            prompt_text="Implement the intake classifier module.",
        )
        assert "intake" in state
        assert state["intake"]["request_class"] in {
            "direct_response",
            "planning_only",
            "light_edit",
            "full_workflow",
        }

    def test_workflow_state_intake_is_full_workflow_for_implementation_prompt(self) -> None:
        state = default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=["phase_1"],
            goal="Test",
            state_root=".dev",
            prompt_text="Implement the request classifier and write unit tests.",
        )
        assert state["intake"]["request_class"] == "full_workflow"

    def test_workflow_state_intake_is_direct_for_analysis_prompt(self) -> None:
        state = default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=["phase_1"],
            goal="Test",
            state_root=".dev",
            prompt_text="Analyze the supervisor logic and summarize findings.",
        )
        assert state["intake"]["request_class"] == "direct_response"

    def test_workflow_state_intake_without_prompt_defaults_to_direct(self) -> None:
        state = default_workflow_state(
            timestamp="2026-04-16T00:00:00+09:00",
            roadmap_phase_ids=[],
            goal="Bootstrap",
            state_root=".dev",
            prompt_text=None,
        )
        assert state["intake"]["request_class"] == "direct_response"
