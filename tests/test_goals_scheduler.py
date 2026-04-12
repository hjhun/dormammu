"""Unit and integration tests for GoalsScheduler."""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dormammu.daemon.goals_config import GoalsConfig
from dormammu.daemon.goals_scheduler import GoalsScheduler, _model_flag_for


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_config(tmp_path: Path, *, agents=None) -> Any:
    mock = MagicMock()
    mock.repo_root = tmp_path
    mock.base_dev_dir = tmp_path / ".dev"
    mock.active_agent_cli = None
    mock.agents = agents
    return mock


def _make_scheduler(
    tmp_path: Path,
    *,
    goals_dir: Path | None = None,
    interval_minutes: int = 1,
    agents=None,
) -> tuple[GoalsScheduler, Path, Path]:
    goals_dir = goals_dir or (tmp_path / "goals")
    goals_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = tmp_path / "prompts"
    prompt_path.mkdir(parents=True, exist_ok=True)
    app = _make_app_config(tmp_path, agents=agents)
    goals_cfg = GoalsConfig(path=goals_dir, interval_minutes=interval_minutes)
    stream = io.StringIO()
    sched = GoalsScheduler(goals_cfg, prompt_path, app, progress_stream=stream)
    return sched, goals_dir, prompt_path


# ---------------------------------------------------------------------------
# _model_flag_for
# ---------------------------------------------------------------------------


class TestModelFlagFor:
    def test_claude(self) -> None:
        assert _model_flag_for("claude") == "--model"

    def test_claude_code(self) -> None:
        assert _model_flag_for("claude-code") == "--model"

    def test_codex(self) -> None:
        assert _model_flag_for("codex") == "-m"

    def test_gemini(self) -> None:
        assert _model_flag_for("gemini") == "--model"

    def test_unknown(self) -> None:
        assert _model_flag_for("unknown-cli") is None


# ---------------------------------------------------------------------------
# _has_goal_files / _list_goal_files
# ---------------------------------------------------------------------------


class TestGoalFileListing:
    def test_empty_dir_has_no_goals(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        assert sched._has_goal_files() is False
        assert sched._list_goal_files() == []

    def test_md_file_detected(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        (goals_dir / "my-goal.md").write_text("goal", encoding="utf-8")
        assert sched._has_goal_files() is True
        assert len(sched._list_goal_files()) == 1

    def test_non_md_ignored(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        (goals_dir / "notes.txt").write_text("note", encoding="utf-8")
        assert sched._has_goal_files() is False

    def test_multiple_files_sorted(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        (goals_dir / "b.md").write_text("b", encoding="utf-8")
        (goals_dir / "a.md").write_text("a", encoding="utf-8")
        files = sched._list_goal_files()
        assert [f.name for f in files] == ["a.md", "b.md"]

    def test_nonexistent_dir_returns_false(self, tmp_path: Path) -> None:
        goals_dir = tmp_path / "no-such-dir"
        prompt_path = tmp_path / "prompts"
        prompt_path.mkdir()
        app = _make_app_config(tmp_path)
        cfg = GoalsConfig(path=goals_dir, interval_minutes=1)
        sched = GoalsScheduler(cfg, prompt_path, app)
        assert sched._has_goal_files() is False
        assert sched._list_goal_files() == []


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_goal_only(self) -> None:
        result = GoalsScheduler._build_prompt("do something", None, None)
        assert result == "# Goal\n\ndo something"

    def test_with_plan(self) -> None:
        result = GoalsScheduler._build_prompt("goal", "plan text", None)
        assert "## Plan" in result
        assert "plan text" in result

    def test_with_plan_and_design(self) -> None:
        result = GoalsScheduler._build_prompt("goal", "plan text", "design text")
        assert "## Plan" in result
        assert "## Design" in result
        assert "design text" in result

    def test_strips_whitespace(self) -> None:
        result = GoalsScheduler._build_prompt("  goal  ", "  plan  ", None)
        assert "# Goal\n\ngoal" in result
        assert "## Plan\n\nplan" in result


# ---------------------------------------------------------------------------
# Timer lifecycle
# ---------------------------------------------------------------------------


class TestTimerLifecycle:
    def test_no_timer_when_no_files(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path)
        sched._sync_timer()
        with sched._timer_lock:
            assert sched._timer is None

    def test_timer_created_when_files_exist(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        (goals_dir / "goal.md").write_text("content", encoding="utf-8")
        sched._sync_timer()
        with sched._timer_lock:
            assert sched._timer is not None
        sched._cancel_timer()

    def test_no_duplicate_timer_on_second_sync(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        (goals_dir / "goal.md").write_text("content", encoding="utf-8")
        sched._sync_timer()
        with sched._timer_lock:
            first_timer = sched._timer
        sched._sync_timer()
        with sched._timer_lock:
            assert sched._timer is first_timer  # same object, not re-created
        sched._cancel_timer()

    def test_timer_cancelled_when_files_removed(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        goal = goals_dir / "goal.md"
        goal.write_text("content", encoding="utf-8")
        sched._sync_timer()
        with sched._timer_lock:
            assert sched._timer is not None
        goal.unlink()
        sched._sync_timer()
        with sched._timer_lock:
            assert sched._timer is None

    def test_stop_cancels_timer(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        (goals_dir / "goal.md").write_text("content", encoding="utf-8")
        sched._sync_timer()
        sched.stop()
        with sched._timer_lock:
            assert sched._timer is None


# ---------------------------------------------------------------------------
# Prompt generation — _process_single_goal
# ---------------------------------------------------------------------------


class TestProcessSingleGoal:
    def test_generates_prompt_file(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path)
        goal = goals_dir / "my-feature.md"
        goal.write_text("Add a new feature", encoding="utf-8")

        with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260412"
            sched._process_single_goal(goal)

        generated = list(prompt_path.glob("*.md"))
        assert len(generated) == 1
        assert "my-feature" in generated[0].name
        content = generated[0].read_text(encoding="utf-8")
        assert "Add a new feature" in content

    def test_skips_if_prompt_already_exists(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path)
        goal = goals_dir / "my-feature.md"
        goal.write_text("goal", encoding="utf-8")
        existing = prompt_path / "20260412_my-feature.md"
        existing.write_text("already there", encoding="utf-8")

        with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260412"
            sched._process_single_goal(goal)

        # Should not have overwritten
        assert existing.read_text(encoding="utf-8") == "already there"
        assert len(list(prompt_path.glob("*.md"))) == 1

    def test_prompt_contains_goal_section(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path)
        goal = goals_dir / "alpha.md"
        goal.write_text("Improve performance", encoding="utf-8")

        with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260412"
            sched._process_single_goal(goal)

        content = (prompt_path / "20260412_alpha.md").read_text(encoding="utf-8")
        assert "# Goal" in content
        assert "Improve performance" in content


class TestProcessGoals:
    def test_all_goal_files_processed(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path)
        (goals_dir / "goal-a.md").write_text("A", encoding="utf-8")
        (goals_dir / "goal-b.md").write_text("B", encoding="utf-8")

        with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260412"
            sched._process_goals()

        generated = list(prompt_path.glob("*.md"))
        assert len(generated) == 2

    def test_stops_early_on_stop_event(self, tmp_path: Path) -> None:
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path)
        for i in range(5):
            (goals_dir / f"goal-{i}.md").write_text(f"G{i}", encoding="utf-8")

        sched._stop_event.set()

        with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260412"
            sched._process_goals()

        # None should be generated because stop_event was set
        assert list(prompt_path.glob("*.md")) == []


# ---------------------------------------------------------------------------
# _generate_prompt with agents
# ---------------------------------------------------------------------------


class TestGeneratePromptWithAgents:
    def test_no_agents_returns_goal_only_prompt(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents=None)
        result = sched._generate_prompt("my goal", "my-goal", "20260412")
        assert "# Goal" in result
        assert "## Plan" not in result

    def test_agents_with_no_resolvable_cli_returns_goal_only(
        self, tmp_path: Path
    ) -> None:
        from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig

        agents = AgentsConfig()  # all cli=None
        app = _make_app_config(tmp_path, agents=agents)
        app.active_agent_cli = None
        goals_cfg = GoalsConfig(path=tmp_path / "goals", interval_minutes=1)
        (tmp_path / "goals").mkdir()
        sched = GoalsScheduler(goals_cfg, tmp_path / "prompts", app)
        result = sched._generate_prompt("goal text", "stem", "20260412")
        assert "## Plan" not in result

    def test_planner_output_included_in_prompt(self, tmp_path: Path) -> None:
        from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig

        agents = AgentsConfig(planner=RoleAgentConfig(cli=Path("echo")))
        app = _make_app_config(tmp_path, agents=agents)
        app.active_agent_cli = None
        goals_cfg = GoalsConfig(path=tmp_path / "goals", interval_minutes=1)
        (tmp_path / "goals").mkdir()
        (tmp_path / ".dev").mkdir()
        sched = GoalsScheduler(goals_cfg, tmp_path / "prompts", app)

        # Mock _call_role_agent to return predictable text
        with patch.object(sched, "_call_role_agent", return_value="PLAN OUTPUT") as mock_call:
            result = sched._generate_prompt("my goal", "stem", "20260412")
            mock_call.assert_called_once()

        assert "## Plan" in result
        assert "PLAN OUTPUT" in result

    def test_architect_called_after_planner(self, tmp_path: Path) -> None:
        from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig

        agents = AgentsConfig(
            planner=RoleAgentConfig(cli=Path("echo")),
            architect=RoleAgentConfig(cli=Path("echo")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        app.active_agent_cli = None
        goals_cfg = GoalsConfig(path=tmp_path / "goals", interval_minutes=1)
        (tmp_path / "goals").mkdir()
        sched = GoalsScheduler(goals_cfg, tmp_path / "prompts", app)

        call_results = ["PLAN OUTPUT", "DESIGN OUTPUT"]

        def fake_call(**kwargs: object) -> str:
            return call_results.pop(0)

        with patch.object(sched, "_call_role_agent", side_effect=fake_call) as mock_call:
            result = sched._generate_prompt("my goal", "stem", "20260412")
            assert mock_call.call_count == 2

        assert "## Plan" in result
        assert "## Design" in result

    def test_architect_skipped_when_planner_returns_none(
        self, tmp_path: Path
    ) -> None:
        from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig

        agents = AgentsConfig(
            planner=RoleAgentConfig(cli=Path("echo")),
            architect=RoleAgentConfig(cli=Path("echo")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        app.active_agent_cli = None
        goals_cfg = GoalsConfig(path=tmp_path / "goals", interval_minutes=1)
        (tmp_path / "goals").mkdir()
        sched = GoalsScheduler(goals_cfg, tmp_path / "prompts", app)

        with patch.object(sched, "_call_role_agent", return_value=None) as mock_call:
            result = sched._generate_prompt("my goal", "stem", "20260412")
            # architect should not be called if planner returned None
            assert mock_call.call_count == 1

        assert "## Design" not in result


# ---------------------------------------------------------------------------
# trigger_now — immediate init run
# ---------------------------------------------------------------------------


class TestTriggerNow:
    def test_no_op_when_no_goal_files(self, tmp_path: Path) -> None:
        """trigger_now does nothing if the goals directory is empty."""
        sched, _, prompt_path = _make_scheduler(tmp_path)
        sched.trigger_now()
        assert list(prompt_path.glob("*.md")) == []
        with sched._timer_lock:
            assert sched._timer is None

    def test_processes_goals_immediately(self, tmp_path: Path) -> None:
        """trigger_now writes prompt files without waiting for the timer."""
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path)
        (goals_dir / "feature.md").write_text("Build something", encoding="utf-8")
        sched.trigger_now()
        assert len(list(prompt_path.glob("*.md"))) == 1

    def test_schedules_timer_after_processing(self, tmp_path: Path) -> None:
        """trigger_now arms the next timer once processing completes."""
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        (goals_dir / "feature.md").write_text("Build something", encoding="utf-8")
        sched.trigger_now()
        with sched._timer_lock:
            assert sched._timer is not None
        sched._cancel_timer()

    def test_cancels_pending_timer_before_processing(self, tmp_path: Path) -> None:
        """trigger_now resets any already-scheduled timer so the interval
        restarts from the end of this run, not from daemon startup."""
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        (goals_dir / "feature.md").write_text("Build something", encoding="utf-8")
        # Arm a timer to simulate what _watch_loop would do.
        sched._sync_timer()
        with sched._timer_lock:
            original_timer = sched._timer
        assert original_timer is not None

        sched.trigger_now()

        # A new timer should have been created (the old one was cancelled).
        with sched._timer_lock:
            assert sched._timer is not original_timer
        sched._cancel_timer()

    def test_no_op_when_stopped(self, tmp_path: Path) -> None:
        """trigger_now exits immediately if the scheduler has been stopped."""
        sched, goals_dir, prompt_path = _make_scheduler(tmp_path)
        (goals_dir / "feature.md").write_text("Build something", encoding="utf-8")
        sched.stop()
        sched.trigger_now()
        assert list(prompt_path.glob("*.md")) == []


# ---------------------------------------------------------------------------
# Start / stop (thread safety)
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_and_stop(self, tmp_path: Path) -> None:
        sched, goals_dir, _ = _make_scheduler(tmp_path)
        sched.start()
        time.sleep(0.05)
        sched.stop()
        assert sched._stop_event.is_set()

    def test_stop_without_start_is_safe(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path)
        sched.stop()  # should not raise

    def test_timer_fires_and_generates_prompt(self, tmp_path: Path) -> None:
        """End-to-end: timer fires quickly and writes a prompt file."""
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        prompt_path = tmp_path / "prompts"
        prompt_path.mkdir()
        app = _make_app_config(tmp_path)

        # Use a very short interval so the timer fires fast in the test.
        goals_cfg = GoalsConfig(path=goals_dir, interval_minutes=1)
        sched = GoalsScheduler(goals_cfg, prompt_path, app)

        (goals_dir / "quick.md").write_text("Quick goal", encoding="utf-8")

        generated: list[Path] = []

        def fake_on_timer_fired() -> None:
            with sched._timer_lock:
                sched._timer = None
            sched._process_goals()
            generated.extend(prompt_path.glob("*.md"))

        # Patch _schedule_timer_locked to fire immediately
        original_schedule = sched._schedule_timer_locked

        def immediate_schedule() -> None:
            timer = threading.Timer(0.01, sched._on_timer_fired)
            timer.daemon = True
            sched._timer = timer
            timer.start()

        with patch.object(sched, "_schedule_timer_locked", side_effect=immediate_schedule):
            sched._sync_timer()
            time.sleep(0.2)  # wait for timer to fire

        assert len(list(prompt_path.glob("*.md"))) >= 1
