"""Unit and integration tests for PipelineRunner."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from dormammu.agent.prompt_identity import prepend_cli_identity
from dormammu.artifacts import ArtifactRef
from dormammu.daemon.cli_output import select_agent_output
from dormammu.agent.profiles import resolve_agent_profile
from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig
from dormammu.daemon.models import StageResult
from dormammu.daemon.pipeline_runner import (
    MAX_STAGE_ITERATIONS,
    PipelineRunner,
    _model_args,
)
from dormammu.loop_runner import LoopRunResult
from dormammu.results import ResultStatus, ResultVerdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop_result(status: str = "completed") -> LoopRunResult:
    return LoopRunResult(
        status=status,
        attempts_completed=1,
        retries_used=0,
        max_retries=49,
        max_iterations=50,
        latest_run_id="run-1",
        supervisor_verdict="approved",
        report_path=None,
        continuation_prompt_path=None,
    )


def _make_app_config(tmp_path: Path, *, agents: AgentsConfig | None = None) -> Any:
    mock = MagicMock()
    mock.repo_root = tmp_path
    mock.base_dev_dir = tmp_path / ".dev"
    mock.active_agent_cli = Path("claude")
    mock.agents_dir = Path(__file__).resolve().parents[1] / "agents"
    mock.agents = agents
    mock.runtime_path_prompt.return_value = ""
    mock.resolve_agent_profile.side_effect = lambda role: resolve_agent_profile(
        role,
        agents_config=agents,
    )
    return mock


def _make_runner(
    tmp_path: Path,
    *,
    agents: AgentsConfig | None = None,
    active_agent_cli: Path | None = None,
) -> PipelineRunner:
    agents = agents or AgentsConfig()
    app = _make_app_config(tmp_path, agents=agents)
    app.active_agent_cli = active_agent_cli  # default None → no fallback CLI
    stream = io.StringIO()
    runner = PipelineRunner(app, agents, progress_stream=stream)
    runner._repository.read_workflow_state = MagicMock(  # type: ignore[method-assign]
        return_value={"intake": {"request_class": "full_workflow"}}
    )
    return runner


# ---------------------------------------------------------------------------
# _model_args
# ---------------------------------------------------------------------------


class TestModelArgs:
    def test_no_model_returns_empty(self) -> None:
        assert _model_args("claude", None) == []

    def test_claude_model_flag(self) -> None:
        assert _model_args("claude", "claude-opus-4-5") == [
            "--model",
            "claude-opus-4-5",
        ]

    def test_codex_model_flag(self) -> None:
        assert _model_args("codex", "gpt-4") == ["-m", "gpt-4"]

    def test_unknown_cli_returns_empty(self) -> None:
        assert _model_args("unknown-cli", "some-model") == []


class TestSelectAgentOutput:
    def test_prefers_non_empty_stdout(self) -> None:
        assert select_agent_output("final output\n", "warning\n") == "final output\n"

    def test_falls_back_to_stderr_when_stdout_is_blank(self) -> None:
        assert select_agent_output(" \n\t", "stderr output\n") == "stderr output\n"


# ---------------------------------------------------------------------------
# _append_feedback
# ---------------------------------------------------------------------------


class TestAppendFeedback:
    def test_appends_section(self) -> None:
        result = PipelineRunner._append_feedback(
            "original prompt",
            "tester said FAIL",
            source="tester",
        )
        assert "original prompt" in result
        assert "# Feedback from tester" in result
        assert "tester said FAIL" in result


# ---------------------------------------------------------------------------
# Refiner / planner stages
# ---------------------------------------------------------------------------


class TestMandatoryPreludeStages:
    def test_stage_iteration_limit_matches_developer_default_max_iterations(self) -> None:
        assert MAX_STAGE_ITERATIONS == _make_loop_result().max_iterations

    def test_refiner_uses_active_cli_fallback(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path, active_agent_cli=Path("claude"))

        with patch.object(runner, "_call_once", return_value="requirements") as mock_call:
            output = runner._run_refiner("goal", stem="g", date_str="20260412")

        assert output.output == "requirements"
        assert output.status == ResultStatus.COMPLETED
        assert output.verdict == "done"
        assert mock_call.call_args.kwargs["cli"] == Path("claude")

    def test_planner_uses_active_cli_fallback(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path, active_agent_cli=Path("claude"))

        with patch.object(runner, "_call_once", return_value="plan") as mock_call:
            output = runner._run_planner("goal", stem="g", date_str="20260412")

        assert output.output == "plan"
        assert output.status == ResultStatus.COMPLETED
        assert output.verdict == "done"
        assert mock_call.call_args.kwargs["cli"] == Path("claude")

    def test_plan_evaluator_proceed_verdict(self, tmp_path: Path) -> None:
        agents = AgentsConfig(evaluator=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)

        with patch.object(
            runner, "_call_once", return_value="checkpoint ok\nDECISION: PROCEED"
        ):
            stage = runner._run_plan_evaluator("goal", stem="g", date_str="20260412")

        assert stage.verdict == "proceed"

    def test_plan_evaluator_ambiguous_output_fails_closed_to_rework(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(evaluator=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)

        with patch.object(runner, "_call_once", return_value="checkpoint without verdict"):
            stage = runner._run_plan_evaluator("goal", stem="g", date_str="20260412")

        assert stage.verdict == "rework"

    def test_plan_evaluator_artifacts_and_lifecycle_use_plan_stage_name(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(evaluator=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        report_path = tmp_path / ".dev" / "logs" / "check_plan_g_20260412.md"
        report_ref = ArtifactRef.from_path(
            kind="checkpoint_report",
            path=report_path,
            label="plan_checkpoint_report",
            content_type="text/markdown",
            role="evaluator",
            stage_name="plan_evaluator",
        )
        runner._lifecycle = MagicMock()
        runner._lifecycle.run_id = "pipeline:test"
        runner._hook_controller.emit_stage_start = MagicMock()
        runner._hook_controller.emit_stage_complete = MagicMock()

        def _fake_call_once(**_: Any) -> str:
            runner._last_written_artifact_ref = report_ref
            return "checkpoint ok\nDECISION: PROCEED"

        with patch.object(runner, "_call_once", side_effect=_fake_call_once):
            stage = runner._run_plan_evaluator("goal", stem="g", date_str="20260412")

        assert stage.stage_name == "plan_evaluator"
        assert stage.artifacts == (report_ref,)
        assert stage.report_path == report_path
        persisted_events = [
            call_args.kwargs
            for call_args in runner._lifecycle.emit.call_args_list
            if call_args.kwargs["event_type"].value == "evaluator.checkpoint_decision"
        ]
        assert len(persisted_events) == 1
        assert persisted_events[0]["stage"] == "plan_evaluator"
        assert persisted_events[0]["artifact_refs"] == (report_ref,)
        runner._hook_controller.emit_stage_start.assert_called_once()
        assert (
            runner._hook_controller.emit_stage_start.call_args.kwargs["stage_name"]
            == "plan_evaluator"
        )

    def test_plan_evaluator_report_path_includes_stem_for_same_day_uniqueness(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(evaluator=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)

        first_prompt = runner._plan_evaluator_prompt(
            "goal one",
            None,
            stem="goal-one",
            date_str="20260412",
        )
        second_prompt = runner._plan_evaluator_prompt(
            "goal two",
            None,
            stem="goal-two",
            date_str="20260412",
        )

        assert "check_plan_goal-one_20260412.md" in first_prompt
        assert "check_plan_goal-two_20260412.md" in second_prompt
        assert first_prompt != second_prompt

    def test_run_refine_and_plan_retries_until_evaluator_proceeds(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            refiner=RoleAgentConfig(cli=Path("echo")),
            planner=RoleAgentConfig(cli=Path("echo")),
            evaluator=RoleAgentConfig(cli=Path("echo")),
        )
        runner = _make_runner(tmp_path, agents=agents)

        with (
            patch.object(runner, "_run_refiner", return_value="requirements") as mock_refiner,
            patch.object(runner, "_run_planner", return_value="plan") as mock_planner,
            patch.object(
                runner,
                "_run_plan_evaluator",
                side_effect=[
                    StageResult(role="evaluator", verdict="rework", output="DECISION: REWORK"),
                    StageResult(role="evaluator", verdict="proceed", output="DECISION: PROCEED"),
                ],
            ) as mock_eval,
        ):
            runner.run_refine_and_plan(
                "goal",
                stem="g",
                date_str="20260412",
                enable_plan_evaluator=True,
            )

        mock_refiner.assert_called_once()
        assert mock_planner.call_count == 2
        assert mock_eval.call_count == 2

    def test_run_refine_and_plan_skips_plan_evaluator_for_non_goals_prompts(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            refiner=RoleAgentConfig(cli=Path("echo")),
            planner=RoleAgentConfig(cli=Path("echo")),
            evaluator=RoleAgentConfig(cli=Path("echo")),
        )
        runner = _make_runner(tmp_path, agents=agents)

        with (
            patch.object(runner, "_run_refiner", return_value="requirements") as mock_refiner,
            patch.object(runner, "_run_planner", return_value="plan") as mock_planner,
            patch.object(runner, "_run_plan_evaluator") as mock_eval,
        ):
            runner.run_refine_and_plan(
                "goal",
                stem="g",
                date_str="20260412",
                enable_plan_evaluator=False,
            )

        mock_refiner.assert_called_once()
        mock_planner.assert_called_once()
        mock_eval.assert_not_called()

    def test_run_refine_and_plan_skips_refiner_for_light_edit(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            refiner=RoleAgentConfig(cli=Path("echo")),
            planner=RoleAgentConfig(cli=Path("echo")),
        )
        runner = _make_runner(tmp_path, agents=agents)

        with (
            patch.object(runner, "_run_refiner") as mock_refiner,
            patch.object(runner, "_run_planner", return_value="plan") as mock_planner,
        ):
            runner.run_refine_and_plan(
                "Fix the typo in README.md.",
                stem="g",
                date_str="20260412",
                request_class="light_edit",
            )

        mock_refiner.assert_not_called()
        mock_planner.assert_called_once()

    def test_run_refine_and_plan_skips_prelude_for_direct_response(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            refiner=RoleAgentConfig(cli=Path("echo")),
            planner=RoleAgentConfig(cli=Path("echo")),
        )
        runner = _make_runner(tmp_path, agents=agents)

        with (
            patch.object(runner, "_run_refiner") as mock_refiner,
            patch.object(runner, "_run_planner") as mock_planner,
        ):
            runner.run_refine_and_plan(
                "Explain the workflow.",
                stem="g",
                date_str="20260412",
                request_class="direct_response",
            )

        mock_refiner.assert_not_called()
        mock_planner.assert_not_called()

    def test_run_refine_and_plan_raises_after_max_rework(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            refiner=RoleAgentConfig(cli=Path("echo")),
            planner=RoleAgentConfig(cli=Path("echo")),
            evaluator=RoleAgentConfig(cli=Path("echo")),
        )
        runner = _make_runner(tmp_path, agents=agents)

        with (
            patch.object(runner, "_run_refiner", return_value="requirements"),
            patch.object(runner, "_run_planner", return_value="plan"),
            patch.object(
                runner,
                "_run_plan_evaluator",
                return_value=StageResult(role="evaluator", verdict="rework", output="DECISION: REWORK"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Mandatory plan evaluator"):
                runner.run_refine_and_plan(
                    "goal",
                    stem="g",
                    date_str="20260412",
                    enable_plan_evaluator=True,
                )

    def test_run_refine_and_plan_retries_up_to_stage_iteration_limit(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            refiner=RoleAgentConfig(cli=Path("echo")),
            planner=RoleAgentConfig(cli=Path("echo")),
            evaluator=RoleAgentConfig(cli=Path("echo")),
        )
        runner = _make_runner(tmp_path, agents=agents)

        with (
            patch.object(runner, "_run_refiner", return_value="requirements"),
            patch.object(runner, "_run_planner", return_value="plan") as mock_planner,
            patch.object(
                runner,
                "_run_plan_evaluator",
                return_value=StageResult(role="evaluator", verdict="rework", output="DECISION: REWORK"),
            ) as mock_eval,
        ):
            with pytest.raises(RuntimeError, match="Mandatory plan evaluator"):
                runner.run_refine_and_plan(
                    "goal",
                    stem="g",
                    date_str="20260412",
                    enable_plan_evaluator=True,
                )

        assert mock_planner.call_count == MAX_STAGE_ITERATIONS
        assert mock_eval.call_count == MAX_STAGE_ITERATIONS


# ---------------------------------------------------------------------------
# Developer stage
# ---------------------------------------------------------------------------


class TestDeveloperStage:
    def test_run_developer_uses_profile_cli_and_model_overrides(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("codex"), model="gpt-5.4"),
        )
        runner = _make_runner(tmp_path, agents=agents, active_agent_cli=Path("claude"))

        with patch("dormammu.daemon.pipeline_runner.LoopRunner") as mock_loop_runner:
            mock_loop_runner.return_value.run.return_value = _make_loop_result("completed")

            result = runner._run_developer("Implement the active slice.", stem="phase1")

        request = mock_loop_runner.return_value.run.call_args.args[0]
        assert result.status == "completed"
        assert request.cli_path == Path("codex")
        assert request.agent_role == "developer"
        assert request.extra_args == ("-m", "gpt-5.4")
        assert request.workdir == tmp_path
        assert request.run_label == "pipeline-developer-phase1"

    def test_run_developer_uses_active_session_roadmap_phase(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("codex")),
        )
        runner = _make_runner(tmp_path, agents=agents)
        runner._repository.read_workflow_state = MagicMock(  # type: ignore[method-assign]
            return_value={"roadmap": {"active_phase_ids": ["phase_6"]}}
        )

        with patch("dormammu.daemon.pipeline_runner.LoopRunner") as mock_loop_runner:
            mock_loop_runner.return_value.run.return_value = _make_loop_result("completed")

            runner._run_developer("Implement the active slice.", stem="phase6")

        request = mock_loop_runner.return_value.run.call_args.args[0]
        assert request.expected_roadmap_phase_id == "phase_6"


# ---------------------------------------------------------------------------
# Tester stage
# ---------------------------------------------------------------------------


class TestTesterStage:
    def test_no_cli_returns_none(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        result = runner._run_tester("goal", stem="g", date_str="20260412")
        assert result is None

    def test_pass_verdict_on_overall_pass(self, tmp_path: Path) -> None:
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="All tests passed.\nOVERALL: PASS"):
            stage = runner._run_tester("goal", stem="g", date_str="20260412")
        assert stage is not None and stage.verdict == "pass"

    def test_fail_verdict_on_overall_fail(self, tmp_path: Path) -> None:
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="Test X failed.\nOVERALL: FAIL"):
            stage = runner._run_tester("goal", stem="g", date_str="20260412")
        assert stage is not None and stage.verdict == "fail"

    def test_missing_verdict_fails_stage(self, tmp_path: Path) -> None:
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="No verdict line."):
            stage = runner._run_tester("goal", stem="g", date_str="20260412")
        assert stage is not None
        assert stage.status == ResultStatus.FAILED
        assert stage.verdict is None

    def test_case_insensitive_fail(self, tmp_path: Path) -> None:
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="overall: fail"):
            stage = runner._run_tester("goal", stem="g", date_str="20260412")
        assert stage is not None and stage.verdict == "fail"

    def test_manual_review_verdict_marks_stage_manual_review_needed(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(
            runner,
            "_call_once",
            return_value=(
                "Executable browser validation was unavailable.\n"
                "OVERALL: MANUAL_REVIEW_NEEDED"
            ),
        ):
            stage = runner._run_tester("goal", stem="g", date_str="20260412")
        assert stage is not None
        assert stage.status == ResultStatus.MANUAL_REVIEW_NEEDED
        assert stage.verdict == ResultVerdict.MANUAL_REVIEW_NEEDED
        assert "requested manual review" in (stage.summary or "")

    def test_tester_prompt_prefers_npx_agent_browser_and_manual_review(
        self, tmp_path: Path
    ) -> None:
        runner = _make_runner(tmp_path)

        prompt = runner._tester_prompt("goal", stem="g", date_str="20260412")

        assert "npx -y agent-browser" in prompt
        assert "OVERALL: MANUAL_REVIEW_NEEDED" in prompt


# ---------------------------------------------------------------------------
# Reviewer stage
# ---------------------------------------------------------------------------


class TestReviewerStage:
    def test_no_cli_returns_none(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path)
        result = runner._run_reviewer("goal", stem="g", date_str="20260412")
        assert result is None

    def test_approved_verdict(self, tmp_path: Path) -> None:
        agents = AgentsConfig(reviewer=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="Looks good.\nVERDICT: APPROVED"):
            stage = runner._run_reviewer("goal", stem="g", date_str="20260412")
        assert stage is not None and stage.verdict == "approved"

    def test_needs_work_verdict(self, tmp_path: Path) -> None:
        agents = AgentsConfig(reviewer=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(
            runner, "_call_once", return_value="Issues found.\nVERDICT: NEEDS_WORK"
        ):
            stage = runner._run_reviewer("goal", stem="g", date_str="20260412")
        assert stage is not None and stage.verdict == "needs_work"

    def test_missing_verdict_fails_stage(self, tmp_path: Path) -> None:
        agents = AgentsConfig(reviewer=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="No verdict."):
            stage = runner._run_reviewer("goal", stem="g", date_str="20260412")
        assert stage is not None
        assert stage.status == ResultStatus.FAILED
        assert stage.verdict is None

    def test_designer_doc_included_in_prompt(self, tmp_path: Path) -> None:
        agents = AgentsConfig(reviewer=RoleAgentConfig(cli=Path("echo")))
        app = _make_app_config(tmp_path, agents=agents)
        stream = io.StringIO()
        runner = PipelineRunner(app, agents, progress_stream=stream)

        # Create a fake designer doc (renamed from architect)
        logs_dir = tmp_path / ".dev" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "20260412_designer_my-feat.md").write_text(
            "# Designer Document", encoding="utf-8"
        )

        captured: list[str] = []

        def fake_call_once(*, role, cli, model, prompt, stem, date_str, doc_path=None, save_doc=True):
            captured.append(prompt)
            return "VERDICT: APPROVED"

        with patch.object(runner, "_call_once", side_effect=fake_call_once):
            runner._run_reviewer("goal", stem="my-feat", date_str="20260412")

        assert "Designer Document" in captured[0]


# ---------------------------------------------------------------------------
# StageResult model (Phase 4)
# ---------------------------------------------------------------------------


class TestStageResult:
    def test_fields_accessible(self) -> None:
        stage = StageResult(role="tester", verdict="pass", output="OVERALL: PASS")
        assert stage.role == "tester"
        assert stage.status == ResultStatus.COMPLETED
        assert stage.verdict == "pass"
        assert stage.output == "OVERALL: PASS"
        assert stage.report_path is None

    def test_report_path_stored(self, tmp_path: Path) -> None:
        path = tmp_path / "report.md"
        stage = StageResult(role="evaluator", verdict="proceed", output="ok", report_path=path)
        assert stage.report_path == path

    def test_to_dict_excludes_output(self) -> None:
        stage = StageResult(role="reviewer", verdict="approved", output="long output text")
        d = stage.to_dict()
        assert d["role"] == "reviewer"
        assert d["status"] == "completed"
        assert d["verdict"] == "approved"
        assert "output" not in d

    def test_immutable(self) -> None:
        stage = StageResult(role="tester", verdict="fail", output="")
        with pytest.raises((AttributeError, TypeError)):
            stage.verdict = "pass"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Role taxonomy (Phase 4)
# ---------------------------------------------------------------------------


class TestRoleTaxonomy:
    def test_designer_role_is_valid(self) -> None:
        from dormammu.agent.role_config import AgentsConfig, ROLE_NAMES
        assert "designer" in ROLE_NAMES
        cfg = AgentsConfig()
        assert cfg.for_role("designer").cli is None

    def test_architect_role_no_longer_valid(self) -> None:
        from dormammu.agent.role_config import AgentsConfig
        with pytest.raises(ValueError, match="Unknown role"):
            AgentsConfig().for_role("architect")

    def test_analyzer_role_still_valid(self) -> None:
        from dormammu.agent.role_config import AgentsConfig
        cfg = AgentsConfig()
        assert cfg.for_role("analyzer").cli is None

    def test_all_expected_roles_present(self) -> None:
        from dormammu.agent.role_config import ROLE_NAMES
        expected = {"refiner", "analyzer", "planner", "designer", "developer",
                    "tester", "reviewer", "committer", "evaluator"}
        assert set(ROLE_NAMES) == expected


# ---------------------------------------------------------------------------
# Full pipeline — run()
# ---------------------------------------------------------------------------


class TestPipelineRun:
    def test_no_cli_anywhere_raises(self, tmp_path: Path) -> None:
        """When no CLI is configured anywhere, refiner fails first."""
        runner = _make_runner(tmp_path)  # active_agent_cli=None by default
        with pytest.raises(RuntimeError, match="No CLI available for refiner"):
            runner.run("goal", stem="s", date_str="20260412")

    def test_successful_pipeline_all_pass(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
            committer=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        dev_result = _make_loop_result("completed")

        with (
            patch.object(runner, "run_refine_and_plan") as mock_prelude,
            patch.object(runner, "_run_developer", return_value=dev_result) as mock_dev,
            patch.object(
                runner, "_run_tester",
                return_value=StageResult(role="tester", verdict="pass", output="OVERALL: PASS"),
            ) as mock_tester,
            patch.object(
                runner, "_run_reviewer",
                return_value=StageResult(role="reviewer", verdict="approved", output="VERDICT: APPROVED"),
            ) as mock_reviewer,
            patch.object(
                runner,
                "_run_committer",
                return_value=StageResult(role="committer", verdict="committed", output="commit ok"),
            ) as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "completed"
        assert {stage.role for stage in result.stage_results} >= {"developer", "tester", "reviewer", "committer"}
        mock_prelude.assert_called_once()
        assert mock_dev.call_count == 1
        assert mock_tester.call_count == 1
        assert mock_reviewer.call_count == 1
        assert mock_committer.call_count == 1

    def test_non_goal_pipeline_run_disables_plan_evaluator(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
            committer=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with (
            patch.object(runner, "run_refine_and_plan") as mock_prelude,
            patch.object(runner, "_run_developer", return_value=_make_loop_result("completed")),
            patch.object(runner, "_run_tester", return_value=StageResult(role="tester", verdict="pass", output="")),
            patch.object(runner, "_run_reviewer", return_value=StageResult(role="reviewer", verdict="approved", output="")),
            patch.object(runner, "_run_committer", return_value=None),
        ):
            runner.run("goal", stem="s", date_str="20260412")

        assert mock_prelude.call_args.kwargs["enable_plan_evaluator"] is False

    def test_direct_response_uses_fast_path_without_pipeline_stages(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
            committer=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())
        runner._repository.read_workflow_state = MagicMock(  # type: ignore[method-assign]
            return_value={"intake": {"request_class": "direct_response"}}
        )

        direct_result = LoopRunResult(
            status="completed",
            attempts_completed=1,
            retries_used=0,
            max_retries=0,
            max_iterations=1,
            latest_run_id="run-direct",
            supervisor_verdict="done",
            report_path=None,
            continuation_prompt_path=None,
        )

        with (
            patch.object(runner, "run_refine_and_plan") as mock_prelude,
            patch.object(runner, "_run_direct_response", return_value=direct_result) as mock_direct,
            patch.object(runner, "_run_developer") as mock_dev,
            patch.object(runner, "_run_tester") as mock_tester,
            patch.object(runner, "_run_reviewer") as mock_reviewer,
            patch.object(runner, "_run_committer") as mock_committer,
        ):
            result = runner.run("Explain the workflow.", stem="s", date_str="20260412")

        assert result.status == "completed"
        mock_direct.assert_called_once()
        mock_prelude.assert_not_called()
        mock_dev.assert_not_called()
        mock_tester.assert_not_called()
        mock_reviewer.assert_not_called()
        mock_committer.assert_not_called()

    def test_planning_only_stops_after_refine_and_plan(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            refiner=RoleAgentConfig(cli=Path("claude")),
            planner=RoleAgentConfig(cli=Path("claude")),
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
            committer=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())
        runner._repository.read_workflow_state = MagicMock(  # type: ignore[method-assign]
            return_value={"intake": {"request_class": "planning_only"}}
        )

        with (
            patch.object(runner, "run_refine_and_plan") as mock_prelude,
            patch.object(runner, "_run_developer") as mock_dev,
            patch.object(runner, "_run_tester") as mock_tester,
            patch.object(runner, "_run_reviewer") as mock_reviewer,
            patch.object(runner, "_run_committer") as mock_committer,
        ):
            result = runner.run(
                "Think deeply about the dormammu runtime structure.",
                stem="s",
                date_str="20260412",
            )

        assert result.status == "completed"
        assert result.metadata["request_class"] == "planning_only"
        assert result.metadata["execution_mode"] == "deep_thinking"
        mock_prelude.assert_called_once()
        mock_dev.assert_not_called()
        mock_tester.assert_not_called()
        mock_reviewer.assert_not_called()
        mock_committer.assert_not_called()

    def test_goal_pipeline_run_enables_plan_evaluator(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
            committer=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        goal_file = tmp_path / "goal.md"
        goal_file.write_text("goal\n", encoding="utf-8")

        with (
            patch.object(runner, "run_refine_and_plan") as mock_prelude,
            patch.object(runner, "_run_developer", return_value=_make_loop_result("completed")),
            patch.object(runner, "_run_tester", return_value=StageResult(role="tester", verdict="pass", output="")),
            patch.object(runner, "_run_reviewer", return_value=StageResult(role="reviewer", verdict="approved", output="")),
            patch.object(runner, "_run_committer", return_value=None),
            patch.object(runner, "_run_evaluator", return_value=None),
        ):
            runner.run(
                "goal",
                stem="s",
                date_str="20260412",
                goal_file_path=goal_file,
            )

        assert mock_prelude.call_args.kwargs["enable_plan_evaluator"] is True

    def test_tester_fail_triggers_developer_reentry(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())
        recorder = MagicMock()
        recorder.run_id = "pipeline:test"

        tester_responses = [
            StageResult(role="tester", verdict="fail", output="OVERALL: FAIL"),
            StageResult(role="tester", verdict="pass", output="OVERALL: PASS"),
        ]

        with (
            patch(
                "dormammu.daemon.pipeline_runner.LifecycleRecorder.for_execution",
                return_value=recorder,
            ),
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(
                runner, "_run_tester", side_effect=tester_responses
            ) as mock_tester,
            patch.object(runner, "_run_reviewer", return_value=None),
            patch.object(runner, "_run_committer", return_value=None),
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "completed"
        assert mock_dev.call_count == 2  # developer ran twice
        assert mock_tester.call_count == 2
        retried_event = next(
            call.kwargs
            for call in recorder.emit.call_args_list
            if call.kwargs["event_type"].value == "stage.retried"
        )
        assert retried_event["role"] == "developer"
        assert retried_event["stage"] == "developer"
        assert retried_event["status"] == "retried"
        assert retried_event["payload"].source_stage == "tester"
        assert retried_event["payload"].target_stage == "developer"
        assert retried_event["payload"].attempt == 1
        assert retried_event["payload"].next_attempt == 2

        handoff_event = next(
            call.kwargs
            for call in recorder.emit.call_args_list
            if call.kwargs["event_type"].value == "supervisor.handoff"
            and call.kwargs["payload"].from_role == "tester"
        )
        assert handoff_event["role"] == "tester"
        assert handoff_event["stage"] == "developer"
        assert handoff_event["status"] == "handoff"
        assert handoff_event["payload"].to_role == "developer"
        assert handoff_event["payload"].attempt == 2

        finished_event = recorder.emit.call_args_list[-1].kwargs
        assert finished_event["event_type"].value == "run.finished"
        assert finished_event["payload"].supervisor_verdict == "pass"

    def test_reviewer_needs_work_triggers_developer_reentry(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        reviewer_responses = [
            StageResult(role="reviewer", verdict="needs_work", output="VERDICT: NEEDS_WORK"),
            StageResult(role="reviewer", verdict="approved", output="VERDICT: APPROVED"),
        ]

        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(runner, "_run_tester", return_value=None),
            patch.object(
                runner, "_run_reviewer", side_effect=reviewer_responses
            ) as mock_reviewer,
            patch.object(runner, "_run_committer", return_value=None),
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "completed"
        assert mock_dev.call_count == 2
        assert mock_reviewer.call_count == 2

    def test_developer_failure_short_circuits_pipeline(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(developer=RoleAgentConfig(cli=Path("claude")))
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("failed")
            ),
            patch.object(runner, "_run_tester", return_value=None) as mock_tester,
            patch.object(runner, "_run_reviewer", return_value=None) as mock_reviewer,
            patch.object(runner, "_run_committer", return_value=None) as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "failed"
        # Tester/reviewer/committer must NOT be called on developer failure
        mock_tester.assert_not_called()
        mock_reviewer.assert_not_called()
        mock_committer.assert_not_called()

    def test_tester_fails_max_iterations_stops_for_manual_review(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        # Tester always fails
        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(
                runner, "_run_tester",
                return_value=StageResult(role="tester", verdict="fail", output="OVERALL: FAIL"),
            ) as mock_tester,
            patch.object(runner, "_run_reviewer", return_value=None) as mock_reviewer,
            patch.object(runner, "_run_committer", return_value=None),
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "manual_review_needed"
        assert result.supervisor_verdict == "manual_review_needed"
        assert "Tester requested another developer pass" in result.summary
        assert mock_dev.call_count == MAX_STAGE_ITERATIONS
        assert mock_tester.call_count == MAX_STAGE_ITERATIONS
        mock_reviewer.assert_not_called()

    def test_reviewer_fails_max_iterations_stops_for_manual_review(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        # Reviewer always fails
        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(runner, "_run_tester", return_value=None),
            patch.object(
                runner, "_run_reviewer",
                return_value=StageResult(role="reviewer", verdict="needs_work", output="VERDICT: NEEDS_WORK"),
            ) as mock_reviewer,
            patch.object(runner, "_run_committer", return_value=None) as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "manual_review_needed"
        assert result.supervisor_verdict == "manual_review_needed"
        assert "Reviewer still reported NEEDS_WORK" in result.summary
        # developer re-ran MAX_STAGE_ITERATIONS times total
        assert mock_dev.call_count == MAX_STAGE_ITERATIONS
        assert mock_reviewer.call_count == MAX_STAGE_ITERATIONS
        mock_committer.assert_not_called()

    def test_feedback_appended_to_prompt_on_tester_fail(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        captured_prompts: list[str] = []

        def fake_dev(prompt: str, *, stem: str) -> LoopRunResult:
            captured_prompts.append(prompt)
            return _make_loop_result("completed")

        tester_responses = [
            StageResult(role="tester", verdict="fail", output="failure details here"),
            StageResult(role="tester", verdict="pass", output="OVERALL: PASS"),
        ]

        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(runner, "_run_developer", side_effect=fake_dev),
            patch.object(runner, "_run_tester", side_effect=tester_responses),
            patch.object(runner, "_run_reviewer", return_value=None),
            patch.object(runner, "_run_committer", return_value=None),
        ):
            runner.run("original goal", stem="s", date_str="20260412")

        # Second developer call should have tester feedback appended
        assert len(captured_prompts) == 2
        assert "failure details here" in captured_prompts[1]
        assert "# Feedback from tester" in captured_prompts[1]

    def test_invalid_tester_output_aborts_pipeline(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(
                runner,
                "_run_tester",
                return_value=StageResult(
                    role="tester",
                    stage_name="tester",
                    status=ResultStatus.FAILED,
                    verdict=None,
                    summary="Tester output did not include a valid 'OVERALL:' verdict.",
                ),
            ),
            patch.object(runner, "_run_reviewer", return_value=None) as mock_reviewer,
            patch.object(runner, "_run_committer", return_value=None) as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == ResultStatus.FAILED
        assert mock_dev.call_count == 1
        mock_reviewer.assert_not_called()
        mock_committer.assert_not_called()

    def test_tester_manual_review_stops_pipeline_without_reentering_developer(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(
                runner,
                "_run_tester",
                return_value=StageResult(
                    role="tester",
                    stage_name="tester",
                    status=ResultStatus.MANUAL_REVIEW_NEEDED,
                    verdict=ResultVerdict.MANUAL_REVIEW_NEEDED,
                    summary="Executable browser validation was unavailable.",
                ),
            ) as mock_tester,
            patch.object(runner, "_run_reviewer", return_value=None) as mock_reviewer,
            patch.object(runner, "_run_committer", return_value=None) as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == ResultStatus.MANUAL_REVIEW_NEEDED
        assert result.supervisor_verdict == ResultVerdict.MANUAL_REVIEW_NEEDED
        assert result.summary == "Executable browser validation was unavailable."
        assert mock_dev.call_count == 1
        assert mock_tester.call_count == 1
        mock_reviewer.assert_not_called()
        mock_committer.assert_not_called()

    def test_invalid_reviewer_output_aborts_pipeline(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(runner, "_run_tester", return_value=None),
            patch.object(
                runner,
                "_run_reviewer",
                return_value=StageResult(
                    role="reviewer",
                    stage_name="reviewer",
                    status=ResultStatus.FAILED,
                    verdict=None,
                    summary="Reviewer output did not include a valid 'VERDICT:' line.",
                ),
            ),
            patch.object(runner, "_run_committer", return_value=None) as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == ResultStatus.FAILED
        assert mock_dev.call_count == 1
        mock_committer.assert_not_called()

    def test_invalid_final_evaluator_output_aborts_pipeline_and_records_stage(
        self,
        tmp_path: Path,
    ) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            reviewer=RoleAgentConfig(cli=Path("claude")),
            committer=RoleAgentConfig(cli=Path("claude")),
            evaluator=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())
        goal_file = tmp_path / "goal.md"
        goal_file.write_text("goal\n", encoding="utf-8")
        evaluator_report = tmp_path / ".dev" / "logs" / "20260412_evaluator_s.md"
        evaluator_stage = StageResult(
            role="evaluator",
            stage_name="final_evaluator",
            status=ResultStatus.FAILED,
            verdict="unknown",
            summary="Evaluator output did not include a valid 'VERDICT:' line.",
            report_path=evaluator_report,
        )

        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(runner, "_run_tester", return_value=None),
            patch.object(
                runner,
                "_run_reviewer",
                return_value=StageResult(
                    role="reviewer",
                    verdict="approved",
                    output="VERDICT: APPROVED",
                ),
            ),
            patch.object(
                runner,
                "_run_committer",
                return_value=StageResult(
                    role="committer",
                    verdict="committed",
                    output="commit ok",
                ),
            ) as mock_committer,
            patch(
                "dormammu.daemon.pipeline_runner.EvaluatorStage.run",
                return_value=evaluator_stage,
            ),
        ):
            result = runner.run(
                "goal",
                stem="s",
                date_str="20260412",
                goal_file_path=goal_file,
            )

        assert result.status == ResultStatus.FAILED
        assert result.supervisor_verdict == "unknown"
        assert result.summary == evaluator_stage.summary
        assert result.stage_results[-1] == evaluator_stage
        assert result.stage_results[-1].artifacts[0].path == evaluator_report
        assert mock_dev.call_count == 1
        mock_committer.assert_called_once()

    def test_run_evaluator_records_failed_stage_and_emits_report_artifact(
        self,
        tmp_path: Path,
    ) -> None:
        agents = AgentsConfig(evaluator=RoleAgentConfig(cli=Path("claude")))
        runner = _make_runner(tmp_path, agents=agents, active_agent_cli=Path("claude"))
        goal_file = tmp_path / "goal.md"
        goal_file.write_text("goal\n", encoding="utf-8")
        evaluator_report = tmp_path / ".dev" / "logs" / "20260412_evaluator_s.md"
        failed_stage = StageResult(
            role="evaluator",
            stage_name="final_evaluator",
            status=ResultStatus.FAILED,
            verdict="unknown",
            summary="Evaluator output did not include a valid 'VERDICT:' line.",
            report_path=evaluator_report,
        )

        runner._current_stage_results = []
        runner._lifecycle = MagicMock()
        runner._lifecycle.run_id = "pipeline:test"
        runner._hook_controller.emit_stage_complete = MagicMock()

        with patch(
            "dormammu.daemon.pipeline_runner.EvaluatorStage.run",
            return_value=failed_stage,
        ):
            result = runner._run_evaluator(
                prompt_text="goal",
                stem="s",
                date_str="20260412",
                goal_file_path=goal_file,
                evaluator_config=None,
            )

        assert result == failed_stage
        assert runner._current_stage_results == [failed_stage]
        emitted_types = [
            call_args.kwargs["event_type"].value
            for call_args in runner._lifecycle.emit.call_args_list
        ]
        assert emitted_types[:2] == [
            "stage.queued",
            "stage.started",
        ]
        assert emitted_types[-2:] == [
            "artifact.persisted",
            "stage.failed",
        ]
        runner._hook_controller.emit_stage_complete.assert_called_once()

    def test_run_evaluator_passes_pipeline_execution_identity_into_request(
        self,
        tmp_path: Path,
    ) -> None:
        agents = AgentsConfig(evaluator=RoleAgentConfig(cli=Path("claude")))
        runner = _make_runner(tmp_path, agents=agents, active_agent_cli=Path("claude"))
        goal_file = tmp_path / "goal.md"
        goal_file.write_text("goal\n", encoding="utf-8")
        runner._repository = MagicMock()
        runner._repository.read_session_state.return_value = {"session_id": "session-42"}
        runner._current_stage_results = []
        runner._lifecycle = MagicMock()
        runner._lifecycle.run_id = "pipeline:test"
        runner._hook_controller.emit_stage_complete = MagicMock()

        evaluator_stage = StageResult(
            role="evaluator",
            stage_name="final_evaluator",
            status=ResultStatus.COMPLETED,
            verdict="partial",
            summary="Evaluator completed.",
        )

        with patch(
            "dormammu.daemon.pipeline_runner.EvaluatorStage.run",
            return_value=evaluator_stage,
        ) as mock_run:
            runner._run_evaluator(
                prompt_text="goal",
                stem="s",
                date_str="20260412",
                goal_file_path=goal_file,
                evaluator_config=None,
            )

        request = mock_run.call_args.args[0]
        assert request.run_id == "pipeline:test"
        assert request.session_id == "session-42"

    @pytest.mark.parametrize(
        ("verdict", "expected_event_type", "expected_status"),
        [
            ("done", "stage.completed", "completed"),
            ("pass", "stage.completed", "completed"),
            ("approved", "stage.completed", "completed"),
            ("committed", "stage.completed", "completed"),
            ("fail", "stage.failed", "completed"),
            ("needs_work", "stage.failed", "completed"),
            ("rework", "stage.failed", "completed"),
            ("blocked", "stage.failed", "completed"),
            ("failed", "stage.failed", "failed"),
        ],
    )
    def test_stage_verdicts_map_to_expected_lifecycle_event_types(
        self,
        tmp_path: Path,
        verdict: str,
        expected_event_type: str,
        expected_status: str,
    ) -> None:
        runner = _make_runner(tmp_path, active_agent_cli=Path("claude"))
        runner._lifecycle = MagicMock()
        runner._hook_controller.emit_stage_complete = MagicMock()

        runner._emit_stage_complete(role="tester", verdict=verdict)

        emit_kwargs = runner._lifecycle.emit.call_args.kwargs
        assert emit_kwargs["event_type"].value == expected_event_type
        assert emit_kwargs["status"] == expected_status

    def test_emit_stage_complete_attaches_stage_result_metadata_and_artifacts(
        self,
        tmp_path: Path,
    ) -> None:
        runner = _make_runner(tmp_path, active_agent_cli=Path("claude"))
        runner._lifecycle = MagicMock()
        runner._hook_controller.emit_stage_complete = MagicMock()
        artifact = ArtifactRef.from_path(
            kind="stage_report",
            path=tmp_path / ".dev" / "logs" / "20260412_tester_s.md",
            label="tester_report",
            content_type="text/markdown",
            role="tester",
            stage_name="tester",
        )
        stage = StageResult(
            role="tester",
            stage_name="tester",
            verdict="pass",
            artifacts=(artifact,),
            summary="Tests passed.",
        )

        runner._emit_stage_complete(stage=stage, run_id="pipeline:test")

        emit_kwargs = runner._lifecycle.emit.call_args.kwargs
        assert emit_kwargs["artifact_refs"] == (artifact,)
        assert emit_kwargs["metadata"]["run_id"] == "pipeline:test"
        assert emit_kwargs["metadata"]["stage_result"]["stage_name"] == "tester"
        assert emit_kwargs["metadata"]["stage_result"]["artifacts"][0]["kind"] == "stage_report"

    def test_finalize_pipeline_result_aggregates_stage_artifacts_and_records_run_result(
        self,
        tmp_path: Path,
    ) -> None:
        runner = _make_runner(tmp_path, active_agent_cli=Path("claude"))
        runner._repository = MagicMock()
        runner._hook_controller.emit_session_end = MagicMock()
        runner._lifecycle = MagicMock()
        runner._lifecycle.run_id = "pipeline:test"
        stage_artifact = ArtifactRef.from_path(
            kind="stage_report",
            path=tmp_path / ".dev" / "logs" / "20260412_tester_s.md",
            label="tester_report",
            content_type="text/markdown",
            role="tester",
            stage_name="tester",
        )
        runner._current_stage_results = [
            StageResult(
                role="tester",
                stage_name="tester",
                verdict="pass",
                artifacts=(stage_artifact,),
                summary="Tests passed.",
            )
        ]

        with patch.object(runner, "_emit_run_finished_event") as mock_finished:
            result = runner._finalize_pipeline_result(_make_loop_result("completed"))

        assert result.artifacts == (stage_artifact,)
        runner._repository.record_run_result.assert_called_once()
        assert runner._repository.record_run_result.call_args.kwargs["run_id"] == "pipeline:test"
        mock_finished.assert_called_once()

    def test_finalize_pipeline_result_excludes_artifacts_from_superseded_stage_attempts(
        self,
        tmp_path: Path,
    ) -> None:
        runner = _make_runner(tmp_path, active_agent_cli=Path("claude"))
        runner._repository = MagicMock()
        runner._hook_controller.emit_session_end = MagicMock()
        runner._lifecycle = MagicMock()
        runner._lifecycle.run_id = "pipeline:test"
        stale_artifact = ArtifactRef.from_path(
            kind="stage_report",
            path=tmp_path / ".dev" / "logs" / "20260412_tester_fail.md",
            label="tester_report",
            content_type="text/markdown",
            role="tester",
            stage_name="tester",
        )
        latest_artifact = ArtifactRef.from_path(
            kind="stage_report",
            path=tmp_path / ".dev" / "logs" / "20260412_tester_pass.md",
            label="tester_report",
            content_type="text/markdown",
            role="tester",
            stage_name="tester",
        )
        runner._current_stage_results = [
            StageResult(
                role="tester",
                stage_name="tester",
                verdict="fail",
                artifacts=(stale_artifact,),
                summary="Initial failure.",
            ),
            StageResult(
                role="tester",
                stage_name="tester",
                verdict="pass",
                artifacts=(latest_artifact,),
                summary="Retry succeeded.",
            ),
        ]

        with patch.object(runner, "_emit_run_finished_event"):
            result = runner._finalize_pipeline_result(_make_loop_result("completed"))

        assert result.artifacts == (latest_artifact,)

    def test_pipeline_emits_terminal_failure_event_when_setup_raises_early(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(developer=RoleAgentConfig(cli=Path("claude")))
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())
        recorder = MagicMock()
        recorder.run_id = "pipeline:test"

        with (
            patch("dormammu.daemon.pipeline_runner.LifecycleRecorder.for_execution", return_value=recorder),
            patch.object(runner, "run_refine_and_plan", side_effect=RuntimeError("planner exploded")),
            pytest.raises(RuntimeError, match="planner exploded"),
        ):
            runner.run("goal", stem="s", date_str="20260412")

        emitted_types = [call.kwargs["event_type"].value for call in recorder.emit.call_args_list]
        assert emitted_types == [
            "run.requested",
            "run.started",
            "run.finished",
        ]
        finished_call = recorder.emit.call_args_list[-1]
        finished_payload = finished_call.kwargs["payload"]
        assert finished_call.kwargs["status"] == "failed"
        assert finished_payload.outcome == "failed"
        assert finished_payload.error == "planner exploded"


# ---------------------------------------------------------------------------
# Document writing
# ---------------------------------------------------------------------------


def _make_adapter_result(tmp_path: Path, stdout: str = "", stderr: str = "") -> Any:
    """Create a mock AgentRunResult with real temp files for stdout/stderr."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    stdout_file = tmp_path / "stdout.txt"
    stderr_file = tmp_path / "stderr.txt"
    stdout_file.write_text(stdout, encoding="utf-8")
    stderr_file.write_text(stderr, encoding="utf-8")
    result = MagicMock()
    result.stdout_path = stdout_file
    result.stderr_path = stderr_file
    return result


class TestDocumentWriting:
    def test_call_once_writes_role_doc(self, tmp_path: Path) -> None:
        agents = AgentsConfig()
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with patch("dormammu.agent.cli_adapter.CliAdapter.run_once") as mock_run:
            mock_run.return_value = _make_adapter_result(tmp_path / "r1", stdout="agent output")
            runner._call_once(
                role="tester",
                cli=Path("claude"),
                model=None,
                prompt="test prompt",
                stem="my-feature",
                date_str="20260412",
            )

        doc = tmp_path / ".dev" / "logs" / "20260412_tester_my-feature.md"
        assert doc.exists()
        content = doc.read_text(encoding="utf-8")
        assert "Tester" in content
        assert "agent output" in content

    def test_call_once_passes_prompt_to_adapter_request(self, tmp_path: Path) -> None:
        """_call_once forwards the raw prompt to AgentRunRequest; CliAdapter applies identity."""
        agents = AgentsConfig()
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with patch("dormammu.agent.cli_adapter.CliAdapter.run_once") as mock_run:
            mock_run.return_value = _make_adapter_result(tmp_path / "r2", stdout="agent output")
            runner._call_once(
                role="tester",
                cli=Path("claude"),
                model=None,
                prompt="test prompt",
                stem="my-feature",
                date_str="20260412",
            )

        request = mock_run.call_args[0][0]
        assert request.prompt_text == "test prompt"
        assert request.cli_path == Path("claude")

    def test_call_once_uses_stderr_when_stdout_is_blank(self, tmp_path: Path) -> None:
        agents = AgentsConfig()
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with patch("dormammu.agent.cli_adapter.CliAdapter.run_once") as mock_run:
            mock_run.return_value = _make_adapter_result(
                tmp_path / "r3",
                stdout=" \n",
                stderr="stage report from stderr\n",
            )
            output = runner._call_once(
                role="refiner",
                cli=Path("claude"),
                model=None,
                prompt="test prompt",
                stem="stderr-case",
                date_str="20260412",
            )

        assert output == "stage report from stderr\n"
        doc = tmp_path / ".dev" / "logs" / "20260412_refiner_stderr-case.md"
        assert "stage report from stderr" in doc.read_text(encoding="utf-8")

    def test_call_once_binds_artifact_refs_to_overridden_stage_name(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig()
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())
        runner._lifecycle = MagicMock()
        runner._lifecycle.run_id = "pipeline:test"

        with patch("dormammu.agent.cli_adapter.CliAdapter.run_once") as mock_run:
            mock_run.return_value = _make_adapter_result(tmp_path / "r-stage", stdout="checkpoint")
            runner._call_once(
                role="evaluator",
                stage_name="plan_evaluator",
                cli=Path("claude"),
                model=None,
                prompt="test prompt",
                stem="plan-checkpoint",
                date_str="20260412",
                artifact_kind="checkpoint_report",
                artifact_label="plan_checkpoint_report",
            )

        assert runner._last_written_artifact_ref is not None
        assert runner._last_written_artifact_ref.stage_name == "plan_evaluator"
        emit_kwargs = runner._lifecycle.emit.call_args.kwargs
        assert emit_kwargs["event_type"].value == "artifact.persisted"
        assert emit_kwargs["stage"] == "plan_evaluator"
        assert emit_kwargs["artifact_refs"][0].stage_name == "plan_evaluator"

    def test_call_once_emits_command_and_captured_output_to_progress_stream(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig()
        app = _make_app_config(tmp_path, agents=agents)
        progress = io.StringIO()
        runner = PipelineRunner(app, agents, progress_stream=progress)

        with patch("dormammu.agent.cli_adapter.CliAdapter.run_once") as mock_run:
            mock_run.return_value = _make_adapter_result(
                tmp_path / "r4",
                stdout="stdout body\n",
                stderr="stderr body\n",
            )
            runner._call_once(
                role="tester",
                cli=Path("claude"),
                model=None,
                prompt="test prompt",
                stem="log-case",
                date_str="20260412",
            )

        log_text = progress.getvalue()
        assert "=== pipeline tester cli ===" in log_text
        assert "command: claude" in log_text
        assert "=== pipeline tester stdout ===" in log_text
        assert "stdout body" in log_text
        assert "=== pipeline tester stderr ===" in log_text
        assert "stderr body" in log_text
