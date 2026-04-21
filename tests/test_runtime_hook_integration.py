from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.agent.role_config import AgentsConfig
from dormammu.config import AppConfig
from dormammu.daemon.pipeline_runner import PipelineRunner
from dormammu.loop_runner import LoopRunRequest, LoopRunResult, LoopRunner
from dormammu.state import StateRepository


def _seed_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
    templates = root / "templates" / "dev"
    templates.mkdir(parents=True, exist_ok=True)
    (templates / "dashboard.md.tmpl").write_text(
        "\n".join(
            [
                "# DASHBOARD",
                "",
                "## Actual Progress",
                "",
                "- Goal: ${goal}",
                "- Prompt-driven scope: ${active_delivery_slice}",
                "- Active roadmap focus:",
                "${active_roadmap_focus}",
                "- Current workflow phase: ${active_phase}",
                "- Last completed workflow phase: ${last_completed_phase}",
                "- Supervisor verdict: `${supervisor_verdict}`",
                "- Escalation status: `${escalation_status}`",
                "- Resume point: ${resume_point}",
                "",
                "## In Progress",
                "",
                "${next_action}",
                "",
                "## Progress Notes",
                "",
                "${notes}",
                "",
                "## Risks And Watchpoints",
                "",
                "${risks_and_watchpoints}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (templates / "plan.md.tmpl").write_text(
        "\n".join(
            [
                "# PLAN",
                "",
                "## Prompt-Derived Implementation Plan",
                "",
                "${task_items}",
                "",
                "## Resume Checkpoint",
                "",
                "${resume_checkpoint}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (templates / "patterns.md.tmpl").write_text(
        "\n".join(
            [
                "# Codebase Patterns",
                "",
                "## Patterns",
                "",
                "(no patterns recorded yet)",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_loop_cli(root: Path, *, success_attempt: int = 1, name: str = "fake-loop-agent") -> Path:
    script = root / name
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            from pathlib import Path
            import json
            import os
            import sys

            ROOT = Path({str(root)!r})
            SUCCESS_ATTEMPT = {success_attempt}
            COUNTER_PATH = ROOT / ".attempt-count"
            TARGET_PATH = ROOT / "done.txt"
            BASE_DEV_DIR = Path(os.environ["DORMAMMU_BASE_DEV_DIR"])
            SESSION_PATH = BASE_DEV_DIR / "session.json"

            def mark_complete(path: Path) -> None:
                if not path.exists():
                    return
                lines = path.read_text(encoding="utf-8").splitlines()
                rewritten = [
                    line.replace("- [ ] ", "- [O] ") if line.startswith("- [ ] ") else line
                    for line in lines
                ]
                path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

            def mark_plan_complete() -> None:
                payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                session_id = payload.get("active_session_id") or payload.get("session_id")
                sessions_dir = Path(os.environ["DORMAMMU_SESSIONS_DIR"])
                mark_complete(sessions_dir / str(session_id) / "PLAN.md")
                mark_complete(sessions_dir / str(session_id) / "TASKS.md")

            def main() -> int:
                args = sys.argv[1:]
                if "--help" in args:
                    print("usage: fake-loop-agent [--prompt-file PATH]")
                    return 0

                attempt = 1
                if COUNTER_PATH.exists():
                    attempt = int(COUNTER_PATH.read_text(encoding="utf-8").strip()) + 1
                COUNTER_PATH.write_text(str(attempt), encoding="utf-8")

                if "--prompt-file" in args:
                    prompt_path = Path(args[args.index("--prompt-file") + 1])
                    print(prompt_path.read_text(encoding="utf-8").strip())

                if attempt >= SUCCESS_ATTEMPT:
                    TARGET_PATH.write_text("done\\n", encoding="utf-8")
                    mark_plan_complete()
                return 0

            raise SystemExit(main())
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_hook_script(root: Path) -> Path:
    script = root / "hook-handler.py"
    script.write_text(
        textwrap.dedent(
            """\
            #!__PYTHON__
            import json
            import sys

            payload = json.load(sys.stdin)
            mode = sys.argv[1]

            if mode == "allow":
                print(json.dumps({"action": "allow", "message": payload["event"]}))
            elif mode == "warn":
                print(json.dumps({"action": "warn", "message": "prompt warning"}))
            elif mode == "annotate-final":
                print(json.dumps({
                    "action": "annotate",
                    "message": "final verification annotated",
                    "annotations": {
                        "verdict": payload["payload"]["report"]["verdict"],
                    },
                }))
            elif mode == "annotate-stage-complete":
                print(json.dumps({
                    "action": "annotate",
                    "message": "stage completion annotated",
                    "annotations": {
                        "stage": payload["payload"]["stage_name"],
                        "status": payload["payload"].get("status"),
                        "verdict": payload["payload"].get("verdict"),
                    },
                }))
            elif mode == "deny-stage-start":
                print(json.dumps({"action": "deny", "message": "blocked stage start"}))
            elif mode == "deny-prompt-intake":
                print(json.dumps({"action": "deny", "message": "blocked prompt intake"}))
            elif mode == "deny-stage-complete":
                print(json.dumps({"action": "deny", "message": "blocked stage completion"}))
            elif mode == "deny-session-end":
                print(json.dumps({"action": "deny", "message": "blocked session end"}))
            elif mode == "annotate-plan-start":
                print(json.dumps({
                    "action": "annotate",
                    "message": "planner boundary annotated",
                    "annotations": {
                        "stem": payload["payload"]["stem"],
                    },
                }))
            else:
                raise SystemExit(f"unknown hook mode: {mode}")
            """
        ).replace("__PYTHON__", sys.executable),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _hook_payload(
    hook_script: Path,
    *,
    name: str,
    event: str,
    mode: str,
) -> dict[str, object]:
    return {
        "name": name,
        "event": event,
        "execution_mode": "sync",
        "enabled": True,
        "target": {
            "kind": "command",
            "ref": sys.executable,
            "settings": {
                "args": [str(hook_script), mode],
            },
        },
    }


def _load_config(root: Path) -> AppConfig:
    home_dir = root / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig.load(
        repo_root=root,
        env={
            "HOME": str(home_dir),
            **{key: value for key, value in os.environ.items() if key != "HOME"},
            "DORMAMMU_SESSIONS_DIR": str(root / "sessions"),
        },
    )


def _event_history(repository: StateRepository) -> list[dict[str, object]]:
    workflow_state = repository.read_workflow_state()
    hooks = workflow_state.get("hooks", {})
    history = hooks.get("history", [])
    assert isinstance(history, list)
    return history


def test_loop_runner_no_hooks_preserves_existing_behavior() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _seed_repo(root)
        cli = _write_loop_cli(root)
        config = _load_config(root)
        repository = StateRepository(config)

        result = LoopRunner(config, repository=repository).run(
            LoopRunRequest(
                cli_path=cli,
                prompt_text="Create the required marker file.",
                repo_root=root,
                run_label="no-hooks",
                max_retries=0,
                required_paths=("done.txt",),
                expected_roadmap_phase_id="phase_4",
            )
        )

        assert result.status == "completed"
        assert (root / "done.txt").exists()
        assert "hooks" not in repository.read_workflow_state()
        assert "hooks" not in repository.read_session_state()


def test_loop_runner_records_prompt_stage_final_and_completion_hook_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _seed_repo(root)
        cli = _write_loop_cli(root)
        hook_script = _write_hook_script(root)
        _write_json(
            root / "dormammu.json",
            {
                "hooks": [
                    _hook_payload(hook_script, name="prompt-warn", event="prompt intake", mode="warn"),
                    _hook_payload(hook_script, name="stage-start", event="stage start", mode="allow"),
                    _hook_payload(
                        hook_script,
                        name="final-annotate",
                        event="final verification",
                        mode="annotate-final",
                    ),
                _hook_payload(
                    hook_script,
                    name="stage-complete-annotate",
                    event="stage completion",
                    mode="annotate-stage-complete",
                ),
                _hook_payload(
                    hook_script,
                    name="session-end-allow",
                    event="session end",
                    mode="allow",
                ),
                ]
            },
        )
        config = _load_config(root)
        repository = StateRepository(config)

        result = LoopRunner(config, repository=repository).run(
            LoopRunRequest(
                cli_path=cli,
                prompt_text="Create the required marker file.",
                repo_root=root,
                run_label="diagnostics",
                max_retries=0,
                required_paths=("done.txt",),
                expected_roadmap_phase_id="phase_4",
            )
        )

        assert result.status == "completed"
        history = _event_history(repository)
        events = [item["event"] for item in history]
        assert "prompt intake" in events
        assert "stage_start" not in events
        assert "stage start" in events
        assert "final verification" in events
        assert "stage completion" in events
        assert "session end" in events

        prompt_record = next(item for item in history if item["event"] == "prompt intake")
        assert prompt_record["warnings"] == [
            {"hook": "prompt-warn", "message": "prompt warning", "metadata": {}}
        ]

        final_record = next(item for item in history if item["event"] == "final verification")
        assert final_record["annotations"] == [
            {
                "hook": "final-annotate",
                "annotations": {"verdict": "approved"},
                "message": "final verification annotated",
            }
        ]

        stage_complete_record = next(item for item in history if item["event"] == "stage completion")
        assert stage_complete_record["annotations"] == [
            {
                "hook": "stage-complete-annotate",
                "annotations": {
                    "stage": "developer",
                    "status": "completed",
                    "verdict": None,
                },
                "message": "stage completion annotated",
            }
        ]
        lifecycle_history = repository.read_session_state()["lifecycle"]["history"]
        loop_run_id = next(
            item["run_id"] for item in lifecycle_history if item["event_type"] == "run.requested"
        )
        assert {item["hook_input"]["run_id"] for item in history} == {loop_run_id}
        assert {
            item["run_id"]
            for item in lifecycle_history
            if item["event_type"].startswith("hook.execution")
        } == {loop_run_id}


def test_loop_runner_prompt_intake_hook_block_updates_terminal_lifecycle_event() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _seed_repo(root)
        cli = _write_loop_cli(root)
        hook_script = _write_hook_script(root)
        _write_json(
            root / "dormammu.json",
            {
                "hooks": [
                    _hook_payload(
                        hook_script,
                        name="deny-prompt-intake",
                        event="prompt intake",
                        mode="deny-prompt-intake",
                    ),
                    _hook_payload(
                        hook_script,
                        name="session-end-allow",
                        event="session end",
                        mode="allow",
                    ),
                ]
            },
        )
        config = _load_config(root)
        repository = StateRepository(config)

        result = LoopRunner(config, repository=repository).run(
            LoopRunRequest(
                cli_path=cli,
                prompt_text="Create the required marker file.",
                repo_root=root,
                run_label="deny-prompt-intake",
                max_retries=0,
                required_paths=("done.txt",),
                expected_roadmap_phase_id="phase_4",
            )
        )

        assert result.status == "blocked"
        assert not (root / ".attempt-count").exists()
        lifecycle = repository.read_session_state()["lifecycle"]
        assert lifecycle["latest_event"]["event_type"] == "run.finished"
        assert lifecycle["latest_event"]["status"] == "blocked"
        assert lifecycle["latest_event"]["payload"]["outcome"] == "blocked"
        assert lifecycle["latest_event"]["payload"]["error"] == "blocked prompt intake"


def test_loop_runner_blocks_before_agent_execution_when_stage_start_hook_denies() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _seed_repo(root)
        cli = _write_loop_cli(root)
        hook_script = _write_hook_script(root)
        _write_json(
            root / "dormammu.json",
            {
                "hooks": [
                    _hook_payload(
                        hook_script,
                        name="deny-stage-start",
                        event="stage start",
                        mode="deny-stage-start",
                    ),
                    _hook_payload(
                        hook_script,
                        name="session-end-allow",
                        event="session end",
                        mode="allow",
                    ),
                ]
            },
        )
        config = _load_config(root)
        repository = StateRepository(config)

        result = LoopRunner(config, repository=repository).run(
            LoopRunRequest(
                cli_path=cli,
                prompt_text="Create the required marker file.",
                repo_root=root,
                run_label="deny-stage-start",
                max_retries=0,
                required_paths=("done.txt",),
                expected_roadmap_phase_id="phase_4",
            )
        )

        assert result.status == "blocked"
        assert result.attempts_completed == 0
        assert not (root / ".attempt-count").exists()
        history = _event_history(repository)
        assert [item["event"] for item in history] == ["stage start", "session end"]
        assert history[0]["blocked"] is True
        assert history[-1]["blocked"] is False
        latest_event = repository.read_workflow_state()["hooks"]["latest_event"]
        assert latest_event["event"] == "session end"
        lifecycle = repository.read_session_state()["lifecycle"]
        assert lifecycle["latest_event"]["event_type"] == "run.finished"
        assert lifecycle["latest_event"]["status"] == "blocked"
        assert lifecycle["latest_event"]["payload"]["outcome"] == "blocked"
        assert lifecycle["latest_event"]["payload"]["error"] == "blocked stage start"


def test_loop_runner_emits_session_end_when_stage_completion_hook_denies() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _seed_repo(root)
        cli = _write_loop_cli(root)
        hook_script = _write_hook_script(root)
        _write_json(
            root / "dormammu.json",
            {
                "hooks": [
                    _hook_payload(
                        hook_script,
                        name="deny-stage-complete",
                        event="stage completion",
                        mode="deny-stage-complete",
                    ),
                    _hook_payload(
                        hook_script,
                        name="session-end-allow",
                        event="session end",
                        mode="allow",
                    ),
                ]
            },
        )
        config = _load_config(root)
        repository = StateRepository(config)

        result = LoopRunner(config, repository=repository).run(
            LoopRunRequest(
                cli_path=cli,
                prompt_text="Create the required marker file.",
                repo_root=root,
                run_label="deny-stage-complete",
                max_retries=0,
                required_paths=("done.txt",),
                expected_roadmap_phase_id="phase_4",
            )
        )

        assert result.status == "blocked"
        assert (root / "done.txt").exists()
        history = _event_history(repository)
        assert [item["event"] for item in history][-2:] == [
            "stage completion",
            "session end",
        ]
        assert history[-2]["blocked"] is True
        assert history[-1]["blocked"] is False
        lifecycle = repository.read_session_state()["lifecycle"]
        assert lifecycle["latest_event"]["event_type"] == "run.finished"
        assert lifecycle["latest_event"]["status"] == "blocked"
        assert lifecycle["latest_event"]["payload"]["outcome"] == "blocked"
        assert lifecycle["latest_event"]["payload"]["error"] == "blocked stage completion"
        stage_failed = next(
            item for item in lifecycle["history"] if item["event_type"] == "stage.failed"
        )
        assert stage_failed["payload"]["error"] == "blocked stage completion"


def test_pipeline_runner_prompt_intake_hook_does_not_crash_without_active_session(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _seed_repo(root)
    hook_script = _write_hook_script(root)
    _write_json(
        root / "dormammu.json",
        {
            "active_agent_cli": sys.executable,
            "hooks": [
                _hook_payload(
                    hook_script,
                    name="prompt-allow",
                    event="prompt intake",
                    mode="allow",
                )
            ],
        },
    )
    config = _load_config(root)
    repository = StateRepository(config)
    runner = PipelineRunner(
        config,
        config.agents or AgentsConfig(),
        repository=repository,
        progress_stream=io.StringIO(),
    )

    with (
        patch.object(runner, "run_refine_and_plan"),
        patch.object(
            runner,
            "_run_developer",
            return_value=LoopRunResult(
                status="completed",
                attempts_completed=1,
                retries_used=0,
                max_retries=0,
                max_iterations=1,
                latest_run_id=None,
                supervisor_verdict="approved",
                report_path=None,
                continuation_prompt_path=None,
            ),
        ),
        patch.object(runner, "_run_tester", return_value=None),
        patch.object(runner, "_run_reviewer", return_value=None),
        patch.object(runner, "_run_committer"),
    ):
        result = runner.run(
            "Plan the runtime hook integration.",
            stem="runtime-hooks",
            date_str="20260421",
        )

    assert result.status == "completed"
    assert repository._session_mgr.read_active_session_id() is None


def test_pipeline_runner_session_end_uses_bootstrapped_session_id(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _seed_repo(root)
    hook_script = _write_hook_script(root)
    _write_json(
        root / "dormammu.json",
        {
            "active_agent_cli": sys.executable,
            "hooks": [
                _hook_payload(
                    hook_script,
                    name="session-end-allow",
                    event="session end",
                    mode="allow",
                )
            ],
        },
    )
    config = _load_config(root)
    repository = StateRepository(config)
    runner = PipelineRunner(
        config,
        config.agents or AgentsConfig(),
        repository=repository,
        progress_stream=io.StringIO(),
    )

    def _bootstrap_session_during_developer_run(
        prompt_text: str,
        *,
        stem: str,
    ) -> LoopRunResult:
        repository.ensure_bootstrap_state(
            goal="Runtime hook integration",
            prompt_text=prompt_text,
            active_roadmap_phase_ids=["phase_4"],
        )
        return LoopRunResult(
            status="completed",
            attempts_completed=1,
            retries_used=0,
            max_retries=0,
            max_iterations=1,
            latest_run_id=None,
            supervisor_verdict="approved",
            report_path=None,
            continuation_prompt_path=None,
        )

    with (
        patch.object(runner, "run_refine_and_plan"),
        patch.object(
            runner,
            "_run_developer",
            side_effect=_bootstrap_session_during_developer_run,
        ),
        patch.object(runner, "_run_tester", return_value=None),
        patch.object(runner, "_run_reviewer", return_value=None),
        patch.object(runner, "_run_committer"),
    ):
        result = runner.run(
            "Plan the runtime hook integration.",
            stem="runtime-hooks",
            date_str="20260421",
        )

    assert result.status == "completed"
    session_id = repository._session_mgr.read_active_session_id()
    assert session_id is not None
    history = _event_history(repository)
    assert [item["event"] for item in history] == ["session end"]
    assert history[-1]["hook_input"]["session_id"] == session_id
    assert history[-1]["hook_input"]["subject"]["id"] == session_id
    assert history[-1]["subject"]["id"] == session_id


def test_pipeline_runner_emits_session_end_when_prompt_intake_hook_denies(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _seed_repo(root)
    hook_script = _write_hook_script(root)
    _write_json(
        root / "dormammu.json",
        {
            "active_agent_cli": sys.executable,
            "hooks": [
                _hook_payload(
                    hook_script,
                    name="deny-prompt-intake",
                    event="prompt intake",
                    mode="deny-prompt-intake",
                ),
                _hook_payload(
                    hook_script,
                    name="session-end-allow",
                    event="session end",
                    mode="allow",
                ),
            ],
        },
    )
    config = _load_config(root)
    repository = StateRepository(config)
    repository.ensure_bootstrap_state(
        goal="Prompt intake session-end test",
        prompt_text="Plan the runtime hook integration.",
        active_roadmap_phase_ids=["phase_4"],
    )
    runner = PipelineRunner(
        config,
        config.agents or AgentsConfig(),
        repository=repository,
        progress_stream=io.StringIO(),
    )

    result = runner.run(
        "Plan the runtime hook integration.",
        stem="runtime-hooks",
        date_str="20260421",
    )

    assert result.status == "blocked"
    history = _event_history(repository)
    assert [item["event"] for item in history][-2:] == [
        "prompt intake",
        "session end",
    ]
    assert history[-2]["blocked"] is True
    assert history[-1]["blocked"] is False


def test_pipeline_runner_hook_events_share_pipeline_execution_run_id(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _seed_repo(root)
    hook_script = _write_hook_script(root)
    _write_json(
        root / "dormammu.json",
        {
            "active_agent_cli": sys.executable,
            "hooks": [
                _hook_payload(
                    hook_script,
                    name="prompt-allow",
                    event="prompt intake",
                    mode="allow",
                ),
                _hook_payload(
                    hook_script,
                    name="plan-start",
                    event="plan start",
                    mode="annotate-plan-start",
                ),
                _hook_payload(
                    hook_script,
                    name="stage-start-allow",
                    event="stage start",
                    mode="allow",
                ),
                _hook_payload(
                    hook_script,
                    name="stage-complete-allow",
                    event="stage completion",
                    mode="allow",
                ),
                _hook_payload(
                    hook_script,
                    name="session-end-allow",
                    event="session end",
                    mode="allow",
                ),
            ],
        },
    )
    config = _load_config(root)
    repository = StateRepository(config)
    repository.ensure_bootstrap_state(
        goal="Pipeline run-id integration test",
        prompt_text="Plan the runtime hook integration.",
        active_roadmap_phase_ids=["phase_4"],
    )
    runner = PipelineRunner(
        config,
        config.agents or AgentsConfig(),
        repository=repository,
        progress_stream=io.StringIO(),
    )

    def _run_refine_and_plan(
        prompt_text: str,
        *,
        stem: str,
        date_str: str,
        enable_plan_evaluator: bool = False,
    ) -> None:
        assert enable_plan_evaluator is False
        runner._run_refiner(prompt_text, stem=stem, date_str=date_str)
        runner._run_planner(prompt_text, stem=stem, date_str=date_str)

    def _run_developer(prompt_text: str, *, stem: str) -> LoopRunResult:
        runner._emit_stage_queued(role="developer", reason="Developer stage is queued.")
        runner._emit_stage_start(role="developer")
        result = LoopRunResult(
            status="completed",
            attempts_completed=1,
            retries_used=0,
            max_retries=0,
            max_iterations=1,
            latest_run_id="agent-run-1",
            supervisor_verdict="approved",
            report_path=None,
            continuation_prompt_path=None,
        )
        runner._emit_stage_complete(
            role="developer",
            verdict=result.status,
            run_id=result.latest_run_id,
            payload={
                "status": result.status,
                "attempts_completed": result.attempts_completed,
                "retries_used": result.retries_used,
                "supervisor_verdict": result.supervisor_verdict,
            },
        )
        return result

    with (
        patch.object(runner, "_call_once", return_value="ok"),
        patch.object(runner, "run_refine_and_plan", side_effect=_run_refine_and_plan),
        patch.object(runner, "_run_developer", side_effect=_run_developer),
        patch.object(runner, "_run_tester", return_value=None),
        patch.object(runner, "_run_reviewer", return_value=None),
        patch.object(runner, "_run_committer"),
    ):
        result = runner.run(
            "Plan the runtime hook integration.",
            stem="runtime-hooks",
            date_str="20260421",
        )

    assert result.status == "completed"
    history = _event_history(repository)
    pipeline_run_id = next(
        item["run_id"]
        for item in repository.read_session_state()["lifecycle"]["history"]
        if item["event_type"] == "run.requested" and item["role"] == "pipeline"
    )
    assert {
        item["event"]
        for item in history
    } >= {"prompt intake", "plan start", "stage start", "stage completion", "session end"}
    assert {item["hook_input"]["run_id"] for item in history} == {pipeline_run_id}
    assert {
        item["run_id"]
        for item in repository.read_session_state()["lifecycle"]["history"]
        if item["event_type"].startswith("hook.execution")
    } == {pipeline_run_id}


def test_pipeline_runner_session_end_hook_block_updates_terminal_lifecycle_event(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _seed_repo(root)
    hook_script = _write_hook_script(root)
    _write_json(
        root / "dormammu.json",
        {
            "active_agent_cli": sys.executable,
            "hooks": [
                _hook_payload(
                    hook_script,
                    name="deny-session-end",
                    event="session end",
                    mode="deny-session-end",
                )
            ],
        },
    )
    config = _load_config(root)
    repository = StateRepository(config)
    repository.ensure_bootstrap_state(
        goal="Pipeline session-end lifecycle test",
        prompt_text="Plan the runtime hook integration.",
        active_roadmap_phase_ids=["phase_4"],
    )
    runner = PipelineRunner(
        config,
        config.agents or AgentsConfig(),
        repository=repository,
        progress_stream=io.StringIO(),
    )

    def _bootstrap_session_during_developer_run(
        prompt_text: str,
        *,
        stem: str,
    ) -> LoopRunResult:
        repository.ensure_bootstrap_state(
            goal="Runtime hook integration",
            prompt_text=prompt_text,
            active_roadmap_phase_ids=["phase_4"],
        )
        return LoopRunResult(
            status="completed",
            attempts_completed=1,
            retries_used=0,
            max_retries=0,
            max_iterations=1,
            latest_run_id=None,
            supervisor_verdict="approved",
            report_path=None,
            continuation_prompt_path=None,
        )

    with (
        patch.object(runner, "run_refine_and_plan"),
        patch.object(
            runner,
            "_run_developer",
            side_effect=_bootstrap_session_during_developer_run,
        ),
        patch.object(runner, "_run_tester", return_value=None),
        patch.object(runner, "_run_reviewer", return_value=None),
        patch.object(runner, "_run_committer"),
    ):
        result = runner.run(
            "Plan the runtime hook integration.",
            stem="runtime-hooks",
            date_str="20260421",
        )

    assert result.status == "blocked"
    lifecycle = repository.read_session_state()["lifecycle"]
    assert lifecycle["latest_event"]["event_type"] == "run.finished"
    assert lifecycle["latest_event"]["status"] == "blocked"
    assert lifecycle["latest_event"]["payload"]["outcome"] == "blocked"
    assert lifecycle["latest_event"]["payload"]["error"] == "blocked session end"


def test_loop_runner_session_end_hook_can_block_successful_completion() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _seed_repo(root)
        cli = _write_loop_cli(root)
        hook_script = _write_hook_script(root)
        _write_json(
            root / "dormammu.json",
            {
                "hooks": [
                    _hook_payload(
                        hook_script,
                        name="deny-session-end",
                        event="session end",
                        mode="deny-session-end",
                    )
                ]
            },
        )
        config = _load_config(root)
        repository = StateRepository(config)

        result = LoopRunner(config, repository=repository).run(
            LoopRunRequest(
                cli_path=cli,
                prompt_text="Create the required marker file.",
                repo_root=root,
                run_label="deny-session-end",
                max_retries=0,
                required_paths=("done.txt",),
                expected_roadmap_phase_id="phase_4",
            )
        )

        assert result.status == "blocked"
        assert (root / "done.txt").exists()
        workflow_state = repository.read_workflow_state()
        assert workflow_state["loop"]["status"] == "blocked"
        assert workflow_state["hooks"]["latest_event"]["event"] == "session end"
        assert workflow_state["hooks"]["latest_event"]["blocked"] is True
        lifecycle = repository.read_session_state()["lifecycle"]
        assert lifecycle["latest_event"]["event_type"] == "run.finished"
        assert lifecycle["latest_event"]["status"] == "blocked"
        assert lifecycle["latest_event"]["payload"]["outcome"] == "blocked"
        assert lifecycle["latest_event"]["payload"]["error"] == "blocked session end"


def test_pipeline_runner_emits_plan_start_hook_at_planner_boundary(tmp_path: Path) -> None:
    root = tmp_path
    _seed_repo(root)
    hook_script = _write_hook_script(root)
    _write_json(
        root / "dormammu.json",
        {
            "active_agent_cli": sys.executable,
            "hooks": [
                _hook_payload(
                    hook_script,
                    name="plan-start",
                    event="plan start",
                    mode="annotate-plan-start",
                )
            ],
        },
    )
    config = _load_config(root)
    repository = StateRepository(config)
    repository.ensure_bootstrap_state(
        goal="Plan start test",
        prompt_text="Plan the runtime hook integration.",
        active_roadmap_phase_ids=["phase_4"],
    )
    runner = PipelineRunner(
        config,
        config.agents or AgentsConfig(),
        repository=repository,
        progress_stream=io.StringIO(),
    )

    with patch.object(runner, "_call_once", return_value="planner output"):
        output = runner._run_planner(
            "Plan the runtime hook integration.",
            stem="runtime-hooks",
            date_str="20260421",
        )

    assert output == "planner output"
    history = _event_history(repository)
    plan_start_record = next(item for item in history if item["event"] == "plan start")
    assert plan_start_record["annotations"] == [
        {
            "hook": "plan-start",
            "annotations": {"stem": "runtime-hooks"},
            "message": "planner boundary annotated",
        }
    ]
