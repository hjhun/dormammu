"""Unit and integration tests for GoalsScheduler."""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import threading
import time
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dormammu.agent.profiles import resolve_agent_profile
from dormammu.config import AppConfig
from dormammu.daemon.cli_output import model_args
from dormammu.daemon.goals_config import GoalsConfig
from dormammu.daemon.goals_scheduler import GoalsScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_config(tmp_path: Path, *, agents=None) -> Any:
    mock = MagicMock()
    mock.repo_root = tmp_path
    mock.base_dev_dir = tmp_path / ".dev"
    mock.active_agent_cli = None
    mock.typescript_agent_runner_cli = None
    mock.agents = agents
    mock.resolve_agent_profile.side_effect = lambda role: resolve_agent_profile(
        role,
        agents_config=agents,
    )
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


def _write_fake_typescript_runner(root: Path) -> Path:
    script = root / "ts-runner"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import base64
            from datetime import datetime, timezone
            import json
            from pathlib import Path
            import sys

            payload = json.loads(sys.stdin.read())
            (Path({str(root)!r}) / "captured-runner-payload.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\\n",
                encoding="utf-8",
            )
            if payload.get("entrypoint") == "goals_queue":
                goals_path = Path(payload["goals_path"])
                prompt_path = Path(payload["prompt_path"])
                date_text = payload["date_text"]
                goal_files = []
                candidates = []
                queued_names = {{
                    item.name
                    for item in prompt_path.iterdir()
                    if item.is_file()
                }} if prompt_path.exists() else set()
                for goal_file in sorted(
                    item for item in goals_path.iterdir()
                    if item.is_file() and item.suffix == ".md"
                ):
                    queued_name = f"{{date_text}}_{{goal_file.stem}}.md"
                    entry = {{
                        "path": str(goal_file),
                        "name": goal_file.name,
                        "stem": goal_file.stem,
                    }}
                    goal_files.append(entry)
                    candidates.append({{
                        **entry,
                        "queuedPromptName": queued_name,
                        "alreadyQueued": queued_name in queued_names,
                    }})
                print(json.dumps({{
                    "entrypoint": "goals_queue",
                    "goal_files": goal_files,
                    "candidates": candidates,
                }}, ensure_ascii=True))
                raise SystemExit(0)
            if payload.get("entrypoint") == "goals_prompt_projection":
                goal_file = Path(payload["goal_file_path"])
                print(json.dumps({{
                    "entrypoint": "goals_prompt_projection",
                    "stem": goal_file.stem,
                    "filename": f"{{payload['date_text']}}_{{goal_file.stem}}.md",
                    "content": (
                        f"<!-- dormammu:goal_source={{goal_file}} -->\\n\\n"
                        f"TS_PROJECTED\\n{{payload['generated_prompt']}}"
                    ),
                }}, ensure_ascii=True))
                raise SystemExit(0)
            request = payload["request"]
            logs_dir = Path(payload["logs_dir"])
            logs_dir.mkdir(parents=True, exist_ok=True)
            run_id = "typescript-goals-" + str(request.get("run_label") or "role")
            started_at = datetime.now(timezone.utc).isoformat()
            prompt_path = logs_dir / f"{{run_id}}.prompt.txt"
            stdout_path = logs_dir / f"{{run_id}}.stdout.txt"
            stderr_path = logs_dir / f"{{run_id}}.stderr.txt"
            metadata_path = logs_dir / f"{{run_id}}.metadata.json"
            prompt_path.write_text(request["prompt_text"], encoding="utf-8")
            stdout_path.write_text("GOALS_TS_OUTPUT\\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            capabilities = {{
                "help_flag": "--help",
                "prompt_file_flag": "--prompt-file",
                "prompt_arg_flag": None,
                "workdir_flag": None,
                "help_text": "usage: ts-runner",
                "help_exit_code": 0,
                "command_prefix": [],
                "prompt_positional": False,
                "preset": None,
                "auto_approve": {{
                    "supported": False,
                    "requires_confirmation": False,
                    "candidates": [],
                    "notes": [],
                }},
            }}
            base = {{
                "run_id": run_id,
                "cli_path": request["cli_path"],
                "workdir": request.get("workdir") or request["repo_root"],
                "prompt_mode": "file",
                "command": [request["cli_path"], "--typescript-runner"],
                "started_at": started_at,
                "artifacts": {{
                    "prompt": str(prompt_path),
                    "stdout": str(stdout_path),
                    "stderr": str(stderr_path),
                    "metadata": str(metadata_path),
                }},
                "capabilities": capabilities,
            }}
            if payload.get("event_stream"):
                print(
                    "DORMAMMU_EVENT " + json.dumps({{"type": "started", "started": base}}),
                    file=sys.stderr,
                    flush=True,
                )
                print(
                    "DORMAMMU_EVENT "
                    + json.dumps({{
                        "type": "output",
                        "data": base64.b64encode(b"GOALS_TS_OUTPUT\\n").decode("ascii"),
                    }}),
                    file=sys.stderr,
                    flush=True,
                )
            result = dict(base)
            result.update(
                {{
                    "exit_code": 0,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "requested_cli_path": request["cli_path"],
                    "attempted_cli_paths": [request["cli_path"]],
                    "fallback_trigger": None,
                    "timed_out": False,
                }}
            )
            metadata_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=True) + "\\n",
                encoding="utf-8",
            )
            print(json.dumps(result, ensure_ascii=True))
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


# ---------------------------------------------------------------------------
# model_args (shared flag helper, formerly _model_flag_for in goals_scheduler)
# ---------------------------------------------------------------------------


class TestModelArgs:
    def test_claude_flag(self) -> None:
        assert model_args("claude", "m") == ["--model", "m"]

    def test_claude_code_flag(self) -> None:
        assert model_args("claude-code", "m") == ["--model", "m"]

    def test_codex_flag(self) -> None:
        assert model_args("codex", "m") == ["-m", "m"]

    def test_gemini_flag(self) -> None:
        assert model_args("gemini", "m") == ["--model", "m"]

    def test_unknown_returns_empty(self) -> None:
        assert model_args("unknown-cli", "m") == []

    def test_none_model_returns_empty(self) -> None:
        assert model_args("claude", None) == []


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

    def test_list_goal_files_can_use_typescript_runner_bridge(
        self, tmp_path: Path
    ) -> None:
        runner_cli = _write_fake_typescript_runner(tmp_path)
        (tmp_path / "dormammu.json").write_text(
            json.dumps({"typescript_agent_runner_cli": str(runner_cli)}),
            encoding="utf-8",
        )
        home = tmp_path / "home"
        home.mkdir()
        app = AppConfig.load(
            repo_root=tmp_path,
            env={
                **os.environ,
                "HOME": str(home),
                "DORMAMMU_SESSIONS_DIR": str(tmp_path / "sessions"),
            },
        )
        goals_dir = tmp_path / "goals"
        prompt_path = tmp_path / "prompts"
        goals_dir.mkdir()
        prompt_path.mkdir()
        (goals_dir / "b.md").write_text("b", encoding="utf-8")
        (goals_dir / "a.md").write_text("a", encoding="utf-8")
        (goals_dir / "ignore.txt").write_text("ignore", encoding="utf-8")
        (prompt_path / "20260412_a.md").write_text("queued", encoding="utf-8")
        sched = GoalsScheduler(
            GoalsConfig(path=goals_dir, interval_minutes=1),
            prompt_path,
            app,
        )

        files = sched._list_goal_files()

        assert [file.name for file in files] == ["a.md", "b.md"]
        captured = json.loads(
            (tmp_path / "captured-runner-payload.json").read_text(encoding="utf-8")
        )
        assert captured["entrypoint"] == "goals_queue"
        assert captured["goals_path"] == str(goals_dir)
        assert captured["prompt_path"] == str(prompt_path)


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_goal_only(self) -> None:
        result = GoalsScheduler._build_prompt("do something", None, None, None)
        assert "# Goal" in result
        assert "do something" in result

    def test_language_notice_always_present(self) -> None:
        for analysis, plan, design in [
            (None, None, None),
            ("a", "p", None),
            ("a", "p", "d"),
        ]:
            result = GoalsScheduler._build_prompt("goal", analysis, plan, design)
            assert "Language requirement" in result
            assert "English" in result

    def test_language_notice_appears_before_goal(self) -> None:
        result = GoalsScheduler._build_prompt("goal text", None, None, None)
        assert result.index("Language requirement") < result.index("# Goal")

    def test_workflow_contract_always_present(self) -> None:
        result = GoalsScheduler._build_prompt("goal", None, None, None)
        assert "Workflow Contract" in result
        assert "refine -> plan" in result

    def test_with_analysis(self) -> None:
        result = GoalsScheduler._build_prompt("goal", "analysis text", None, None)
        assert "## Requirements Analysis" in result
        assert "analysis text" in result

    def test_with_plan(self) -> None:
        result = GoalsScheduler._build_prompt("goal", None, "plan text", None)
        assert "## Plan" in result
        assert "plan text" in result

    def test_with_plan_and_design(self) -> None:
        result = GoalsScheduler._build_prompt(
            "goal",
            "analysis text",
            "plan text",
            "design text",
        )
        assert "## Requirements Analysis" in result
        assert "## Plan" in result
        assert "## Design" in result
        assert "design text" in result

    def test_strips_whitespace(self) -> None:
        result = GoalsScheduler._build_prompt("  goal  ", "  analysis  ", "  plan  ", None)
        assert "# Goal\n\ngoal" in result
        assert "## Requirements Analysis\n\nanalysis" in result
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

    def test_prompt_write_can_use_typescript_projection_bridge(
        self, tmp_path: Path
    ) -> None:
        runner_cli = _write_fake_typescript_runner(tmp_path)
        (tmp_path / "dormammu.json").write_text(
            json.dumps({"typescript_agent_runner_cli": str(runner_cli)}),
            encoding="utf-8",
        )
        home = tmp_path / "home"
        home.mkdir()
        app = AppConfig.load(
            repo_root=tmp_path,
            env={
                **os.environ,
                "HOME": str(home),
                "DORMAMMU_SESSIONS_DIR": str(tmp_path / "sessions"),
            },
        )
        goals_dir = tmp_path / "goals"
        prompt_path = tmp_path / "prompts"
        goals_dir.mkdir()
        prompt_path.mkdir()
        goal = goals_dir / "alpha.md"
        goal.write_text("Improve performance", encoding="utf-8")
        sched = GoalsScheduler(
            GoalsConfig(path=goals_dir, interval_minutes=1),
            prompt_path,
            app,
        )

        with patch("dormammu.daemon.goals_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "20260412"
            sched._process_single_goal(goal)

        content = (prompt_path / "20260412_alpha.md").read_text(encoding="utf-8")
        assert "TS_PROJECTED" in content
        assert "Improve performance" in content
        captured = json.loads(
            (tmp_path / "captured-runner-payload.json").read_text(encoding="utf-8")
        )
        assert captured["entrypoint"] == "goals_prompt_projection"
        assert captured["goal_file_path"] == str(goal.resolve())


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
    def test_call_role_agent_uses_configured_typescript_runner_bridge(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "AGENTS.md").write_text("goals test\n", encoding="utf-8")
        runner_cli = _write_fake_typescript_runner(tmp_path)
        (tmp_path / "dormammu.json").write_text(
            json.dumps({"typescript_agent_runner_cli": str(runner_cli)}),
            encoding="utf-8",
        )
        home = tmp_path / "home"
        home.mkdir()
        app = AppConfig.load(
            repo_root=tmp_path,
            env={
                **os.environ,
                "HOME": str(home),
                "DORMAMMU_SESSIONS_DIR": str(tmp_path / "sessions"),
            },
        )
        goals_dir = tmp_path / "goals"
        goals_dir.mkdir()
        progress = io.StringIO()
        sched = GoalsScheduler(
            GoalsConfig(path=goals_dir, interval_minutes=1),
            tmp_path / "prompts",
            app,
            progress_stream=progress,
        )

        output = sched._call_role_agent(
            role="planner",
            cli=Path("goals-agent"),
            model=None,
            prompt="goals prompt",
            stem="goal-stem",
            date_str="20260412",
        )

        assert output == "GOALS_TS_OUTPUT\n"
        log_text = progress.getvalue()
        assert "goals scheduler: [planner] stdout:" in log_text
        assert "GOALS_TS_OUTPUT" in log_text
        captured = json.loads(
            (tmp_path / "captured-runner-payload.json").read_text(encoding="utf-8")
        )
        assert captured["event_stream"] is True
        assert captured["request"]["cli_path"] == "goals-agent"
        assert captured["request"]["prompt_text"] == "goals prompt"

    def test_no_agents_returns_goal_only_prompt(self, tmp_path: Path) -> None:
        sched, _, _ = _make_scheduler(tmp_path, agents=None)
        result = sched._generate_prompt("my goal", "my-goal", "20260412")
        assert "# Goal" in result
        assert "Workflow Contract" in result
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

    def test_analyzer_output_included_before_plan(self, tmp_path: Path) -> None:
        from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig

        agents = AgentsConfig(
            analyzer=RoleAgentConfig(cli=Path("echo")),
            planner=RoleAgentConfig(cli=Path("echo")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        app.active_agent_cli = None
        goals_cfg = GoalsConfig(path=tmp_path / "goals", interval_minutes=1)
        (tmp_path / "goals").mkdir()
        sched = GoalsScheduler(goals_cfg, tmp_path / "prompts", app)

        call_results = ["ANALYSIS OUTPUT", "PLAN OUTPUT"]

        def fake_call(**kwargs: object) -> str:
            return call_results.pop(0)

        with patch.object(sched, "_call_role_agent", side_effect=fake_call) as mock_call:
            result = sched._generate_prompt("my goal", "stem", "20260412")
            assert mock_call.call_count == 2

        assert result.index("## Requirements Analysis") < result.index("## Plan")
        assert "ANALYSIS OUTPUT" in result
        assert "PLAN OUTPUT" in result

    def test_designer_called_after_planner(self, tmp_path: Path) -> None:
        from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig

        agents = AgentsConfig(
            planner=RoleAgentConfig(cli=Path("echo")),
            designer=RoleAgentConfig(cli=Path("echo")),
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

    def test_designer_skipped_when_planner_returns_none(
        self, tmp_path: Path
    ) -> None:
        from dormammu.agent.role_config import AgentsConfig, RoleAgentConfig

        agents = AgentsConfig(
            planner=RoleAgentConfig(cli=Path("echo")),
            designer=RoleAgentConfig(cli=Path("echo")),
        )
        app = _make_app_config(tmp_path, agents=agents)
        app.active_agent_cli = None
        goals_cfg = GoalsConfig(path=tmp_path / "goals", interval_minutes=1)
        (tmp_path / "goals").mkdir()
        sched = GoalsScheduler(goals_cfg, tmp_path / "prompts", app)

        with patch.object(sched, "_call_role_agent", return_value=None) as mock_call:
            result = sched._generate_prompt("my goal", "stem", "20260412")
            # designer should not be called if planner returned None
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
