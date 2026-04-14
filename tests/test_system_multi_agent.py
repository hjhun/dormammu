"""System regression tests: multi-agent pipeline with Claude / Codex / Gemini.

Verifies that the goals-scheduler correctly routes each role to a different
CLI and that outputs chain through the planning → design stages.

Role assignments under test
---------------------------
  Claude  → planner   (plan generation)
  Codex   → architect (technical design, receives Claude's plan in prompt)
  Gemini  → tester / reviewer (command construction verified directly)

All subprocess calls are intercepted — no real CLI is executed.

Regression coverage
-------------------
* Exact command-line arguments for claude / codex / gemini (model flags,
  preset prefix/extra args, prompt delivery mode).
* Planner output is embedded in the architect prompt.
* Final queued prompt contains both ``## Plan`` and ``## Design`` sections.
* Role documents are written to the correct ``.dev/<slot>-<role>/`` paths.
* Architect is skipped when the planner produces no output.
* Per-role agent timeout comes from ``GoalsConfig.agent_timeout_seconds``.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from dormammu.agent.prompt_identity import prepend_cli_identity
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
    return mock


def _agents(
    *,
    planner_cli: str = "claude",
    planner_model: str = "claude-sonnet-4-6",
    architect_cli: str = "codex",
    architect_model: str = "o4-mini",
    developer_cli: str = "codex",
    developer_model: str = "o4-mini",
    tester_cli: str = "gemini",
    tester_model: str = "gemini-2.5-pro",
    reviewer_cli: str = "gemini",
    reviewer_model: str = "gemini-2.5-pro",
) -> AgentsConfig:
    return AgentsConfig(
        planner=RoleAgentConfig(cli=Path(planner_cli), model=planner_model),
        architect=RoleAgentConfig(cli=Path(architect_cli), model=architect_model),
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


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    """Return a fake ``subprocess.CompletedProcess``."""
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


# ---------------------------------------------------------------------------
# Claude command construction
# ---------------------------------------------------------------------------


class TestClaudeCommandConstruction:
    """claude (planner): --print prefix, positional prompt, --model flag."""

    def _call_planner(self, sched: GoalsScheduler, prompt: str = "Plan this") -> list[str]:
        with patch("subprocess.run", return_value=_ok(_CLAUDE_PLAN)) as mock_run:
            sched._call_role_agent(
                role="planner",
                cli=Path("claude"),
                model="claude-sonnet-4-6",
                prompt=prompt,
                stem="goal",
                date_str="20260412",
                slot="01",
            )
        return mock_run.call_args[0][0]

    def test_executable_is_claude(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_planner(sched)
        assert args[0] == "claude"

    def test_print_prefix_present(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_planner(sched)
        assert "--print" in args

    def test_dangerously_skip_permissions_present(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_planner(sched)
        assert "--dangerously-skip-permissions" in args

    def test_model_flag_is_double_dash_model(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_planner(sched)
        assert "--model" in args
        assert args[args.index("--model") + 1] == "claude-sonnet-4-6"

    def test_prompt_is_last_positional_arg(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        prompt_text = "Implement the scheduler"
        args = self._call_planner(sched, prompt=prompt_text)
        assert args[-1] == prepend_cli_identity(prompt_text, Path("claude"))

    def test_full_arg_order(self, tmp_path: Path) -> None:
        """Regression: exact order is claude --print --dangerously-skip-permissions --model M <prompt>."""
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_planner(sched, prompt="P")
        assert args == [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--model",
            "claude-sonnet-4-6",
            prepend_cli_identity("P", Path("claude")),
        ]


# ---------------------------------------------------------------------------
# Codex command construction
# ---------------------------------------------------------------------------


class TestCodexCommandConstruction:
    """codex (architect / developer): exec subcommand, positional prompt, -m flag."""

    def _call_architect(self, sched: GoalsScheduler, prompt: str = "Design this") -> list[str]:
        with patch("subprocess.run", return_value=_ok(_CODEX_DESIGN)) as mock_run:
            sched._call_role_agent(
                role="architect",
                cli=Path("codex"),
                model="o4-mini",
                prompt=prompt,
                stem="goal",
                date_str="20260412",
                slot="02",
            )
        return mock_run.call_args[0][0]

    def test_executable_is_codex(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_architect(sched)
        assert args[0] == "codex"

    def test_exec_subcommand_present(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_architect(sched)
        assert "exec" in args

    def test_bypass_approvals_flag_present(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_architect(sched)
        assert "--dangerously-bypass-approvals-and-sandbox" in args

    def test_skip_git_repo_check_present(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_architect(sched)
        assert "--skip-git-repo-check" in args

    def test_model_flag_is_short_m(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_architect(sched)
        assert "-m" in args
        assert args[args.index("-m") + 1] == "o4-mini"

    def test_prompt_is_last_positional_arg(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        prompt_text = "Design the architecture"
        args = self._call_architect(sched, prompt=prompt_text)
        assert args[-1] == prepend_cli_identity(prompt_text, Path("codex"))

    def test_full_arg_order(self, tmp_path: Path) -> None:
        """Regression: exact order is codex exec --dangerously-bypass-... --skip-git-repo-check -m M <prompt>."""
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_architect(sched, prompt="P")
        assert args == [
            "codex", "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "-m", "o4-mini",
            prepend_cli_identity("P", Path("codex")),
        ]


# ---------------------------------------------------------------------------
# Gemini command construction
# ---------------------------------------------------------------------------


class TestGeminiCommandConstruction:
    """gemini (tester / reviewer): --prompt flag, --approval-mode yolo, --model flag."""

    def _call_tester(self, sched: GoalsScheduler, prompt: str = "Test this") -> list[str]:
        with patch("subprocess.run", return_value=_ok(_GEMINI_REVIEW)) as mock_run:
            sched._call_role_agent(
                role="tester",
                cli=Path("gemini"),
                model="gemini-2.5-pro",
                prompt=prompt,
                stem="goal",
                date_str="20260412",
                slot="03",
            )
        return mock_run.call_args[0][0]

    def test_executable_is_gemini(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_tester(sched)
        assert args[0] == "gemini"

    def test_prompt_delivered_via_flag(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        prompt_text = "Run all tests"
        args = self._call_tester(sched, prompt=prompt_text)
        assert "--prompt" in args
        assert args[args.index("--prompt") + 1] == prepend_cli_identity(
            prompt_text,
            Path("gemini"),
        )

    def test_approval_mode_yolo_present(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_tester(sched)
        assert "--approval-mode" in args
        assert args[args.index("--approval-mode") + 1] == "yolo"

    def test_include_directories_slash_present(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_tester(sched)
        assert "--include-directories" in args
        assert args[args.index("--include-directories") + 1] == "/"

    def test_model_flag_is_double_dash_model(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_tester(sched)
        assert "--model" in args
        assert args[args.index("--model") + 1] == "gemini-2.5-pro"

    def test_full_arg_order(self, tmp_path: Path) -> None:
        """Regression: exact order is gemini --approval-mode yolo --include-directories / --model M --prompt <prompt>."""
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        args = self._call_tester(sched, prompt="P")
        assert args == [
            "gemini",
            "--approval-mode", "yolo",
            "--include-directories", "/",
            "--model", "gemini-2.5-pro",
            "--prompt", prepend_cli_identity("P", Path("gemini")),
        ]


# ---------------------------------------------------------------------------
# Multi-agent output chaining
# ---------------------------------------------------------------------------


class TestMultiAgentOutputChaining:
    """Claude's plan must appear verbatim inside Codex's architect prompt."""

    def test_first_call_targets_claude(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        captured: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> MagicMock:
            captured.append(args)
            return _ok(_CLAUDE_PLAN if args[0] == "claude" else _CODEX_DESIGN)

        with patch("subprocess.run", side_effect=fake_run):
            sched._generate_prompt("Build a feature", "feature", "20260412")

        assert captured[0][0] == "claude"

    def test_second_call_targets_codex(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        captured: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> MagicMock:
            captured.append(args)
            return _ok(_CLAUDE_PLAN if args[0] == "claude" else _CODEX_DESIGN)

        with patch("subprocess.run", side_effect=fake_run):
            sched._generate_prompt("Build a feature", "feature", "20260412")

        assert len(captured) == 2
        assert captured[1][0] == "codex"

    def test_architect_prompt_embeds_planner_output(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        captured: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> MagicMock:
            captured.append(list(args))
            return _ok(_CLAUDE_PLAN if args[0] == "claude" else _CODEX_DESIGN)

        with patch("subprocess.run", side_effect=fake_run):
            sched._generate_prompt("Build a feature", "feature", "20260412")

        # Codex uses positional prompt (last arg)
        architect_prompt = captured[1][-1]
        assert _CLAUDE_PLAN.strip() in architect_prompt

    def test_final_prompt_contains_plan_and_design_sections(
        self, tmp_path: Path
    ) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())

        with patch("subprocess.run", side_effect=[_ok(_CLAUDE_PLAN), _ok(_CODEX_DESIGN)]):
            result = sched._generate_prompt("Build a feature", "feature", "20260412")

        assert "## Plan" in result
        assert "## Design" in result
        assert "Phase 1" in result    # from _CLAUDE_PLAN
        assert "Module A" in result   # from _CODEX_DESIGN

    def test_architect_not_called_when_planner_produces_no_output(
        self, tmp_path: Path
    ) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        call_count = 0

        def fake_run(args: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return _ok("")  # empty stdout → planner returns None

        with patch("subprocess.run", side_effect=fake_run):
            result = sched._generate_prompt("Build a feature", "feature", "20260412")

        assert call_count == 1          # only planner called
        assert "## Design" not in result


# ---------------------------------------------------------------------------
# End-to-end regression: goal file → prompt queue
# ---------------------------------------------------------------------------


class TestGoalsSchedulerMultiAgentRegression:
    """Full regression: ``.md`` goal file is processed and written to the queue."""

    def test_queued_prompt_contains_plan_and_design(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "improve-system.md").write_text(
            "Improve system performance", encoding="utf-8"
        )

        with patch("subprocess.run", side_effect=[_ok(_CLAUDE_PLAN), _ok(_CODEX_DESIGN)]):
            with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
                mock_dt.now.return_value.strftime.return_value = "20260412"
                mock_dt.now.return_value.timezone = None
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

        with patch("subprocess.run", side_effect=[_ok(_CLAUDE_PLAN), _ok(_CODEX_DESIGN)]):
            with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
                mock_dt.now.return_value.strftime.return_value = "20260412"
                mock_dt.now.return_value.timezone = None
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

        with patch("subprocess.run", side_effect=[_ok(_CLAUDE_PLAN), _ok(_CODEX_DESIGN)]):
            with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
                mock_dt.now.return_value.strftime.return_value = "20260412"
                mock_dt.now.return_value.timezone = None
                sched._process_goals()

        doc = tmp_path / ".dev" / "01-planner" / "20260412_feature.md"
        assert doc.exists(), "planner document not written"
        assert "Phase 1" in doc.read_text(encoding="utf-8")

    def test_architect_role_document_written_with_codex_output(
        self, tmp_path: Path
    ) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "feature.md").write_text("Add feature X", encoding="utf-8")

        with patch("subprocess.run", side_effect=[_ok(_CLAUDE_PLAN), _ok(_CODEX_DESIGN)]):
            with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
                mock_dt.now.return_value.strftime.return_value = "20260412"
                mock_dt.now.return_value.timezone = None
                sched._process_goals()

        doc = tmp_path / ".dev" / "02-architect" / "20260412_feature.md"
        assert doc.exists(), "architect document not written"
        assert "Module A" in doc.read_text(encoding="utf-8")

    def test_only_goal_section_when_planner_fails(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "feature.md").write_text("Add feature X", encoding="utf-8")

        with patch("subprocess.run", return_value=_ok("", "fatal error", returncode=1)):
            with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
                mock_dt.now.return_value.strftime.return_value = "20260412"
                mock_dt.now.return_value.timezone = None
                sched._process_goals()

        queued = list(prompt_path.glob("*.md"))
        assert len(queued) == 1
        content = queued[0].read_text(encoding="utf-8")
        assert "## Plan" not in content
        assert "## Design" not in content
        assert "Add feature X" in content

    def test_agent_timeout_from_config_passed_to_subprocess(
        self, tmp_path: Path
    ) -> None:
        sched, _, _ = _make_scheduler(
            tmp_path, agents_cfg=_agents(), agent_timeout_seconds=999
        )

        with patch("subprocess.run", return_value=_ok(_CLAUDE_PLAN)) as mock_run:
            sched._call_role_agent(
                role="planner",
                cli=Path("claude"),
                model=None,
                prompt="test",
                stem="goal",
                date_str="20260412",
                slot="01",
            )

        kwargs = mock_run.call_args[1]
        assert kwargs.get("timeout") == 999

    def test_timeout_logs_role_and_seconds(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(
            tmp_path, agents_cfg=_agents(), agent_timeout_seconds=42
        )
        (goals_dir / "feature.md").write_text("Add feature X", encoding="utf-8")

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=42),
        ):
            with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
                mock_dt.now.return_value.strftime.return_value = "20260412"
                mock_dt.now.return_value.timezone = None
                sched._process_goals()

        log = sched._progress_stream.getvalue()
        assert "timed out" in log
        assert "42s" in log

    def test_multiple_goal_files_each_invoke_full_pipeline(
        self, tmp_path: Path
    ) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path, agents_cfg=_agents())
        (goals_dir / "goal-a.md").write_text("Goal A", encoding="utf-8")
        (goals_dir / "goal-b.md").write_text("Goal B", encoding="utf-8")

        # Two goals × two stages = four subprocess calls
        responses = [
            _ok(_CLAUDE_PLAN), _ok(_CODEX_DESIGN),
            _ok(_CLAUDE_PLAN), _ok(_CODEX_DESIGN),
        ]

        with patch("subprocess.run", side_effect=responses) as mock_run:
            with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
                mock_dt.now.return_value.strftime.return_value = "20260412"
                mock_dt.now.return_value.timezone = None
                sched._process_goals()

        assert mock_run.call_count == 4
        queued = sorted(prompt_path.glob("*.md"))
        assert len(queued) == 2
