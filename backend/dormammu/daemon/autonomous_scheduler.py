"""AutonomousScheduler — background thread that periodically analyzes the
repository and generates development prompts for the daemon queue without
requiring any human-supplied goal files.

Thread safety
-------------
- ``_timer`` and ``_timer_active`` are guarded by ``_timer_lock``.
- The only shared state with ``DaemonRunner`` is the ``prompt_path``
  directory, which is accessed via atomic file-system writes.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from dormammu.agent import CliAdapter
from dormammu.agent.models import AgentRunRequest
from dormammu.agent.role_config import AgentsConfig
from dormammu.daemon.cli_output import model_args, select_agent_output

if TYPE_CHECKING:
    from dormammu.config import AppConfig
    from dormammu.daemon.autonomous_config import AutonomousConfig

_WATCHER_POLL_SECONDS = 60
_AUTO_PROMPT_PREFIX = "auto_"

_FOCUS_DESCRIPTIONS: dict[str, str] = {
    "all": (
        "any area that would most improve overall project quality, reliability, "
        "or developer experience"
    ),
    "bugs": (
        "known bugs, failing tests, unhandled error paths, crash-prone code, "
        "or reliability regressions"
    ),
    "improvements": (
        "performance bottlenecks, code clarity, architectural simplification, "
        "refactoring opportunities, or technical debt"
    ),
    "tests": (
        "missing unit tests, weak integration coverage, untested edge cases, "
        "or flaky test infrastructure"
    ),
    "docs": (
        "missing or outdated documentation, unclear API contracts, missing "
        "docstrings, or stale README sections"
    ),
}


class AutonomousScheduler:
    """Analyzes the repository on a timer and generates development prompts.

    Lifecycle
    ---------
    1. ``start()`` — spawns the watcher thread (daemon=True).
    2. ``trigger_now()`` — optionally runs immediately on daemon init.
    3. On each timer fire: collect repo context → call analyzer agent →
       write generated prompt to ``prompt_path``.
    4. ``stop()`` — signals the watcher thread to exit and cancels any timer.
    """

    def __init__(
        self,
        autonomous_config: AutonomousConfig,
        prompt_path: Path,
        app_config: AppConfig,
        *,
        progress_stream: TextIO | None = None,
    ) -> None:
        self._config = autonomous_config
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
            name="dormammu-autonomous-watcher",
        )
        self._watcher_thread.start()

    def stop(self) -> None:
        """Signal the watcher to exit and cancel any pending timer."""
        self._stop_event.set()
        self._cancel_timer()

    def trigger_now(self) -> None:
        """Immediately run an analysis cycle and schedule the next timer.

        Cancels any previously armed timer so the interval is measured from
        this run, not from daemon start time.  Runs synchronously.
        """
        if self._stop_event.is_set():
            return
        self._log("autonomous scheduler: starting immediate analysis cycle on init")
        self._cancel_timer()
        try:
            self._run_cycle()
        except Exception as exc:
            self._log(f"autonomous scheduler: initial trigger error: {exc}")
        finally:
            if not self._stop_event.is_set():
                self._arm_timer()

    # ------------------------------------------------------------------
    # Internal — watcher loop
    # ------------------------------------------------------------------

    def _watch_loop(self) -> None:
        """Arm the timer on startup, then poll to keep it alive."""
        # Arm once on first entry.
        self._sync_timer()
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=_WATCHER_POLL_SECONDS)

    def _sync_timer(self) -> None:
        """Arm the timer if not already running."""
        with self._timer_lock:
            if self._timer is None and not self._stop_event.is_set():
                self._arm_timer_locked()

    def _arm_timer(self) -> None:
        with self._timer_lock:
            if not self._stop_event.is_set():
                self._arm_timer_locked()

    def _arm_timer_locked(self) -> None:
        """Create and start a new timer. Caller must hold ``_timer_lock``."""
        interval = self._config.interval_minutes * 60
        self._timer = threading.Timer(interval, self._on_timer_fired)
        self._timer.daemon = True
        self._timer.start()
        self._log(
            f"autonomous scheduler: timer armed "
            f"({self._config.interval_minutes}m interval, focus={self._config.focus})"
        )

    def _cancel_timer(self) -> None:
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _on_timer_fired(self) -> None:
        """Called by ``threading.Timer`` when the interval elapses."""
        with self._timer_lock:
            self._timer = None

        if self._stop_event.is_set():
            return

        try:
            self._run_cycle()
        except Exception as exc:
            self._log(f"autonomous scheduler: cycle error: {exc}")

        # Re-arm for next interval.
        self._arm_timer()

    # ------------------------------------------------------------------
    # Internal — analysis cycle
    # ------------------------------------------------------------------

    def _run_cycle(self) -> None:
        """Collect repo context, generate a prompt, and write it to the queue."""
        queued = self._count_queued_auto_tasks()
        if queued >= self._config.max_queued_tasks:
            self._log(
                f"autonomous scheduler: {queued} auto task(s) already queued "
                f"(max={self._config.max_queued_tasks}); skipping generation"
            )
            return

        self._log("autonomous scheduler: collecting repository context")
        context = self._gather_repo_context()

        self._log("autonomous scheduler: calling analyzer agent")
        prompt_text = self._generate_improvement_prompt(context)
        if not prompt_text or not prompt_text.strip():
            self._log("autonomous scheduler: analyzer produced no output; skipping")
            return

        self._write_prompt(prompt_text)

    # ------------------------------------------------------------------
    # Internal — repository context collection
    # ------------------------------------------------------------------

    def _gather_repo_context(self) -> str:
        """Collect repository state without calling any agent."""
        parts: list[str] = []
        repo_root = self._app_config.repo_root

        # Recent git log.
        git_log = self._run_git(["log", "--oneline", "-15"], cwd=repo_root)
        if git_log:
            parts.append(f"## Recent Commits\n\n```\n{git_log}\n```")

        # Git status summary.
        git_status = self._run_git(["status", "--short"], cwd=repo_root)
        if git_status:
            parts.append(f"## Git Status\n\n```\n{git_status}\n```")

        # README.
        for name in ("README.md", "README.rst", "README.txt", "README"):
            candidate = repo_root / name
            if candidate.exists():
                content = candidate.read_text(encoding="utf-8", errors="replace")[:3000]
                parts.append(f"## README ({name})\n\n{content}")
                break

        # .dev/ state files.
        dev_dir = self._app_config.base_dev_dir
        for fname in ("DASHBOARD.md", "ROADMAP.md", "TASKS.md", "REQUIREMENTS.md"):
            fpath = dev_dir / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8", errors="replace")[:2000]
                parts.append(f"## .dev/{fname}\n\n{content}")

        # TODO / FIXME comment count (best effort).
        todo_count = self._count_todo_fixme(repo_root)
        if todo_count is not None:
            parts.append(f"## Code Quality\n\nTODO / FIXME comments found: {todo_count}")

        # Recently completed auto-task results (avoid repeating).
        recent_results = self._read_recent_auto_results()
        if recent_results:
            parts.append(f"## Recently Completed Auto-Tasks\n\n{recent_results}")

        return "\n\n---\n\n".join(parts) if parts else "(no context available)"

    def _run_git(self, args: list[str], *, cwd: Path) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=30,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    def _count_todo_fixme(self, repo_root: Path) -> int | None:
        try:
            result = subprocess.run(
                ["grep", "-rn", "--include=*.py", "-c", r"TODO\|FIXME", "."],
                capture_output=True,
                text=True,
                cwd=repo_root,
                timeout=20,
            )
            total = 0
            for line in result.stdout.splitlines():
                if ":" in line:
                    try:
                        total += int(line.rsplit(":", 1)[-1])
                    except ValueError:
                        pass
            return total
        except Exception:
            return None

    def _read_recent_auto_results(self) -> str:
        """Read titles of the last few completed auto-task result files."""
        result_path = self._prompt_path.parent / "results"
        if not result_path.exists():
            return ""
        try:
            files = sorted(
                (p for p in result_path.iterdir() if p.name.startswith(_AUTO_PROMPT_PREFIX) and p.suffix == ".md"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:5]
            titles: list[str] = []
            for f in files:
                first_line = f.read_text(encoding="utf-8", errors="replace").splitlines()[0]
                titles.append(f"- {first_line.lstrip('# ').strip()}")
            return "\n".join(titles)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Internal — prompt generation via agent
    # ------------------------------------------------------------------

    def _generate_improvement_prompt(self, context: str) -> str | None:
        """Run the analyzer agent and return a complete development prompt."""
        focus_desc = _FOCUS_DESCRIPTIONS.get(self._config.focus, _FOCUS_DESCRIPTIONS["all"])
        analyzer_prompt = self._build_analyzer_prompt(context, focus_desc)

        agents = getattr(self._app_config, "agents", None) or AgentsConfig()
        active_cli = getattr(self._app_config, "active_agent_cli", None)

        analyzer_cfg = agents.for_role("analyzer")
        analyzer_cli = analyzer_cfg.resolve_cli(active_cli)
        if analyzer_cli is None:
            self._log("autonomous scheduler: no analyzer CLI configured; skipping")
            return None

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        adapter = CliAdapter(
            self._app_config,
            live_output_stream=self._progress_stream,
            stop_event=self._stop_event,
        )
        request = AgentRunRequest(
            cli_path=analyzer_cli,
            prompt_text=analyzer_prompt,
            repo_root=self._app_config.repo_root,
            extra_args=tuple(model_args(analyzer_cli.name, analyzer_cfg.model)),
            run_label=f"autonomous-analyzer-{date_str}",
        )
        try:
            result = adapter.run_once(request)
        except Exception as exc:
            self._log(f"autonomous scheduler: analyzer call failed: {exc}")
            return None

        stdout = result.stdout_path.read_text(encoding="utf-8") if result.stdout_path and result.stdout_path.exists() else ""
        stderr = result.stderr_path.read_text(encoding="utf-8") if result.stderr_path and result.stderr_path.exists() else ""
        output = select_agent_output(stdout, stderr)

        self._log(f"autonomous scheduler: analyzer exit code: {result.exit_code}")
        if not output.strip():
            self._log("autonomous scheduler: analyzer returned empty output")
            return None

        # Save the analyzer output as a log document.
        doc_dir = self._app_config.base_dev_dir / "logs"
        doc_dir.mkdir(parents=True, exist_ok=True)
        doc_path = doc_dir / f"{date_str}_autonomous_analysis.md"
        doc_path.write_text(
            f"# Autonomous Analysis — {date_str}\n\nFocus: {self._config.focus}\n\n{output}",
            encoding="utf-8",
        )
        self._log(f"autonomous scheduler: analysis document saved to {doc_path}")

        return output

    def _build_analyzer_prompt(self, context: str, focus_desc: str) -> str:
        return (
            "You are an autonomous improvement agent for a software project.\n\n"
            "Your task:\n"
            "1. Analyze the repository context below.\n"
            f"2. Identify the single highest-priority improvement opportunity, focusing on: {focus_desc}.\n"
            "3. Write a complete, actionable development prompt that another coding agent can execute "
            "immediately without additional context.\n\n"
            "The development prompt you write must include:\n"
            "- A concise title (one line, starts with `# `)\n"
            "- Clear problem statement and motivation\n"
            "- Concrete acceptance criteria\n"
            "- Specific files or areas to change\n"
            "- Any constraints, risks, or dependencies to be aware of\n\n"
            "Requirements:\n"
            "- Output ONLY the development prompt (title + body), no preamble, no commentary.\n"
            "- Write everything in English.\n"
            "- Be specific and actionable — avoid vague goals like 'improve code quality'.\n"
            "- Do NOT repeat a task that appears in the 'Recently Completed Auto-Tasks' section.\n\n"
            "## Repository Context\n\n"
            f"{context}\n"
        )

    # ------------------------------------------------------------------
    # Internal — queue management
    # ------------------------------------------------------------------

    def _count_queued_auto_tasks(self) -> int:
        """Count auto-generated prompt files currently waiting in the queue."""
        try:
            return sum(
                1
                for p in self._prompt_path.iterdir()
                if p.is_file() and p.name.startswith(_AUTO_PROMPT_PREFIX)
            )
        except (OSError, NotADirectoryError):
            return 0

    def _write_prompt(self, prompt_text: str) -> None:
        """Write the generated prompt as a queued file."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = self._prompt_path / f"{_AUTO_PROMPT_PREFIX}{date_str}.md"
        self._prompt_path.mkdir(parents=True, exist_ok=True)
        # Prepend a machine-readable tag so downstream components can identify
        # autonomous prompts and apply evaluator logic if configured.
        header = f"<!-- dormammu:autonomous focus={self._config.focus} -->\n\n"
        dest.write_text(header + prompt_text.strip() + "\n", encoding="utf-8")
        self._log(f"autonomous scheduler: queued development prompt → {dest.name}")

    # ------------------------------------------------------------------
    # Internal — helpers
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        print(message, file=self._progress_stream)
        self._progress_stream.flush()
