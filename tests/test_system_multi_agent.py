"""System regression tests: multi-agent pipeline with Claude / Codex / Gemini.

Verifies that the goals-scheduler correctly routes each role to a different
CLI and that outputs chain through the planning → design stages.

Role assignments under test
---------------------------
  Claude  → planner   (plan generation)
  Codex   → designer  (technical design, receives Claude's plan in prompt)
  Gemini  → tester / reviewer

All CliAdapter.run_once calls are intercepted — no real CLI is executed.

Regression coverage
-------------------
* GoalsScheduler routes each role to the correct CLI via AgentRunRequest.
* Model flag construction (--model / -m) is correct per CLI.
* Planner output is embedded in the designer prompt.
* Final queued prompt contains both ``## Plan`` and ``## Design`` sections.
* Role documents are written to ``.dev/logs/<date>_<role>_<stem>.md``.
* Designer is skipped when the planner produces no output.
* CliAdapter failures are caught and return None (graceful degradation).
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dormammu.agent.profiles import resolve_agent_profile
from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig
from dormammu.daemon.goals_config import GoalsConfig
from dormammu.daemon.goals_scheduler import GoalsScheduler


# ---------------------------------------------------------------------------
# Canonical fake outputs
# ---------------------------------------------------------------------------

_CLAUDE_PLAN = (
    "# Implementation Plan\n\n"
    "## Phase 1: Analysis\n- Analyse requirements\n\n"
    "## Phase 2: Development\n- Implement core logic\n"
)
_CODEX_DESIGN = (
    "# Technical Design\n\n"
    "## Module A: Core\n- Handles business logic\n\n"
    "## Module B: API\n- HTTP interface layer\n"
)
_GEMINI_REVIEW = (
    "# Review\n\n"
    "All tests pass. No critical issues detected.\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_config(tmp_path: Path, *, agents: AgentsConfig | None = None) -> Any:
    mock = MagicMock()
    mock.repo_root = tmp_path
    mock.base_dev_dir = tmp_path / ".dev"
    mock.active_agent_cli = None
    mock.agents = agents
    mock.resolve_agent_profile.side_effect = lambda role: resolve_agent_profile(
        role,
        agents_config=agents,
    )
    return mock


def _agents(
    *,
    planner_cli: str = "claude",
    planner_model: str = "claude-sonnet-4-6",
    designer_cli: str = "codex",
    designer_model: str = "o4-mini",
    developer_cli: str = "codex",
    developer_model: str = "o4-mini",
    tester_cli: str = "gemini",
    tester_model: str = "gemini-2.5-pro",
    reviewer_cli: str = "gemini",
    reviewer_model: str = "gemini-2.5-pro",
) -> AgentsConfig:
    return AgentsConfig(
        planner=RoleAgentConfig(cli=Path(planner_cli), model=planner_model),
        designer=RoleAgentConfig(cli=Path(designer_cli), model=designer_model),
        developer=RoleAgentConfig(cli=Path(developer_cli), model=developer_model),
        tester=RoleAgentConfig(cli=Path(tester_cli), model=tester_model),
        reviewer=RoleAgentConfig(cli=Path(reviewer_cli), model=reviewer_model),
    )


def _make_scheduler(
    tmp_path: Path,
    *,
    agents_cfg: AgentsConfig | None = None,
    agent_timeout_seconds: int = 60,
) -> tuple[GoalsScheduler, Path, Path]:
    goals_dir = tmp_path / "goals"
    goals_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = tmp_path / "prompts"
    prompt_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".dev").mkdir(parents=True, exist_ok=True)
    app = _make_app_config(tmp_path, agents=agents_cfg)
    goals_cfg = GoalsConfig(
        path=goals_dir,
        interval_minutes=1,
        agent_timeout_seconds=agent_timeout_seconds,
    )
    stream = io.StringIO()
    sched = GoalsScheduler(goals_cfg, prompt_path, app, progress_stream=stream)
    return sched, goals_dir, prompt_path


def _make_result(tmp_path: Path, output: str = "", run_idx: int = 0) -> MagicMock:
    """Return a mock AgentRunResult with real temp files for stdout/stderr."""
    out_dir = tmp_path / f"_adapter_out_{run_idx}"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = MagicMock()
    stdout_file = out_dir / "stdout.txt"
    stderr_file = out_dir / "stderr.txt"
    stdout_file.write_text(output, encoding="utf-8")
    stderr_file.write_text("", encoding="utf-8")
    result.stdout_path = stdout_file
    result.stderr_path = stderr_file
    result.exit_code = 0
    return result


# ---------------------------------------------------------------------------
# AgentRunRequest construction
# ---------------------------------------------------------------------------


class TestCallRoleAgentRequest:
    """_call_role_agent delegates to CliAdapter.run_once with a correct AgentRunRequest."""

    def _capture_request(
        self, sched: GoalsScheduler, tmp_path: Path, **kwargs: Any
    ) -> Any:
        """Call _call_role_agent and return the AgentRunRequest passed to run_once."""
        with patch("dormammu.agent.cli_adapter.CliAdapter.run_once") as mock_run:
            mock_run.return_value = _make_result(tmp_path)
            sched._call_role_agent(**kwargs)
        return mock_run.call_args[0][0]

    def test_claude_planner_cli_path(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        req = self._capture_request(
            sched, tmp_path,
            role="planner", cli=Path("claude"), model="claude-sonnet-4-6",
            prompt="Plan this", stem="goal", date_str="20260412",
        )
        assert req.cli_path == Path("claude")

    def test_claude_model_in_extra_args(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        req = self._capture_request(
            sched, tmp_path,
            role="planner", cli=Path("claude"), model="claude-sonnet-4-6",
            prompt="Plan this", stem="goal", date_str="20260412",
        )
        assert "--model" in req.extra_args
        assert "claude-sonnet-4-6" in req.extra_args

    def test_codex_designer_cli_path(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        req = self._capture_request(
            sched, tmp_path,
            role="designer", cli=Path("codex"), model="o4-mini",
            prompt="Design this", stem="goal", date_str="20260412",
        )
        assert req.cli_path == Path("codex")

    def test_codex_model_uses_short_m_flag(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        req = self._capture_request(
            sched, tmp_path,
            role="designer", cli=Path("codex"), model="o4-mini",
            prompt="Design this", stem="goal", date_str="20260412",
        )
        assert "-m" in req.extra_args
        assert "o4-mini" in req.extra_args

    def test_gemini_model_uses_double_dash_model(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        req = self._capture_request(
            sched, tmp_path,
            role="tester", cli=Path("gemini"), model="gemini-2.5-pro",
            prompt="Test this", stem="goal", date_str="20260412",
        )
        assert "--model" in req.extra_args
        assert "gemini-2.5-pro" in req.extra_args

    def test_prompt_text_forwarded(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        req = self._capture_request(
            sched, tmp_path,
            role="planner", cli=Path("claude"), model=None,
            prompt="My custom prompt", stem="goal", date_str="20260412",
        )
        assert req.prompt_text == "My custom prompt"

    def test_no_model_yields_empty_extra_args(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        req = self._capture_request(
            sched, tmp_path,
            role="planner", cli=Path("claude"), model=None,
            prompt="P", stem="goal", date_str="20260412",
        )
        assert req.extra_args == ()

    def test_adapter_failure_returns_none(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        with patch("dormammu.agent.cli_adapter.CliAdapter.run_once", side_effect=RuntimeError("boom")):
            result = sched._call_role_agent(
                role="planner", cli=Path("claude"), model=None,
                prompt="P", stem="goal", date_str="20260412",
            )
        assert result is None


# ---------------------------------------------------------------------------
# Multi-agent output chaining
# ---------------------------------------------------------------------------


class TestMultiAgentOutputChaining:
    """Claude's plan must appear verbatim inside Codex's designer prompt."""

    @staticmethod
    def _run_generate(
        sched: GoalsScheduler,
        tmp_path: Path,
        outputs: dict[str, str] | None = None,
    ) -> tuple[list[Any], str]:
        """Run _generate_prompt, intercept run_once, return (captured_requests, result)."""
        captured: list[Any] = []
        run_idx = [0]
        out_map: dict[str, str] = {"claude": _CLAUDE_PLAN, "codex": _CODEX_DESIGN}
        if outputs:
            out_map.update(outputs)

        def fake_run_once(req: Any) -> MagicMock:
            captured.append(req)
            idx = run_idx[0]
            run_idx[0] += 1
            output = out_map.get(req.cli_path.name, "")
            return _make_result(tmp_path, output, idx)

        with patch(
            "dormammu.agent.cli_adapter.CliAdapter.run_once", side_effect=fake_run_once
        ):
            result = sched._generate_prompt("Build a feature", "feature", "20260412")

        return captured, result

    def test_first_call_targets_claude(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        captured, _ = self._run_generate(sched, tmp_path)
        assert captured[0].cli_path == Path("claude")

    def test_second_call_targets_codex(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        captured, _ = self._run_generate(sched, tmp_path)
        assert len(captured) == 2
        assert captured[1].cli_path == Path("codex")

    def test_designer_prompt_embeds_planner_output(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        captured, _ = self._run_generate(sched, tmp_path)
        designer_prompt = captured[1].prompt_text
        assert _CLAUDE_PLAN.strip() in designer_prompt

    def test_final_prompt_contains_plan_and_design_sections(
        self, tmp_path: Path
    ) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        _, result = self._run_generate(sched, tmp_path)
        assert "## Plan" in result
        assert "## Design" in result
        assert "Phase 1" in result    # from _CLAUDE_PLAN
        assert "Module A" in result   # from _CODEX_DESIGN

    def test_designer_not_called_when_planner_produces_no_output(
        self, tmp_path: Path
    ) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        run_idx = [0]

        def fake_run_once(req: Any) -> MagicMock:
            idx = run_idx[0]
            run_idx[0] += 1
            return _make_result(tmp_path, "", idx)  # empty → planner returns None

        with patch(
            "dormammu.agent.cli_adapter.CliAdapter.run_once", side_effect=fake_run_once
        ) as mock_run:
            result = sched._generate_prompt("Build a feature", "feature", "20260412")

        assert mock_run.call_count == 1  # only planner called
        assert "## Design" not in result


# ---------------------------------------------------------------------------
# End-to-end regression: goal file → prompt queue
# ---------------------------------------------------------------------------


class TestGoalsSchedulerMultiAgentRegression:
    """Full regression: ``.md`` goal file is processed and written to the queue."""

    @staticmethod
    def _patch_run_once(
        tmp_path: Path,
        per_cli_outputs: dict[str, list[str]] | None = None,
    ):
        """Return a patch context manager for CliAdapter.run_once with per-CLI outputs."""
        counters: dict[str, int] = {}
        run_idx = [0]
        per_cli: dict[str, list[str]] = per_cli_outputs or {
            "claude": [_CLAUDE_PLAN],
            "codex": [_CODEX_DESIGN],
        }

        def fake_run_once(req: Any) -> MagicMock:
            name = req.cli_path.name
            seq = per_cli.get(name, [""])
            idx_in_seq = counters.get(name, 0)
            counters[name] = idx_in_seq + 1
            output = seq[idx_in_seq] if idx_in_seq < len(seq) else ""
            result = _make_result(tmp_path, output, run_idx[0])
            run_idx[0] += 1
            return result

        return patch(
            "dormammu.agent.cli_adapter.CliAdapter.run_once", side_effect=fake_run_once
        )

    @staticmethod
    def _mock_datetime():
        """Return a patch context manager that fixes the date to 20260412."""
        return patch("dormammu.daemon.goals_scheduler.datetime")

    @staticmethod
    def _apply_date_mock(mock_dt: Any) -> None:
        mock_dt.now.return_value.strftime.return_value = "20260412"
        mock_dt.now.return_value.timezone = None

    def test_queued_prompt_contains_plan_and_design(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "improve-system.md").write_text(
            "Improve system performance", encoding="utf-8"
        )

        with self._patch_run_once(tmp_path):
            with self._mock_datetime() as mock_dt:
                self._apply_date_mock(mock_dt)
                sched._process_goals()

        queued = list(prompt_path.glob("*.md"))
        assert len(queued) == 1
        content = queued[0].read_text(encoding="utf-8")
        assert "## Plan" in content
        assert "## Design" in content

    def test_queued_prompt_contains_english_language_requirement(
        self, tmp_path: Path
    ) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "feature.md").write_text("목표: 시스템 개선", encoding="utf-8")

        with self._patch_run_once(tmp_path):
            with self._mock_datetime() as mock_dt:
                self._apply_date_mock(mock_dt)
                sched._process_goals()

        content = list(prompt_path.glob("*.md"))[0].read_text(encoding="utf-8")
        assert "Language requirement" in content
        assert "English" in content
        # Notice must precede the Goal section
        assert content.index("Language requirement") < content.index("# Goal")

    def test_planner_role_document_written_with_claude_output(
        self, tmp_path: Path
    ) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "feature.md").write_text("Add feature X", encoding="utf-8")

        with self._patch_run_once(tmp_path):
            with self._mock_datetime() as mock_dt:
                self._apply_date_mock(mock_dt)
                sched._process_goals()

        doc = tmp_path / ".dev" / "logs" / "20260412_planner_feature.md"
        assert doc.exists(), "planner document not written"
        assert "Phase 1" in doc.read_text(encoding="utf-8")

    def test_designer_role_document_written_with_codex_output(
        self, tmp_path: Path
    ) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "feature.md").write_text("Add feature X", encoding="utf-8")

        with self._patch_run_once(tmp_path):
            with self._mock_datetime() as mock_dt:
                self._apply_date_mock(mock_dt)
                sched._process_goals()

        doc = tmp_path / ".dev" / "logs" / "20260412_designer_feature.md"
        assert doc.exists(), "designer document not written"
        assert "Module A" in doc.read_text(encoding="utf-8")

    def test_only_goal_section_when_planner_fails(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "feature.md").write_text("Add feature X", encoding="utf-8")

        with patch(
            "dormammu.agent.cli_adapter.CliAdapter.run_once",
            side_effect=RuntimeError("fatal error"),
        ):
            with self._mock_datetime() as mock_dt:
                self._apply_date_mock(mock_dt)
                sched._process_goals()

        queued = list(prompt_path.glob("*.md"))
        assert len(queued) == 1
        content = queued[0].read_text(encoding="utf-8")
        assert "## Plan" not in content
        assert "## Design" not in content
        assert "Add feature X" in content

    def test_multiple_goal_files_each_invoke_full_pipeline(
        self, tmp_path: Path
    ) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "goal-a.md").write_text("Goal A", encoding="utf-8")
        (goals_dir / "goal-b.md").write_text("Goal B", encoding="utf-8")

        # Two goals × two stages (planner + designer) = four run_once calls
        with self._patch_run_once(
            tmp_path,
            per_cli_outputs={
                "claude": [_CLAUDE_PLAN, _CLAUDE_PLAN],
                "codex": [_CODEX_DESIGN, _CODEX_DESIGN],
            },
        ) as mock_run:
            with self._mock_datetime() as mock_dt:
                self._apply_date_mock(mock_dt)
                sched._process_goals()

        assert mock_run.call_count == 4
        queued = sorted(prompt_path.glob("*.md"))
        assert len(queued) == 2
