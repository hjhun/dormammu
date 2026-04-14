"""Unit and integration tests for PipelineRunner."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig
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
            verdict, _ = runner._run_plan_evaluator(
                "goal", stem="g", date_str="20260412"
            )

        assert verdict == "proceed"

    def test_plan_evaluator_ambiguous_output_fails_closed_to_rework(
        self, tmp_path: Path
    ) -> None:
        agents = AgentsConfig(evaluator=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)

        with patch.object(runner, "_call_once", return_value="checkpoint without verdict"):
            verdict, _ = runner._run_plan_evaluator(
                "goal", stem="g", date_str="20260412"
            )

        assert verdict == "rework"

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
                    ("rework", "DECISION: REWORK"),
                    ("proceed", "DECISION: PROCEED"),
                ],
            ) as mock_eval,
        ):
            runner.run_refine_and_plan("goal", stem="g", date_str="20260412")

        mock_refiner.assert_called_once()
        assert mock_planner.call_count == 2
        assert mock_eval.call_count == 2

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
                return_value=("rework", "DECISION: REWORK"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Mandatory plan evaluator"):
                runner.run_refine_and_plan("goal", stem="g", date_str="20260412")


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
            verdict, _ = runner._run_tester("goal", stem="g", date_str="20260412")
        assert verdict == "pass"

    def test_fail_verdict_on_overall_fail(self, tmp_path: Path) -> None:
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="Test X failed.\nOVERALL: FAIL"):
            verdict, _ = runner._run_tester("goal", stem="g", date_str="20260412")
        assert verdict == "fail"

    def test_pass_verdict_when_neither_marker_present(self, tmp_path: Path) -> None:
        """Ambiguous output defaults to pass (conservative)."""
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="No verdict line."):
            verdict, _ = runner._run_tester("goal", stem="g", date_str="20260412")
        assert verdict == "pass"

    def test_case_insensitive_fail(self, tmp_path: Path) -> None:
        agents = AgentsConfig(tester=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="overall: fail"):
            verdict, _ = runner._run_tester("goal", stem="g", date_str="20260412")
        assert verdict == "fail"


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
            verdict, _ = runner._run_reviewer("goal", stem="g", date_str="20260412")
        assert verdict == "approved"

    def test_needs_work_verdict(self, tmp_path: Path) -> None:
        agents = AgentsConfig(reviewer=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(
            runner, "_call_once", return_value="Issues found.\nVERDICT: NEEDS_WORK"
        ):
            verdict, _ = runner._run_reviewer("goal", stem="g", date_str="20260412")
        assert verdict == "needs_work"

    def test_approved_when_neither_marker_present(self, tmp_path: Path) -> None:
        """Ambiguous output defaults to approved (conservative)."""
        agents = AgentsConfig(reviewer=RoleAgentConfig(cli=Path("echo")))
        runner = _make_runner(tmp_path, agents=agents)
        with patch.object(runner, "_call_once", return_value="No verdict."):
            verdict, _ = runner._run_reviewer("goal", stem="g", date_str="20260412")
        assert verdict == "approved"

    def test_architect_doc_included_in_prompt(self, tmp_path: Path) -> None:
        agents = AgentsConfig(reviewer=RoleAgentConfig(cli=Path("echo")))
        app = _make_app_config(tmp_path, agents=agents)
        stream = io.StringIO()
        runner = PipelineRunner(app, agents, progress_stream=stream)

        # Create a fake architect doc
        arch_dir = tmp_path / ".dev" / "02-architect"
        arch_dir.mkdir(parents=True)
        (arch_dir / "20260412_my-feat.md").write_text(
            "# Architect Design", encoding="utf-8"
        )

        captured: list[str] = []

        def fake_call_once(*, role, cli, model, prompt, stem, date_str, slot):
            captured.append(prompt)
            return "VERDICT: APPROVED"

        with patch.object(runner, "_call_once", side_effect=fake_call_once):
            runner._run_reviewer("goal", stem="my-feat", date_str="20260412")

        assert "Architect Design" in captured[0]


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
                runner, "_run_tester", return_value=("pass", "OVERALL: PASS")
            ) as mock_tester,
            patch.object(
                runner, "_run_reviewer", return_value=("approved", "VERDICT: APPROVED")
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

    def test_tester_fail_triggers_developer_reentry(self, tmp_path: Path) -> None:
        agents = AgentsConfig(
            developer=RoleAgentConfig(cli=Path("claude")),
            tester=RoleAgentConfig(cli=Path("claude")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        tester_responses = [
            ("fail", "OVERALL: FAIL"),
            ("pass", "OVERALL: PASS"),
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
            ("needs_work", "VERDICT: NEEDS_WORK"),
            ("approved", "VERDICT: APPROVED"),
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
                runner, "_run_tester", return_value=("fail", "OVERALL: FAIL")
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
                runner, "_run_reviewer", return_value=("needs_work", "VERDICT: NEEDS_WORK")
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
            ("fail", "failure details here"),
            ("pass", "OVERALL: PASS"),
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


class TestDocumentWriting:
    def test_call_once_writes_role_doc(self, tmp_path: Path) -> None:
        agents = AgentsConfig()
        app = _make_app_config(tmp_path, agents=agents)
        runner = PipelineRunner(app, agents, progress_stream=io.StringIO())

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="agent output", returncode=0)
            runner._call_once(
                role="tester",
                cli=Path("claude"),
                model=None,
                prompt="test prompt",
                stem="my-feature",
                date_str="20260412",
                slot="04",
            )

        doc = tmp_path / ".dev" / "04-tester" / "20260412_my-feature.md"
        assert doc.exists()
        content = doc.read_text(encoding="utf-8")
        assert "Tester" in content
        assert "agent output" in content
