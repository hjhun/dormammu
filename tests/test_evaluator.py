"""Unit tests for the EvaluatorStage and EvaluatorConfig."""
from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dormammu.agent.prompt_identity import prepend_cli_identity
from dormammu.daemon.evaluator import (
    EvaluatorRequest,
    EvaluatorResult,
    EvaluatorStage,
    resolve_evaluator_cli,
    resolve_evaluator_model,
    _VERDICT_RE,
    _NEXT_GOAL_RE,
)
from dormammu.daemon.goals_config import (
    EvaluatorConfig,
    GoalsConfig,
    parse_evaluator_config,
    parse_goals_config,
    VALID_NEXT_GOAL_STRATEGIES,
)
from dormammu.daemon.pipeline_runner import _strip_goal_source_tag

AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    tmp_path: Path,
    *,
    goal_text: str = "Implement feature X",
    next_goal_strategy: str = "none",
    cli: Path | None = None,
    model: str | None = None,
) -> EvaluatorRequest:
    goal_file = tmp_path / "goals" / "feature_x.md"
    goal_file.parent.mkdir(parents=True, exist_ok=True)
    goal_file.write_text(goal_text, encoding="utf-8")
    dev_dir = tmp_path / ".dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    return EvaluatorRequest(
        cli=cli or Path("claude"),
        model=model,
        goal_file_path=goal_file,
        goal_text=goal_text,
        repo_root=tmp_path,
        dev_dir=dev_dir,
        agents_dir=AGENTS_DIR,
        next_goal_strategy=next_goal_strategy,
        stem="feature_x",
        date_str="20260413",
    )


def _make_stage(tmp_path: Path) -> tuple[EvaluatorStage, io.StringIO]:
    stream = io.StringIO()
    stage = EvaluatorStage(progress_stream=stream)
    return stage, stream


# ---------------------------------------------------------------------------
# EvaluatorConfig parsing
# ---------------------------------------------------------------------------


class TestParseEvaluatorConfig:
    def _config_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "daemonize.json"
        p.write_text("{}", encoding="utf-8")
        return p

    def test_none_returns_none(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        assert parse_evaluator_config(None, config_path=cp) is None

    def test_defaults(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        cfg = parse_evaluator_config({}, config_path=cp)
        assert cfg is not None
        assert cfg.enabled is False
        assert cfg.cli is None
        assert cfg.model is None
        assert cfg.next_goal_strategy == "none"

    def test_enabled_true(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        cfg = parse_evaluator_config({"enabled": True}, config_path=cp)
        assert cfg is not None
        assert cfg.enabled is True

    def test_model_set(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        cfg = parse_evaluator_config(
            {"model": "claude-sonnet-4-6"}, config_path=cp
        )
        assert cfg is not None
        assert cfg.model == "claude-sonnet-4-6"

    def test_next_goal_strategy_auto(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        cfg = parse_evaluator_config(
            {"next_goal_strategy": "auto"}, config_path=cp
        )
        assert cfg is not None
        assert cfg.next_goal_strategy == "auto"

    def test_next_goal_strategy_suggest(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        cfg = parse_evaluator_config(
            {"next_goal_strategy": "suggest"}, config_path=cp
        )
        assert cfg is not None
        assert cfg.next_goal_strategy == "suggest"

    def test_invalid_strategy_raises(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        with pytest.raises(RuntimeError, match="next_goal_strategy"):
            parse_evaluator_config(
                {"next_goal_strategy": "invalid"}, config_path=cp
            )

    def test_not_a_mapping_raises(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        with pytest.raises(RuntimeError, match="goals.evaluator"):
            parse_evaluator_config("bad", config_path=cp)

    def test_invalid_cli_raises(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        with pytest.raises(RuntimeError, match="goals.evaluator.cli"):
            parse_evaluator_config({"cli": 123}, config_path=cp)

    def test_invalid_model_raises(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        with pytest.raises(RuntimeError, match="goals.evaluator.model"):
            parse_evaluator_config({"model": ""}, config_path=cp)

    def test_to_dict(self, tmp_path: Path) -> None:
        cp = self._config_path(tmp_path)
        cfg = parse_evaluator_config(
            {"enabled": True, "model": "claude-sonnet-4-6", "next_goal_strategy": "auto"},
            config_path=cp,
        )
        assert cfg is not None
        d = cfg.to_dict()
        assert d["enabled"] is True
        assert d["model"] == "claude-sonnet-4-6"
        assert d["next_goal_strategy"] == "auto"
        assert d["cli"] is None


# ---------------------------------------------------------------------------
# GoalsConfig with evaluator
# ---------------------------------------------------------------------------


class TestGoalsConfigWithEvaluator:
    def test_evaluator_parsed_from_goals_section(self, tmp_path: Path) -> None:
        cp = tmp_path / "daemonize.json"
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        cp.write_text("{}", encoding="utf-8")
        cfg = parse_goals_config(
            {
                "path": str(goals_dir),
                "interval_minutes": 30,
                "evaluator": {"enabled": True, "next_goal_strategy": "auto"},
            },
            config_path=cp,
        )
        assert cfg is not None
        assert cfg.evaluator is not None
        assert cfg.evaluator.enabled is True
        assert cfg.evaluator.next_goal_strategy == "auto"

    def test_evaluator_absent_defaults_to_none(self, tmp_path: Path) -> None:
        cp = tmp_path / "daemonize.json"
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        cp.write_text("{}", encoding="utf-8")
        cfg = parse_goals_config(
            {"path": str(goals_dir), "interval_minutes": 30},
            config_path=cp,
        )
        assert cfg is not None
        assert cfg.evaluator is None

    def test_to_dict_includes_evaluator(self, tmp_path: Path) -> None:
        cp = tmp_path / "daemonize.json"
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        cp.write_text("{}", encoding="utf-8")
        cfg = parse_goals_config(
            {
                "path": str(goals_dir),
                "interval_minutes": 10,
                "evaluator": {"enabled": True},
            },
            config_path=cp,
        )
        assert cfg is not None
        d = cfg.to_dict()
        assert d["evaluator"] is not None
        assert d["evaluator"]["enabled"] is True  # type: ignore[index]


# ---------------------------------------------------------------------------
# resolve_evaluator_cli / resolve_evaluator_model
# ---------------------------------------------------------------------------


class TestResolveCli:
    def _cfg(self, cli: Path | None = None, model: str | None = None) -> EvaluatorConfig:
        return EvaluatorConfig(enabled=True, cli=cli, model=model)

    def test_evaluator_config_cli_wins(self) -> None:
        cfg = self._cfg(cli=Path("/opt/claude-eval"))
        result = resolve_evaluator_cli(cfg, Path("agents-eval"), Path("active"))
        assert result == Path("/opt/claude-eval")

    def test_agents_evaluator_cli_second_priority(self) -> None:
        cfg = self._cfg(cli=None)
        result = resolve_evaluator_cli(cfg, Path("agents-eval"), Path("active"))
        assert result == Path("agents-eval")

    def test_active_agent_cli_fallback(self) -> None:
        cfg = self._cfg(cli=None)
        result = resolve_evaluator_cli(cfg, None, Path("active"))
        assert result == Path("active")

    def test_all_none_returns_none(self) -> None:
        cfg = self._cfg(cli=None)
        assert resolve_evaluator_cli(cfg, None, None) is None

    def test_evaluator_config_model_wins(self) -> None:
        cfg = self._cfg(model="claude-opus-4-6")
        assert resolve_evaluator_model(cfg, "claude-sonnet-4-6") == "claude-opus-4-6"

    def test_agents_model_fallback(self) -> None:
        cfg = self._cfg(model=None)
        assert resolve_evaluator_model(cfg, "claude-sonnet-4-6") == "claude-sonnet-4-6"

    def test_both_none_returns_none(self) -> None:
        cfg = self._cfg(model=None)
        assert resolve_evaluator_model(cfg, None) is None


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------


class TestVerdictRegex:
    def test_goal_achieved(self) -> None:
        m = _VERDICT_RE.search("VERDICT: goal_achieved")
        assert m is not None
        assert m.group(1).lower() == "goal_achieved"

    def test_partial(self) -> None:
        m = _VERDICT_RE.search("VERDICT: partial")
        assert m is not None
        assert m.group(1).lower() == "partial"

    def test_not_achieved(self) -> None:
        m = _VERDICT_RE.search("Some text\nVERDICT: not_achieved\n")
        assert m is not None
        assert m.group(1).lower() == "not_achieved"

    def test_case_insensitive(self) -> None:
        m = _VERDICT_RE.search("verdict : GOAL_ACHIEVED")
        assert m is not None

    def test_no_match(self) -> None:
        assert _VERDICT_RE.search("no verdict here") is None


class TestNextGoalRegex:
    def test_extracts_content(self) -> None:
        text = (
            "Some output\n"
            "<!-- next_goal_start -->\n"
            "Implement feature Y\n"
            "<!-- next_goal_end -->\n"
        )
        m = _NEXT_GOAL_RE.search(text)
        assert m is not None
        assert "Implement feature Y" in m.group(1)

    def test_multiline_content(self) -> None:
        text = (
            "<!-- next_goal_start -->\n"
            "Line 1\nLine 2\nLine 3\n"
            "<!-- next_goal_end -->"
        )
        m = _NEXT_GOAL_RE.search(text)
        assert m is not None
        content = m.group(1)
        assert "Line 1" in content
        assert "Line 3" in content

    def test_no_match(self) -> None:
        assert _NEXT_GOAL_RE.search("no delimiters here") is None


# ---------------------------------------------------------------------------
# _strip_goal_source_tag (pipeline_runner helper)
# ---------------------------------------------------------------------------


class TestStripGoalSourceTag:
    def test_strips_tag(self) -> None:
        text = (
            "<!-- dormammu:goal_source=/goals/my_goal.md -->\n\n"
            "# Goal\n\nDo something\n"
        )
        result = _strip_goal_source_tag(text)
        assert "dormammu:goal_source" not in result
        assert "# Goal" in result

    def test_no_tag_unchanged(self) -> None:
        text = "# Goal\n\nDo something\n"
        assert _strip_goal_source_tag(text) == text.lstrip()

    def test_only_strips_first_occurrence(self) -> None:
        text = (
            "<!-- dormammu:goal_source=/goals/a.md -->\n\n"
            "<!-- dormammu:goal_source=/goals/b.md -->\n\n"
            "content"
        )
        result = _strip_goal_source_tag(text)
        # Second tag should remain
        assert "goal_source=/goals/b.md" in result


# ---------------------------------------------------------------------------
# EvaluatorStage._build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_contains_goal_text(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        req = _make_request(tmp_path, goal_text="Build a rocket ship")
        prompt = stage._build_prompt(req)
        assert "Build a rocket ship" in prompt

    def test_contains_verdict_instruction(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        req = _make_request(tmp_path)
        prompt = stage._build_prompt(req)
        assert "VERDICT:" in prompt

    def test_strategy_none_no_next_goal_block(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        req = _make_request(tmp_path, next_goal_strategy="none")
        prompt = stage._build_prompt(req)
        assert "next_goal_start" not in prompt
        assert "Suggestions for Next Cycle" not in prompt

    def test_strategy_auto_includes_next_goal_delimiters(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        req = _make_request(tmp_path, next_goal_strategy="auto")
        prompt = stage._build_prompt(req)
        assert "next_goal_start" in prompt
        assert "next_goal_end" in prompt

    def test_strategy_suggest_no_next_goal_delimiters(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        req = _make_request(tmp_path, next_goal_strategy="suggest")
        prompt = stage._build_prompt(req)
        assert "Suggestions for Next Cycle" in prompt
        assert "next_goal_start" not in prompt

    def test_includes_plan_when_present(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path)
        (req.dev_dir / "PLAN.md").write_text("[O] Phase 1. Done", encoding="utf-8")
        stage, _ = _make_stage(tmp_path)
        prompt = stage._build_prompt(req)
        assert "Phase 1. Done" in prompt

    def test_omits_plan_when_absent(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path)
        stage, _ = _make_stage(tmp_path)
        prompt = stage._build_prompt(req)
        assert "Completed Plan" not in prompt


# ---------------------------------------------------------------------------
# EvaluatorStage._parse_verdict
# ---------------------------------------------------------------------------


class TestParseVerdict:
    def test_goal_achieved(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        assert stage._parse_verdict("VERDICT: goal_achieved") == "goal_achieved"

    def test_partial(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        assert stage._parse_verdict("VERDICT: partial") == "partial"

    def test_not_achieved(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        assert stage._parse_verdict("VERDICT: not_achieved") == "not_achieved"

    def test_unknown_when_missing(self, tmp_path: Path) -> None:
        stage, _ = _make_stage(tmp_path)
        assert stage._parse_verdict("No verdict here") == "unknown"


# ---------------------------------------------------------------------------
# EvaluatorStage goal file write-back
# ---------------------------------------------------------------------------


class TestGoalFileWriteBack:
    def test_strategy_none_leaves_goal_file_unchanged(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path, next_goal_strategy="none")
        original_content = req.goal_file_path.read_text()
        stage, _ = _make_stage(tmp_path)
        updated = stage._update_goal_file(req, "VERDICT: goal_achieved", "goal_achieved")
        assert updated is False
        assert req.goal_file_path.read_text() == original_content

    def test_strategy_suggest_appends_to_goal_file(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path, next_goal_strategy="suggest")
        original_content = req.goal_file_path.read_text()
        stage, _ = _make_stage(tmp_path)
        output = "Assessment text\nVERDICT: partial"
        updated = stage._update_goal_file(req, output, "partial")
        assert updated is True
        new_content = req.goal_file_path.read_text()
        assert original_content in new_content
        assert "partial" in new_content
        assert "Evaluation" in new_content

    def test_strategy_auto_overwrites_goal_file(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path, next_goal_strategy="auto")
        output = (
            "Assessment\n"
            "VERDICT: goal_achieved\n"
            "<!-- next_goal_start -->\n"
            "Implement feature Y with acceptance criteria\n"
            "<!-- next_goal_end -->\n"
        )
        stage, _ = _make_stage(tmp_path)
        updated = stage._update_goal_file(req, output, "goal_achieved")
        assert updated is True
        new_content = req.goal_file_path.read_text()
        assert "Implement feature Y" in new_content
        assert "Implement feature X" not in new_content

    def test_strategy_auto_no_next_goal_block_does_not_update(
        self, tmp_path: Path
    ) -> None:
        req = _make_request(tmp_path, next_goal_strategy="auto")
        output = "Assessment\nVERDICT: goal_achieved\n"
        original_content = req.goal_file_path.read_text()
        stage, _ = _make_stage(tmp_path)
        updated = stage._update_goal_file(req, output, "goal_achieved")
        assert updated is False
        assert req.goal_file_path.read_text() == original_content

    def test_strategy_auto_empty_next_goal_block_does_not_update(
        self, tmp_path: Path
    ) -> None:
        req = _make_request(tmp_path, next_goal_strategy="auto")
        output = (
            "Assessment\nVERDICT: goal_achieved\n"
            "<!-- next_goal_start --><!-- next_goal_end -->\n"
        )
        original_content = req.goal_file_path.read_text()
        stage, _ = _make_stage(tmp_path)
        updated = stage._update_goal_file(req, output, "goal_achieved")
        assert updated is False
        assert req.goal_file_path.read_text() == original_content


# ---------------------------------------------------------------------------
# EvaluatorStage.run (integration, mocked subprocess)
# ---------------------------------------------------------------------------


class TestEvaluatorStageRun:
    def _patch_run(
        self,
        stdout: str,
        returncode: int = 0,
        *,
        stderr: str = "",
    ):
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stdout = stdout
        mock_result.stderr = stderr
        return patch("subprocess.run", return_value=mock_result)

    def test_run_completed_with_goal_achieved(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path, next_goal_strategy="none")
        agent_output = "Great work!\nVERDICT: goal_achieved\n"
        stage, _ = _make_stage(tmp_path)
        with self._patch_run(agent_output):
            result = stage.run(req)
        assert result.status == "completed"
        assert result.verdict == "goal_achieved"
        assert result.report_path is not None
        assert result.report_path.exists()
        assert result.goal_file_updated is False

    def test_run_writes_report_file(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path)
        stage, _ = _make_stage(tmp_path)
        with self._patch_run("VERDICT: partial"):
            result = stage.run(req)
        assert result.report_path is not None
        content = result.report_path.read_text()
        assert "VERDICT: partial" in content

    def test_run_failed_when_subprocess_raises(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path)
        stage, _ = _make_stage(tmp_path)
        with patch("subprocess.run", side_effect=OSError("no such file")):
            result = stage.run(req)
        assert result.status == "failed"
        assert result.verdict == "unknown"
        assert result.goal_file_updated is False

    def test_run_auto_strategy_overwrites_goal(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path, next_goal_strategy="auto")
        agent_output = (
            "All done.\nVERDICT: goal_achieved\n"
            "<!-- next_goal_start -->\nNext: implement feature Y\n<!-- next_goal_end -->\n"
        )
        stage, _ = _make_stage(tmp_path)
        with self._patch_run(agent_output):
            result = stage.run(req)
        assert result.goal_file_updated is True
        assert "feature Y" in req.goal_file_path.read_text()

    def test_report_stored_in_07_evaluator_slot(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path, next_goal_strategy="none")
        stage, _ = _make_stage(tmp_path)
        with self._patch_run("VERDICT: partial"):
            result = stage.run(req)
        assert result.report_path is not None
        assert "07-evaluator" in str(result.report_path)
        assert req.date_str in result.report_path.name
        assert req.stem in result.report_path.name

    def test_run_prefixes_prompt_with_cli_name(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path, cli=Path("claude"))
        stage, _ = _make_stage(tmp_path)
        prompt = stage._build_prompt(req)
        with self._patch_run("VERDICT: partial") as mock_run:
            stage._call_once(req, prompt)
        assert mock_run.call_args[0][0][-1] == prepend_cli_identity(
            prompt,
            Path("claude"),
        )

    def test_call_once_uses_stderr_when_stdout_is_blank(self, tmp_path: Path) -> None:
        req = _make_request(tmp_path, cli=Path("claude"))
        stage, _ = _make_stage(tmp_path)
        prompt = stage._build_prompt(req)
        with self._patch_run(" \n", stderr="VERDICT: partial\n"):
            output = stage._call_once(req, prompt)
        assert output == "VERDICT: partial\n"
