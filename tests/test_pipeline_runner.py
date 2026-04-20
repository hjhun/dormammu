"""Unit and integration tests for PipelineRunner."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from dormammu.agent.prompt_identity import prepend_cli_identity
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
    return PipelineRunner(app, agents, progress_stream=stream)


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

        assert output == "requirements"
        assert mock_call.call_args.kwargs["cli"] == Path("claude")

    def test_planner_uses_active_cli_fallback(self, tmp_path: Path) -> None:
        runner = _make_runner(tmp_path, active_agent_cli=Path("claude"))

        with patch.object(runner, "_call_once", return_value="plan") as mock_call:
            output = runner._run_planner("goal", stem="g", date_str="20260412")

        assert output == "plan"
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

    def test_pass_verdict_when_neither_marker_present(self, tmp_path: Path) -> None:
        """Ambiguous output defaults to pass (conservative)."""
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="No verdict line."):
            stage = runner._run_tester("goal", stem="g", date_str="20260412")
        assert stage is not None and stage.verdict == "pass"

    def test_case_insensitive_fail(self, tmp_path: Path) -> None:
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="overall: fail"):
            stage = runner._run_tester("goal", stem="g", date_str="20260412")
        assert stage is not None and stage.verdict == "fail"


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

    def test_approved_when_neither_marker_present(self, tmp_path: Path) -> None:
        """Ambiguous output defaults to approved (conservative)."""
        agents = AgentsConfig(reviewer=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="No verdict."):
            stage = runner._run_reviewer("goal", stem="g", date_str="20260412")
        assert stage is not None and stage.verdict == "approved"

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
            patch.object(runner, "_run_committer") as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "completed"
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
            patch.object(runner, "_run_committer"),
        ):
            runner.run("goal", stem="s", date_str="20260412")

        assert mock_prelude.call_args.kwargs["enable_plan_evaluator"] is False

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
            patch.object(runner, "_run_committer"),
            patch.object(runner, "_run_evaluator"),
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

        tester_responses = [
            StageResult(role="tester", verdict="fail", output="OVERALL: FAIL"),
            StageResult(role="tester", verdict="pass", output="OVERALL: PASS"),
        ]

        with (
            patch.object(runner, "run_refine_and_plan"),
            patch.object(
                runner, "_run_developer", return_value=_make_loop_result("completed")
            ) as mock_dev,
            patch.object(
                runner, "_run_tester", side_effect=tester_responses
            ) as mock_tester,
            patch.object(runner, "_run_reviewer", return_value=None),
            patch.object(runner, "_run_committer"),
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "completed"
        assert mock_dev.call_count == 2  # developer ran twice
        assert mock_tester.call_count == 2

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
            patch.object(runner, "_run_committer"),
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
            patch.object(runner, "_run_committer") as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "failed"
        # Tester/reviewer/committer must NOT be called on developer failure
        mock_tester.assert_not_called()
        mock_reviewer.assert_not_called()
        mock_committer.assert_not_called()

    def test_tester_fails_max_iterations_continues_to_reviewer(
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
            patch.object(runner, "_run_reviewer", return_value=None),
            patch.object(runner, "_run_committer"),
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "completed"
        assert mock_dev.call_count == MAX_STAGE_ITERATIONS
        assert mock_tester.call_count == MAX_STAGE_ITERATIONS

    def test_reviewer_fails_max_iterations_continues_to_committer(
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
            patch.object(runner, "_run_committer") as mock_committer,
        ):
            result = runner.run("goal", stem="s", date_str="20260412")

        assert result.status == "completed"
        # developer re-ran MAX_STAGE_ITERATIONS times total
        assert mock_dev.call_count == MAX_STAGE_ITERATIONS
        assert mock_reviewer.call_count == MAX_STAGE_ITERATIONS
        mock_committer.assert_called_once()

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
            patch.object(runner, "_run_committer"),
        ):
            runner.run("original goal", stem="s", date_str="20260412")

        # Second developer call should have tester feedback appended
        assert len(captured_prompts) == 2
        assert "failure details here" in captured_prompts[1]
        assert "# Feedback from tester" in captured_prompts[1]


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
