"""GoalsScheduler — background thread that watches a goals directory and
periodically generates plan+design prompts for the daemon queue.

Thread safety
-------------
- ``_timer`` and ``_timer_active`` are guarded by ``_timer_lock``.
- ``_goals_config.path`` is read-only after construction.
- The only shared state with ``DaemonRunner`` is the ``prompt_path``
  directory, which is accessed via atomic file-system writes.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from dormammu.config import AppConfig
    from dormammu.daemon.goals_config import GoalsConfig

_WATCHER_POLL_SECONDS = 30


class GoalsScheduler:
    """Monitors a goals directory and generates plan+design prompts on a timer.

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
        waiting for the first timer interval to elapse.  Any previously
        scheduled timer is cancelled first so that the next interval is
        measured from *this* run, not from when the daemon started.

        Processing runs in a background thread so the calling thread
        (the main daemon loop) is not blocked while agent CLIs execute.
        """
        if self._stop_event.is_set():
            return
        if not self._has_goal_files():
            return
        self._log("goals scheduler: goal files detected — triggering immediate run on init")
        # Cancel any timer that the watcher thread may have already armed
        # so the next interval starts fresh after this run completes.
        self._cancel_timer()
        t = threading.Thread(
            target=self._trigger_now_bg,
            daemon=True,
            name="dormammu-goals-init-trigger",
        )
        t.start()

    def _trigger_now_bg(self) -> None:
        """Background task: process goals immediately then re-arm the periodic timer."""
        try:
            if self._stop_event.is_set():
                return
            # Cancel any timer the watcher thread may have armed between
            # trigger_now() returning and this thread starting.
            self._cancel_timer()
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
            if has_goals and self._timer is None:
                self._schedule_timer_locked()
            elif not has_goals and self._timer is not None:
                self._timer.cancel()
                self._timer = None
                self._log("goals scheduler: no goal files — timer cancelled")

    # ------------------------------------------------------------------
    # Internal — timer management
    # ------------------------------------------------------------------

    def _schedule_timer_locked(self) -> None:
        """Create and start a new timer. Caller must hold ``_timer_lock``."""
        interval = self._goals_config.interval_minutes * 60
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
        if not goal_files:
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

        if dest.exists():
            self._log(
                f"goals scheduler: skipping {goal_file.name} "
                f"— {dest.name} already queued"
            )
            return

        goal_text = goal_file.read_text(encoding="utf-8")
        prompt = self._generate_prompt(goal_text, stem, date_str)

        self._prompt_path.mkdir(parents=True, exist_ok=True)
        dest.write_text(prompt, encoding="utf-8")
        self._log(f"goals scheduler: wrote prompt {dest.name}")

    # ------------------------------------------------------------------
    # Internal — prompt generation
    # ------------------------------------------------------------------

    def _generate_prompt(self, goal_text: str, stem: str, date_str: str) -> str:
        """Generate a plan+design prompt from goal content.

        When an ``agents`` config is available and both planner and architect
        CLIs are resolvable, this method calls each agent once (one-shot,
        non-interactive) to produce planning and design documents, then
        assembles a rich prompt from their outputs.

        If no agents config is present (or CLIs cannot be resolved), a
        structured prompt is built directly from the raw goal text so that
        the developer agent can handle planning and design inline.
        """
        agents = getattr(self._app_config, "agents", None)
        active_cli = getattr(self._app_config, "active_agent_cli", None)

        plan_text: str | None = None
        design_text: str | None = None

        if agents is not None:
            planner_cfg = agents.for_role("planner")
            architect_cfg = agents.for_role("architect")
            planner_cli = planner_cfg.resolve_cli(active_cli)
            architect_cli = architect_cfg.resolve_cli(active_cli)

            if planner_cli is not None:
                plan_text = self._call_role_agent(
                    role="planner",
                    cli=planner_cli,
                    model=planner_cfg.model,
                    prompt=self._planner_prompt(goal_text),
                    stem=stem,
                    date_str=date_str,
                    slot="01",
                )

            if architect_cli is not None and plan_text is not None:
                design_text = self._call_role_agent(
                    role="architect",
                    cli=architect_cli,
                    model=architect_cfg.model,
                    prompt=self._architect_prompt(goal_text, plan_text),
                    stem=stem,
                    date_str=date_str,
                    slot="02",
                )

        return self._build_prompt(goal_text, plan_text, design_text)

    def _planner_prompt(self, goal_text: str) -> str:
        return (
            "You are a planning agent. Analyse the following goal and produce a "
            "detailed implementation plan.\n\n"
            "Include:\n"
            "1. Requirements analysis\n"
            "2. Phase breakdown with clear completion signals\n"
            "3. Acceptance criteria\n"
            "4. Risk assessment\n\n"
            f"# Goal\n\n{goal_text.strip()}\n\n"
            "Output your plan in Markdown."
        )

    def _architect_prompt(self, goal_text: str, plan_text: str) -> str:
        return (
            "You are an architect agent. Based on the plan below, create a "
            "technical OOAD design.\n\n"
            "Include:\n"
            "1. Module/class design with responsibilities\n"
            "2. Interface contracts and data schemas\n"
            "3. State management and error handling\n"
            "4. Test strategy (unit, integration, system)\n\n"
            f"# Original Goal\n\n{goal_text.strip()}\n\n"
            f"# Plan\n\n{plan_text.strip()}\n\n"
            "Output your design in Markdown."
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
        slot: str,
    ) -> str | None:
        """Run an agent CLI once and return its stdout, or None on failure."""
        from dormammu.agent.presets import preset_for_executable_name

        executable_name = cli.name
        preset = preset_for_executable_name(executable_name)

        args: list[str] = [str(cli)]
        stdin_input: str | None = None

        if preset is not None:
            args.extend(preset.command_prefix)
            args.extend(preset.default_extra_args)

        if model is not None:
            model_flag = _model_flag_for(executable_name)
            if model_flag:
                args.extend([model_flag, model])

        # Deliver the prompt: positional > file flag > stdin
        if preset is not None and preset.prompt_positional:
            args.append(prompt)
        elif preset is not None and preset.prompt_file_flag:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(prompt)
                tmp_path = Path(tmp.name)
            args.extend([preset.prompt_file_flag, str(tmp_path)])
        elif preset is not None and preset.prompt_arg_flag:
            args.extend([preset.prompt_arg_flag, prompt])
        else:
            stdin_input = prompt

        _ROLE_AGENT_TIMEOUT_SECONDS = 300  # 5-minute cap per role agent call

        try:
            self._log(f"goals scheduler: calling {role} agent ({cli.name}) for {stem}")
            # When the prompt is passed via positional arg or flag (stdin_input is
            # None), close the subprocess stdin so the CLI cannot block waiting
            # for interactive input.
            run_kwargs: dict = dict(
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self._app_config.repo_root),
                timeout=_ROLE_AGENT_TIMEOUT_SECONDS,
            )
            if stdin_input is not None:
                run_kwargs["input"] = stdin_input
            else:
                run_kwargs["stdin"] = subprocess.DEVNULL
            result = subprocess.run(args, **run_kwargs)
            if result.returncode != 0:
                self._log(
                    f"goals scheduler: {role} agent exited with code {result.returncode}"
                )
            if result.stderr.strip():
                self._log(f"goals scheduler: {role} agent stderr: {result.stderr.strip()}")
            output = result.stdout or ""

            # Persist the agent's output as a role document.
            doc_dir = self._app_config.base_dev_dir / f"{slot}-{role}"
            doc_dir.mkdir(parents=True, exist_ok=True)
            doc_path = doc_dir / f"{date_str}_{stem}.md"
            doc_path.write_text(
                f"# {role.capitalize()} — {stem}\n\n{output}",
                encoding="utf-8",
            )
            self._log(f"goals scheduler: {role} document written to {doc_path}")
            return output or None
        except subprocess.TimeoutExpired:
            self._log(
                f"goals scheduler: {role} agent timed out after "
                f"{_ROLE_AGENT_TIMEOUT_SECONDS}s — skipping"
            )
            return None
        except Exception as exc:
            self._log(f"goals scheduler: {role} agent call failed: {exc}")
            return None
        finally:
            if "tmp_path" in dir() and tmp_path.exists():  # type: ignore[name-defined]
                tmp_path.unlink(missing_ok=True)  # type: ignore[name-defined]

    @staticmethod
    def _build_prompt(
        goal_text: str,
        plan_text: str | None,
        design_text: str | None,
    ) -> str:
        sections: list[str] = [f"# Goal\n\n{goal_text.strip()}"]
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
        try:
            return sorted(
                p
                for p in self._goals_config.path.iterdir()
                if p.is_file() and p.suffix == ".md"
            )
        except (OSError, NotADirectoryError):
            return []

    def _log(self, message: str) -> None:
        print(message, file=self._progress_stream)
        self._progress_stream.flush()


def _model_flag_for(executable_name: str) -> str | None:
    """Return the CLI-specific model selection flag, or None if unknown."""
    _MODEL_FLAGS: dict[str, str] = {
        "claude": "--model",
        "claude-code": "--model",
        "gemini": "--model",
        "codex": "-m",
        "aider": "--model",
    }
    return _MODEL_FLAGS.get(executable_name.lower())
