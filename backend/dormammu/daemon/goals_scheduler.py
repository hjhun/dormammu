"""GoalsScheduler — background thread that watches a goals directory and
periodically generates analysis+plan+design prompts for the daemon queue.

Thread safety
-------------
- ``_timer`` and ``_timer_active`` are guarded by ``_timer_lock``.
- ``_goals_config.path`` is read-only after construction.
- The only shared state with ``DaemonRunner`` is the ``prompt_path``
  directory, which is accessed via atomic file-system writes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from dormammu.agent import CliAdapter
from dormammu.agent.models import AgentRunRequest
from dormammu.daemon.cli_output import model_args, select_agent_output

if TYPE_CHECKING:
    from dormammu.config import AppConfig
    from dormammu.daemon.goals_config import GoalsConfig

_WATCHER_POLL_SECONDS = 30


class GoalsScheduler:
    """Monitors a goals directory and generates analysis+plan+design prompts on a timer.

    Lifecycle
    ---------
    1. ``start()`` — spawns the watcher thread (daemon=True).
    2. Watcher polls ``goals.path`` every ``_WATCHER_POLL_SECONDS`` seconds.
    3. If goal files exist and no timer is running, schedules one.
    4. If goal files are all gone, cancels any pending timer.
    5. When the timer fires, processes every ``.md`` in ``goals.path``
       and writes generated prompts to ``prompt_path``.
    6. ``stop()`` — signals the watcher thread to exit and cancels any timer.
    """

    def __init__(
        self,
        goals_config: GoalsConfig,
        prompt_path: Path,
        app_config: AppConfig,
        *,
        progress_stream: TextIO | None = None,
    ) -> None:
        self._goals_config = goals_config
        self._prompt_path = prompt_path
        self._app_config = app_config
        self._progress_stream = progress_stream or sys.stderr

        self._timer_lock = threading.Lock()
        self._timer: threading.Timer | None = None

        self._stop_event = threading.Event()
        self._watcher_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background watcher thread."""
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="dormammu-goals-watcher",
        )
        self._watcher_thread.start()

    def stop(self) -> None:
        """Signal the watcher to exit and cancel any pending timer."""
        self._stop_event.set()
        self._cancel_timer()

    def trigger_now(self) -> None:
        """Immediately process goal files and schedule the next timer run.

        Call this on daemon initialisation when goal files are already
        present so that the first run happens right away rather than
        waiting for the first timer interval to elapse. Any previously
        scheduled timer is cancelled first so that the next interval is
        measured from *this* run, not from when the daemon started.

        This runs synchronously so callers can rely on prompt generation
        and timer re-arming having completed before the method returns.
        """
        has_goals = self._has_goal_files()
        decision = self._project_typescript_trigger_decision(
            stop_requested=self._stop_event.is_set(),
            has_goal_files=has_goals,
        )
        if decision is not None:
            if decision["action"] == "skip":
                return
            self._log(
                "goals scheduler: goal files detected — "
                "triggering immediate run on init"
            )
            if decision["cancel_timer_before_process"]:
                self._cancel_timer()
            try:
                self._process_goals()
            except Exception as exc:
                self._log(f"goals scheduler: initial trigger error: {exc}")
            finally:
                if (
                    decision["sync_timer_after_process"]
                    and not self._stop_event.is_set()
                ):
                    self._sync_timer()
            return

        if self._stop_event.is_set():
            return
        if not has_goals:
            return
        self._log("goals scheduler: goal files detected — triggering immediate run on init")
        # Cancel any timer that the watcher thread may have already armed
        # so the next interval starts fresh after this run completes.
        self._cancel_timer()
        try:
            self._process_goals()
        except Exception as exc:
            self._log(f"goals scheduler: initial trigger error: {exc}")
        finally:
            if not self._stop_event.is_set():
                self._sync_timer()

    # ------------------------------------------------------------------
    # Internal — watcher loop
    # ------------------------------------------------------------------

    def _watch_loop(self) -> None:
        """Poll goals directory and manage timer lifecycle."""
        while not self._stop_event.is_set():
            try:
                self._sync_timer()
            except Exception as exc:  # pragma: no cover
                self._log(f"goals scheduler: watcher error: {exc}")
            self._stop_event.wait(timeout=_WATCHER_POLL_SECONDS)

    def _sync_timer(self) -> None:
        """Align timer state with goals directory contents."""
        has_goals = self._has_goal_files()
        with self._timer_lock:
            timer_active = self._timer is not None
            decision = self._project_typescript_timer_decision(
                has_goal_files=has_goals,
                timer_active=timer_active,
            )
            if decision is not None:
                if decision["action"] == "schedule" and self._timer is None:
                    self._schedule_timer_locked(decision["interval_seconds"])
                elif decision["action"] == "cancel" and self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                    self._log("goals scheduler: no goal files — timer cancelled")
                return

            if has_goals and self._timer is None:
                self._schedule_timer_locked()
            elif not has_goals and self._timer is not None:
                self._timer.cancel()
                self._timer = None
                self._log("goals scheduler: no goal files — timer cancelled")

    # ------------------------------------------------------------------
    # Internal — timer management
    # ------------------------------------------------------------------

    def _schedule_timer_locked(self, interval_seconds: float | None = None) -> None:
        """Create and start a new timer. Caller must hold ``_timer_lock``."""
        interval = (
            interval_seconds
            if interval_seconds is not None
            else self._goals_config.interval_minutes * 60
        )
        self._timer = threading.Timer(interval, self._on_timer_fired)
        self._timer.daemon = True
        self._timer.start()
        self._log(
            f"goals scheduler: timer scheduled "
            f"({self._goals_config.interval_minutes}m interval)"
        )

    def _cancel_timer(self) -> None:
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _on_timer_fired(self) -> None:
        """Called by ``threading.Timer`` when the interval elapses."""
        decision = self._project_typescript_timer_fired_decision(
            stop_requested=self._stop_event.is_set(),
        )
        if decision is not None:
            if decision["clear_timer_before_process"]:
                with self._timer_lock:
                    self._timer = None
            if decision["action"] == "skip":
                return
            self._process_goals()
            if decision["sync_timer_after_process"]:
                self._sync_timer()
            return

        with self._timer_lock:
            self._timer = None  # allow re-scheduling after processing

        if self._stop_event.is_set():
            return

        self._process_goals()

        # Re-arm the timer if goal files remain.
        self._sync_timer()

    # ------------------------------------------------------------------
    # Internal — goal processing
    # ------------------------------------------------------------------

    def _process_goals(self) -> None:
        goal_files = self._list_goal_files()
        decision = self._project_typescript_process_decision(
            stop_requested=self._stop_event.is_set(),
            goal_file_count=len(goal_files),
        )
        if decision is not None:
            if decision["action"] == "skip":
                return
        elif not goal_files:
            return
        self._log(f"goals scheduler: processing {len(goal_files)} goal file(s)")
        for goal_file in goal_files:
            if self._stop_event.is_set():
                break
            try:
                self._process_single_goal(goal_file)
            except Exception as exc:
                self._log(
                    f"goals scheduler: error processing {goal_file.name}: {exc}"
                )

    def _process_single_goal(self, goal_file: Path) -> None:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        stem = goal_file.stem
        dest = self._prompt_path / f"{date_str}_{stem}.md"

        prompt_exists = dest.exists()
        decision = self._project_typescript_single_goal_decision(
            prompt_exists=prompt_exists,
        )
        if decision is not None:
            if decision["action"] == "skip":
                self._log(
                    f"goals scheduler: skipping {goal_file.name} "
                    f"— {dest.name} already queued"
                )
                return
        elif prompt_exists:
            self._log(
                f"goals scheduler: skipping {goal_file.name} "
                f"— {dest.name} already queued"
            )
            return

        goal_text = goal_file.read_text(encoding="utf-8")
        prompt = self._generate_prompt(goal_text, stem, date_str)
        projection = self._project_typescript_goal_prompt(goal_file, prompt, date_str)
        if projection is not None:
            dest = self._prompt_path / projection["filename"]
            prompt_with_meta = projection["content"]
        else:
            # Prepend a machine-readable metadata comment so that downstream
            # components (DaemonRunner, PipelineRunner, EvaluatorStage) can
            # recover the original goal file path without any shared state.
            goal_source_tag = (
                f"<!-- dormammu:goal_source={goal_file.resolve()} -->\n\n"
            )
            prompt_with_meta = goal_source_tag + prompt

        self._prompt_path.mkdir(parents=True, exist_ok=True)
        dest.write_text(prompt_with_meta, encoding="utf-8")
        self._log(f"goals scheduler: wrote prompt {dest.name}")

    # ------------------------------------------------------------------
    # Internal — prompt generation
    # ------------------------------------------------------------------

    def _generate_prompt(self, goal_text: str, stem: str, date_str: str) -> str:
        """Generate an analysis+plan+design prompt from goal content."""
        active_cli = getattr(self._app_config, "active_agent_cli", None)

        analyzer_profile = self._app_config.resolve_agent_profile("analyzer")
        planner_profile = self._app_config.resolve_agent_profile("planner")
        designer_profile = self._app_config.resolve_agent_profile("designer")
        analyzer_cli = analyzer_profile.resolve_cli(active_cli)
        planner_cli = planner_profile.resolve_cli(active_cli)
        designer_cli = designer_profile.resolve_cli(active_cli)

        role_configs = {
            "analyzer": (analyzer_cli, analyzer_profile.model_override),
            "planner": (planner_cli, planner_profile.model_override),
            "designer": (designer_cli, designer_profile.model_override),
        }
        analysis_text, plan_text, design_text = self._run_role_sequence(
            goal_text=goal_text,
            stem=stem,
            date_str=date_str,
            role_configs=role_configs,
        )

        return self._build_prompt(goal_text, analysis_text, plan_text, design_text)

    def _run_role_sequence(
        self,
        *,
        goal_text: str,
        stem: str,
        date_str: str,
        role_configs: dict[str, tuple[Path | None, str | None]],
    ) -> tuple[str | None, str | None, str | None]:
        analysis_text: str | None = None
        plan_text: str | None = None
        design_text: str | None = None
        attempted_roles: set[str] = set()

        for _ in range(3):
            step = self._next_typescript_role_step(
                goal_text=goal_text,
                analysis_text=analysis_text,
                plan_text=plan_text,
                design_text=design_text,
                role_configs=role_configs,
            )
            if step is None:
                break
            role = step["role"]
            if role in attempted_roles:
                break
            role_config = role_configs.get(role)
            if role_config is None:
                break
            cli, configured_model = role_config
            if cli is None:
                break
            attempted_roles.add(role)
            output = self._call_role_agent(
                role=role,
                cli=cli,
                model=step["model"] or configured_model,
                prompt=step["prompt"],
                stem=stem,
                date_str=date_str,
            )
            if role == "analyzer":
                analysis_text = output
            elif role == "planner":
                plan_text = output
            elif role == "designer":
                design_text = output

        return self._complete_python_role_sequence(
            goal_text=goal_text,
            stem=stem,
            date_str=date_str,
            role_configs=role_configs,
            analysis_text=analysis_text,
            plan_text=plan_text,
            design_text=design_text,
            attempted_roles=attempted_roles,
        )

    def _complete_python_role_sequence(
        self,
        *,
        goal_text: str,
        stem: str,
        date_str: str,
        role_configs: dict[str, tuple[Path | None, str | None]],
        analysis_text: str | None,
        plan_text: str | None,
        design_text: str | None,
        attempted_roles: set[str],
    ) -> tuple[str | None, str | None, str | None]:
        analyzer_cli, analyzer_model = role_configs["analyzer"]
        planner_cli, planner_model = role_configs["planner"]
        designer_cli, designer_model = role_configs["designer"]

        if (
            analyzer_cli is not None
            and analysis_text is None
            and "analyzer" not in attempted_roles
        ):
            analysis_text = self._call_role_agent(
                role="analyzer",
                cli=analyzer_cli,
                model=analyzer_model,
                prompt=self._analyzer_prompt(goal_text),
                stem=stem,
                date_str=date_str,
            )

        if (
            planner_cli is not None
            and plan_text is None
            and "planner" not in attempted_roles
        ):
            plan_text = self._call_role_agent(
                role="planner",
                cli=planner_cli,
                model=planner_model,
                prompt=self._planner_prompt(goal_text, analysis_text),
                stem=stem,
                date_str=date_str,
            )

        if (
            designer_cli is not None
            and plan_text is not None
            and design_text is None
            and "designer" not in attempted_roles
        ):
            design_text = self._call_role_agent(
                role="designer",
                cli=designer_cli,
                model=designer_model,
                prompt=self._designer_prompt(goal_text, analysis_text, plan_text),
                stem=stem,
                date_str=date_str,
            )

        return analysis_text, plan_text, design_text

    def _analyzer_prompt(self, goal_text: str) -> str:
        return (
            "You are an analyzer agent. Analyse the goal below and produce a "
            "requirements-focused brief that a planner can immediately use.\n\n"
            "Include:\n"
            "1. Goal restatement\n"
            "2. In-scope and out-of-scope boundaries\n"
            "3. Concrete acceptance criteria\n"
            "4. Constraints and dependencies\n"
            "5. Risks, ambiguities, and open questions\n\n"
            f"# Goal\n\n{goal_text.strip()}\n\n"
            "Output your analysis in Markdown. "
            "Write all content in English regardless of the language of the goal above."
        )

    def _planner_prompt(self, goal_text: str, analysis_text: str | None) -> str:
        analysis_section = (
            f"# Requirements Analysis\n\n{analysis_text.strip()}\n\n"
            if analysis_text
            else ""
        )
        return (
            "You are a planning agent. Use the goal and requirements analysis "
            "below to produce the authoritative execution plan for this task.\n\n"
            "Include:\n"
            "1. Phase breakdown with clear completion signals\n"
            "2. An explicit refine -> plan entry requirement for execution\n"
            "3. A statement that the planner decides the downstream stages "
            "after plan via .dev/WORKFLOWS.md\n"
            "4. Acceptance criteria and validation strategy\n"
            "5. Risks, blockers, and escalation points\n\n"
            f"# Goal\n\n{goal_text.strip()}\n\n"
            f"{analysis_section}"
            "Output your plan in Markdown. "
            "Write all content in English regardless of the language of the goal above."
        )

    def _designer_prompt(
        self,
        goal_text: str,
        analysis_text: str | None,
        plan_text: str,
    ) -> str:
        analysis_section = (
            f"# Requirements Analysis\n\n{analysis_text.strip()}\n\n"
            if analysis_text
            else ""
        )
        return (
            "You are a designing agent. Based on the plan below, create a "
            "technical OOAD design.\n\n"
            "Include:\n"
            "1. Module/class design with responsibilities\n"
            "2. Interface contracts and data schemas\n"
            "3. State management and error handling\n"
            "4. Test strategy (unit, integration, system)\n\n"
            f"# Original Goal\n\n{goal_text.strip()}\n\n"
            f"{analysis_section}"
            f"# Plan\n\n{plan_text.strip()}\n\n"
            "Output your design in Markdown. "
            "Write all content in English regardless of the language of the goal above."
        )

    def _call_role_agent(
        self,
        *,
        role: str,
        cli: Path,
        model: str | None,
        prompt: str,
        stem: str,
        date_str: str,
    ) -> str | None:
        """Run an agent CLI once via :class:`CliAdapter` and return its output.

        Uses the same command-building, prompt-injection, and output-capture
        primitives as :class:`~dormammu.daemon.pipeline_runner.PipelineRunner`
        so both execution paths share a single implementation.

        Returns the agent's output text, or ``None`` on failure.
        """
        self._log(f"goals scheduler: [{role}] starting")
        adapter = CliAdapter(
            self._app_config,
            live_output_stream=self._progress_stream,
            stop_event=self._stop_event,
        )
        request = AgentRunRequest(
            cli_path=cli,
            prompt_text=prompt,
            repo_root=self._app_config.repo_root,
            extra_args=tuple(model_args(cli.name, model)),
            run_label=f"goals-{role}",
            agent_role=role,
        )
        try:
            result = adapter.run_once(request)
        except Exception as exc:
            self._log(f"goals scheduler: [{role}] call failed: {exc}")
            return None

        stdout = result.stdout_path.read_text(encoding="utf-8") if result.stdout_path.exists() else ""
        stderr = result.stderr_path.read_text(encoding="utf-8") if result.stderr_path.exists() else ""
        output = select_agent_output(stdout, stderr)

        self._log(f"goals scheduler: [{role}] exit code: {result.exit_code}")
        if stdout.strip():
            self._log(f"goals scheduler: [{role}] stdout:\n{stdout.rstrip()}")
        else:
            self._log(f"goals scheduler: [{role}] stdout: (empty)")
        if stderr.strip():
            self._log(f"goals scheduler: [{role}] stderr:\n{stderr.rstrip()}")
        else:
            self._log(f"goals scheduler: [{role}] stderr: (empty)")

        # Persist the agent's output as a role document.
        doc_dir = self._app_config.base_dev_dir / "logs"
        projection = self._project_typescript_role_document(
            logs_dir=doc_dir,
            date_str=date_str,
            role=role,
            stem=stem,
            output=output,
        )
        if projection is not None:
            doc_path = Path(projection["path"])
            content = projection["content"]
        else:
            doc_path = doc_dir / f"{date_str}_{role}_{stem}.md"
            content = f"# {role.capitalize()} — {stem}\n\n{output}"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(content, encoding="utf-8")
        self._log(f"goals scheduler: [{role}] document written to {doc_path}")
        return output or None

    @staticmethod
    def _build_prompt(
        goal_text: str,
        analysis_text: str | None,
        plan_text: str | None,
        design_text: str | None,
    ) -> str:
        language_notice = (
            "> **Language requirement:** All responses, code comments, "
            "documentation, and deliverables must be written in English."
        )
        workflow_contract = (
            "## Workflow Contract\n\n"
            "- Start every execution with the mandatory `refine -> plan` stages.\n"
            "- `refine` must produce or update `.dev/REQUIREMENTS.md`.\n"
            "- `plan` must produce or update `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and `.dev/DASHBOARD.md`.\n"
            "- After `plan`, continue with `design -> ...` according to `.dev/WORKFLOWS.md`.\n"
            "- Treat the planner as authoritative for the downstream stage sequence after `plan`.\n"
        )
        sections: list[str] = [
            language_notice,
            workflow_contract,
            f"# Goal\n\n{goal_text.strip()}",
        ]
        if analysis_text:
            sections.append(f"## Requirements Analysis\n\n{analysis_text.strip()}")
        if plan_text:
            sections.append(f"## Plan\n\n{plan_text.strip()}")
        if design_text:
            sections.append(f"## Design\n\n{design_text.strip()}")
        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Internal — directory helpers
    # ------------------------------------------------------------------

    def _has_goal_files(self) -> bool:
        try:
            return any(
                p.is_file() and p.suffix == ".md"
                for p in self._goals_config.path.iterdir()
            )
        except (OSError, NotADirectoryError):
            return False

    def _list_goal_files(self) -> list[Path]:
        if (typescript_payload := self._load_typescript_goals_queue()) is not None:
            goal_files = typescript_payload.get("goal_files")
            if isinstance(goal_files, list):
                paths = [
                    Path(path)
                    for item in goal_files
                    if isinstance(item, dict)
                    if isinstance(path := item.get("path"), str)
                ]
                if len(paths) == len(goal_files):
                    return paths
        try:
            return sorted(
                p
                for p in self._goals_config.path.iterdir()
                if p.is_file() and p.suffix == ".md"
            )
        except (OSError, NotADirectoryError):
            return []

    def _load_typescript_goals_queue(self) -> dict[str, object] | None:
        payload = {
            "entrypoint": "goals_queue",
            "goals_path": str(self._goals_config.path),
            "prompt_path": str(self._prompt_path),
            "date_text": datetime.now(timezone.utc).strftime("%Y%m%d"),
        }
        return self._run_typescript_runner_payload(payload)

    def _project_typescript_goal_prompt(
        self,
        goal_file: Path,
        generated_prompt: str,
        date_str: str,
    ) -> dict[str, str] | None:
        payload = {
            "entrypoint": "goals_prompt_projection",
            "goal_file_path": str(goal_file.resolve()),
            "generated_prompt": generated_prompt,
            "date_text": date_str,
        }
        result = self._run_typescript_runner_payload(payload)
        if result is None:
            return None
        filename = result.get("filename")
        content = result.get("content")
        if isinstance(filename, str) and isinstance(content, str):
            return {"filename": filename, "content": content}
        return None

    def _project_typescript_role_document(
        self,
        *,
        logs_dir: Path,
        date_str: str,
        role: str,
        stem: str,
        output: str,
    ) -> dict[str, str] | None:
        payload = {
            "entrypoint": "goals_role_document_projection",
            "logs_dir": str(logs_dir),
            "date_text": date_str,
            "role": role,
            "stem": stem,
            "output": output,
        }
        result = self._run_typescript_runner_payload(payload)
        if result is None:
            return None
        path = result.get("path")
        content = result.get("content")
        if isinstance(path, str) and isinstance(content, str):
            return {"path": path, "content": content}
        return None

    def _next_typescript_role_step(
        self,
        *,
        goal_text: str,
        analysis_text: str | None,
        plan_text: str | None,
        design_text: str | None,
        role_configs: dict[str, tuple[Path | None, str | None]],
    ) -> dict[str, str | None] | None:
        roles = {
            role: {
                "cli": str(cli) if cli is not None else None,
                "model": model,
            }
            for role, (cli, model) in role_configs.items()
        }
        payload = {
            "entrypoint": "goals_role_sequence",
            "goal_text": goal_text,
            "analysis_text": analysis_text,
            "plan_text": plan_text,
            "design_text": design_text,
            "roles": roles,
        }
        result = self._run_typescript_runner_payload(payload)
        if result is None:
            return None
        step = result.get("next_step")
        if step is None:
            return None
        if not isinstance(step, dict):
            return None
        role = step.get("role")
        prompt = step.get("prompt")
        cli = step.get("cli")
        model = step.get("model")
        if role not in {"analyzer", "planner", "designer"}:
            return None
        if not isinstance(prompt, str):
            return None
        if not isinstance(cli, str):
            return None
        if model is not None and not isinstance(model, str):
            return None
        return {
            "role": role,
            "cli": cli,
            "model": model,
            "prompt": prompt,
        }

    def _project_typescript_timer_decision(
        self,
        *,
        has_goal_files: bool,
        timer_active: bool,
    ) -> dict[str, object] | None:
        payload = {
            "entrypoint": "goals_timer_decision",
            "has_goal_files": has_goal_files,
            "timer_active": timer_active,
            "interval_minutes": self._goals_config.interval_minutes,
        }
        result = self._run_typescript_runner_payload(payload)
        if result is None:
            return None
        action = result.get("action")
        interval_seconds = result.get("intervalSeconds")
        if action not in {"schedule", "cancel", "none"}:
            return None
        if action == "schedule":
            if not isinstance(interval_seconds, (int, float)):
                return None
            if interval_seconds < 0:
                return None
        else:
            interval_seconds = None
        return {
            "action": action,
            "interval_seconds": interval_seconds,
        }

    def _project_typescript_trigger_decision(
        self,
        *,
        stop_requested: bool,
        has_goal_files: bool,
    ) -> dict[str, object] | None:
        payload = {
            "entrypoint": "goals_trigger_decision",
            "stop_requested": stop_requested,
            "has_goal_files": has_goal_files,
        }
        result = self._run_typescript_runner_payload(payload)
        if result is None:
            return None
        action = result.get("action")
        cancel_before = result.get("cancelTimerBeforeProcess")
        sync_after = result.get("syncTimerAfterProcess")
        if action not in {"process", "skip"}:
            return None
        if not isinstance(cancel_before, bool):
            return None
        if not isinstance(sync_after, bool):
            return None
        return {
            "action": action,
            "cancel_timer_before_process": cancel_before,
            "sync_timer_after_process": sync_after,
        }

    def _project_typescript_process_decision(
        self,
        *,
        stop_requested: bool,
        goal_file_count: int,
    ) -> dict[str, object] | None:
        payload = {
            "entrypoint": "goals_process_decision",
            "stop_requested": stop_requested,
            "goal_file_count": goal_file_count,
        }
        result = self._run_typescript_runner_payload(payload)
        if result is None:
            return None
        action = result.get("action")
        projected_count = result.get("goalFileCount")
        if action not in {"process", "skip"}:
            return None
        if not isinstance(projected_count, int):
            return None
        if projected_count < 0:
            return None
        if projected_count != goal_file_count:
            return None
        if action == "process" and projected_count == 0:
            return None
        return {
            "action": action,
            "goal_file_count": projected_count,
        }

    def _project_typescript_timer_fired_decision(
        self,
        *,
        stop_requested: bool,
    ) -> dict[str, object] | None:
        payload = {
            "entrypoint": "goals_timer_fired_decision",
            "stop_requested": stop_requested,
        }
        result = self._run_typescript_runner_payload(payload)
        if result is None:
            return None
        action = result.get("action")
        clear_before = result.get("clearTimerBeforeProcess")
        sync_after = result.get("syncTimerAfterProcess")
        if action not in {"process", "skip"}:
            return None
        if not isinstance(clear_before, bool):
            return None
        if not isinstance(sync_after, bool):
            return None
        return {
            "action": action,
            "clear_timer_before_process": clear_before,
            "sync_timer_after_process": sync_after,
        }

    def _project_typescript_single_goal_decision(
        self,
        *,
        prompt_exists: bool,
    ) -> dict[str, object] | None:
        payload = {
            "entrypoint": "goals_single_goal_decision",
            "prompt_exists": prompt_exists,
        }
        result = self._run_typescript_runner_payload(payload)
        if result is None:
            return None
        action = result.get("action")
        if action not in {"write", "skip"}:
            return None
        return {"action": action}

    def _run_typescript_runner_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, object] | None:
        runner_cli = getattr(self._app_config, "typescript_agent_runner_cli", None)
        if not isinstance(runner_cli, (str, Path)):
            return None

        repo_root = getattr(self._app_config, "repo_root", None)
        cwd = repo_root if isinstance(repo_root, Path) else Path.cwd()
        try:
            completed = subprocess.run(
                [str(runner_cli)],
                cwd=cwd,
                env=self._typescript_runner_env(),
                input=json.dumps(payload, ensure_ascii=True),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            self._log(f"goals scheduler: TypeScript runner bridge failed: {exc}")
            return None

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip()
            detail = f": {message}" if message else ""
            self._log(
                "goals scheduler: TypeScript runner bridge exited "
                f"with {completed.returncode}{detail}"
            )
            return None

        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            self._log("goals scheduler: TypeScript runner bridge returned invalid JSON")
            return None
        return result if isinstance(result, dict) else None

    def _typescript_runner_env(self) -> dict[str, str]:
        env = dict(os.environ)
        for name, attr in (
            ("HOME", "home_dir"),
            ("DORMAMMU_SESSIONS_DIR", "sessions_dir"),
            ("DORMAMMU_BASE_DEV_DIR", "base_dev_dir"),
            ("DORMAMMU_WORKSPACE_ROOT", "workspace_root"),
            ("DORMAMMU_WORKSPACE_PROJECT_ROOT", "workspace_project_root"),
            ("DORMAMMU_TMP_DIR", "workspace_tmp_dir"),
            ("DORMAMMU_RESULTS_DIR", "results_dir"),
        ):
            value = getattr(self._app_config, attr, None)
            if isinstance(value, (str, Path)):
                env[name] = str(value)
        return env

    def _log(self, message: str) -> None:
        try:
            print(message, file=self._progress_stream)
            self._progress_stream.flush()
        except ValueError:
            # Timer callbacks can outlive pytest's captured streams or an
            # operator-provided stream; logging must not crash the scheduler.
            return
