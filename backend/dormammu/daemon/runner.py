from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import threading
import time
from typing import Generator, Mapping, TextIO

from dormammu.agent.role_config import AgentsConfig

try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False


def _get_pid() -> int:
    return os.getpid()


def _path_created_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


class DaemonAlreadyRunningError(RuntimeError):
    """Raised when a second daemon instance tries to start on the same queue."""

from dormammu._utils import iso_now as _iso_now
from dormammu.agent import CliAdapter
from dormammu.config import AppConfig
from dormammu.continuation import build_supervisor_handoff_prompt_for_repository
from dormammu.daemon._patterns import (
    GOAL_SOURCE_RE as _GOAL_SOURCE_RE,
    RESULT_STATUS_RE as _RESULT_STATUS_RE,
)
from dormammu.daemon.autonomous_scheduler import AutonomousScheduler
from dormammu.daemon.goals_scheduler import GoalsScheduler
from dormammu.daemon.models import DaemonConfig, DaemonPromptResult
from dormammu.daemon.pipeline_runner import PipelineRunner
from dormammu.daemon.queue import is_prompt_candidate, prompt_sort_key
from dormammu.daemon.reports import ResultReportAuthor, render_result_markdown
from dormammu.daemon.watchers import EFFECTIVE_POLL_INTERVAL_SECONDS, PromptWatcher, build_watcher
from dormammu.guidance import build_guidance_prompt
from dormammu.artifacts import ArtifactWriter
from dormammu.lifecycle import (
    ArtifactPersistedPayload,
    ArtifactRef,
    LifecycleEventType,
    LifecycleRecorder,
    RunEventPayload,
    SupervisorHandoffPayload,
)
from dormammu.loop_runner import LoopRunResult, LoopRunRequest, LoopRunner
from dormammu.request_routing import resolve_request_class
from dormammu.results import run_result_has_clean_terminal_stage_evidence
from dormammu.state import StateRepository
from dormammu.state.models import infer_primary_roadmap_phase_id, summarize_prompt_goal


DEFAULT_DAEMON_MAX_RETRIES = 49


class _PromptSkipped(Exception):
    """Sentinel exception for gracefully skipping a deleted prompt file."""


class SessionProgressLogStream:
    def __init__(self, terminal_stream: TextIO) -> None:
        self._terminal_stream = terminal_stream
        self._log_stream: TextIO | None = None
        self.encoding = getattr(terminal_stream, "encoding", "utf-8")

    def reset_session_log(self, log_path: Path) -> None:
        self.close_log()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_stream = log_path.open("w", encoding="utf-8")

    def write(self, data: str) -> int:
        self._terminal_stream.write(data)
        if self._log_stream is not None:
            self._log_stream.write(data)
        return len(data)

    def flush(self) -> None:
        self._terminal_stream.flush()
        if self._log_stream is not None:
            self._log_stream.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._terminal_stream, "isatty", lambda: False)())

    def close_log(self) -> None:
        if self._log_stream is None:
            return
        self._log_stream.close()
        self._log_stream = None


class DaemonRunner:
    def __init__(
        self,
        app_config: AppConfig,
        daemon_config: DaemonConfig,
        *,
        repository: StateRepository | None = None,
        progress_stream: TextIO | None = None,
        watcher: PromptWatcher | None = None,
    ) -> None:
        self.app_config = app_config
        self.daemon_config = daemon_config
        self.repository = repository or StateRepository(app_config)
        self.progress_stream = progress_stream or sys.stderr
        self.watcher = watcher
        self._in_progress: set[Path] = set()
        # Guards _in_progress against concurrent reads from the Telegram bot
        # thread and writes from the main daemon thread.
        self._in_progress_lock = threading.Lock()
        # Set by request_shutdown() to signal run_forever() to exit cleanly.
        self._shutdown_requested = threading.Event()
        # Path to the heartbeat file written each loop cycle (None = disabled).
        self._heartbeat_path: Path | None = (
            self.daemon_config.result_path.parent / "daemon_heartbeat.json"
        )
        # PID-file path used to prevent duplicate daemon instances.
        self._pid_lock_path: Path = (
            self.daemon_config.result_path.parent / "daemon.pid"
        )
        self._pid_lock_file: object = None  # open file handle held while running
        # Set in run_forever() so request_shutdown() can wake up the watcher.
        self._active_watcher: object = None
        # Goals scheduler — started in run_forever() when goals config is set.
        self._goals_scheduler: GoalsScheduler | None = (
            GoalsScheduler(
                self.daemon_config.goals,
                self.daemon_config.prompt_path,
                self.app_config,
                progress_stream=self.progress_stream,
            )
            if self.daemon_config.goals is not None
            else None
        )
        # Autonomous scheduler — started in run_forever() when autonomous config is set.
        _autonomous_cfg = self.daemon_config.autonomous
        self._autonomous_scheduler: AutonomousScheduler | None = (
            AutonomousScheduler(
                _autonomous_cfg,
                self.daemon_config.prompt_path,
                self.app_config,
                progress_stream=self.progress_stream,
            )
            if _autonomous_cfg is not None and _autonomous_cfg.enabled
            else None
        )

    def in_progress_snapshot(self) -> frozenset[Path]:
        """Return a thread-safe snapshot of the currently-active prompt paths."""
        with self._in_progress_lock:
            return frozenset(self._in_progress)

    def request_shutdown(self) -> None:
        """Ask the daemon loop to stop after the current prompt finishes.

        Safe to call from any thread (e.g. Telegram bot, signal handler).
        Sets the shutdown event (unblocks PollingWatcher immediately) and
        writes to the inotify watcher's wake-up pipe so that
        InotifyWatcher.wait_for_changes() returns without delay.
        """
        self._shutdown_requested.set()
        # Wake up the inotify watcher if it's currently blocking in select().
        watcher = getattr(self, "_active_watcher", None)
        if watcher is not None and hasattr(watcher, "_wake_up"):
            watcher._wake_up()

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested.is_set()

    def run_forever(self) -> int:
        self.daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
        self.daemon_config.result_path.mkdir(parents=True, exist_ok=True)
        with self._instance_lock():
            watcher = self.watcher or build_watcher(
                self.daemon_config.prompt_path,
                self.daemon_config.watch,
                event_logger=self._log,
                stop_event=self._shutdown_requested,
            )
            self._active_watcher = watcher
            watcher.start()
            self._emit_startup_banner(watcher_backend=watcher.backend_name)
            self._write_heartbeat(status="idle")
            if self._goals_scheduler is not None:
                self._goals_scheduler.start()
                self._log("goals scheduler: started")
                self._goals_scheduler.trigger_now()
            if self._autonomous_scheduler is not None:
                self._autonomous_scheduler.start()
                self._log("autonomous scheduler: started")
                self._autonomous_scheduler.trigger_now()
            try:
                while not self._shutdown_requested.is_set():
                    processed = self.run_pending_once(watcher_backend=watcher.backend_name)
                    self._write_heartbeat(
                        status="busy" if self.in_progress_snapshot() else "idle"
                    )
                    if processed == 0:
                        if self._shutdown_requested.is_set():
                            break
                        watcher.wait_for_changes()
            finally:
                if self._goals_scheduler is not None:
                    self._goals_scheduler.stop()
                    self._log("goals scheduler: stopped")
                if self._autonomous_scheduler is not None:
                    self._autonomous_scheduler.stop()
                    self._log("autonomous scheduler: stopped")
                watcher.close()
                self._remove_heartbeat()
                if hasattr(self.progress_stream, "close_log"):
                    self.progress_stream.close_log()
            self._log("daemon shutdown complete.")

    def run_pending_once(self, *, watcher_backend: str | None = None) -> int:
        self.daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
        self.daemon_config.result_path.mkdir(parents=True, exist_ok=True)
        processed = 0
        while True:
            ready_prompt_paths, retry_after_seconds = self._scan_prompt_queue()
            if not ready_prompt_paths:
                if processed == 0 and retry_after_seconds is not None:
                    self._log(
                        "daemon queue scan: waiting for prompt settle window "
                        f"before retry ({retry_after_seconds:.2f}s)"
                    )
                    if self._shutdown_requested.wait(timeout=retry_after_seconds):
                        return processed
                    continue
                return processed
            prompt_path = ready_prompt_paths[0]
            if len(ready_prompt_paths) > 1:
                queued_names = ", ".join(path.name for path in ready_prompt_paths[1:])
                self._log(
                    "daemon queue scan: keeping queued prompts pending until the current prompt finishes: "
                    f"{queued_names}"
                )
            self._process_prompt(
                prompt_path,
                watcher_backend=watcher_backend or self.daemon_config.watch.backend,
            )
            return processed + 1

    def _scan_prompt_queue(self) -> tuple[list[Path], float | None]:
        candidates: list[Path] = []
        retry_after_seconds: float | None = None
        settle_seconds = self.daemon_config.watch.settle_seconds
        now = datetime.now(timezone.utc).timestamp()
        for path in sorted(self.daemon_config.prompt_path.iterdir(), key=lambda item: prompt_sort_key(item.name)):
            if path in self.in_progress_snapshot():
                continue
            if not is_prompt_candidate(path, self.daemon_config.queue):
                self._log(f"daemon queue scan: skipping non-candidate {path.name}")
                continue
            result_path = self._result_path_for_prompt(path)
            if result_path.exists():
                existing_status = self._existing_result_status(result_path)
                if existing_status == "completed":
                    result_path.unlink()
                    self._log(
                        "daemon queue scan: removing stale completed result for "
                        f"{path.name} and reprocessing prompt"
                    )
            try:
                stat_result = path.stat()
            except FileNotFoundError:
                continue
            if settle_seconds > 0 and now - stat_result.st_mtime < settle_seconds:
                remaining = settle_seconds - (now - stat_result.st_mtime)
                if retry_after_seconds is None or remaining < retry_after_seconds:
                    retry_after_seconds = max(remaining, 0.0)
                self._log(
                    "daemon queue scan: deferring "
                    f"{path.name} until settle window expires ({max(remaining, 0.0):.2f}s remaining)"
                )
                continue
            candidates.append(path)
        return candidates, retry_after_seconds

    def _emit_startup_banner(self, *, watcher_backend: str) -> None:
        for line in self._startup_banner_lines(watcher_backend=watcher_backend):
            print(line, file=self.progress_stream)
        self.progress_stream.flush()

    def _startup_banner_lines(self, *, watcher_backend: str) -> list[str]:
        lines: list[str] = [
            "=== dormammu daemonize ===",
            f"repo root: {self.app_config.repo_root.resolve()}",
            f"daemon config: {self.daemon_config.config_path}",
            f"prompt path: {self.daemon_config.prompt_path}",
            f"result path: {self.daemon_config.result_path}",
            (
                "watcher: "
                f"{watcher_backend} (requested={self.daemon_config.watch.backend}, "
                f"poll_interval={self._watcher_poll_interval_seconds(watcher_backend)}s, "
                f"settle={self.daemon_config.watch.settle_seconds}s)"
            ),
            (
                "prompt detection: "
                f"hidden_files={'ignore' if self.daemon_config.queue.ignore_hidden_files else 'include'}, "
                f"extensions={self._describe_allowed_extensions()}, "
                "replace_completed_result_on_requeued_prompt=yes, "
                "order=numeric-prefix -> alpha-prefix -> remaining-name"
            ),
            (
                "prompt lifecycle: each accepted prompt reuses the dormammu run loop and writes its result only after the loop reaches a terminal outcome"
            ),
        ]
        if self.daemon_config.goals is not None:
            goals = self.daemon_config.goals
            lines.append(
                f"goals: {goals.path} "
                f"(interval={goals.interval_minutes}m, "
                f"watching for .md files)"
            )
        else:
            lines.append("goals: disabled")
        if self.daemon_config.autonomous is not None and self.daemon_config.autonomous.enabled:
            auto = self.daemon_config.autonomous
            lines.append(
                f"autonomous: enabled "
                f"(interval={auto.interval_minutes}m, "
                f"focus={auto.focus}, "
                f"max_queued={auto.max_queued_tasks})"
            )
        else:
            lines.append("autonomous: disabled")
        return lines

    def _watcher_poll_interval_seconds(self, watcher_backend: str) -> int:
        if watcher_backend == "polling":
            return self.daemon_config.watch.poll_interval_seconds
        return EFFECTIVE_POLL_INTERVAL_SECONDS

    def _describe_allowed_extensions(self) -> str:
        if not self.daemon_config.queue.allowed_extensions:
            return "any"
        return ",".join(self.daemon_config.queue.allowed_extensions)

    def _log(self, message: str) -> None:
        print(message, file=self.progress_stream)
        self.progress_stream.flush()

    def _write_heartbeat(self, *, status: str) -> None:
        """Write a JSON heartbeat file so external monitors can detect hangs.

        The file contains ``pid``, ``status`` ("idle" | "busy"), and ``ts``
        (ISO-8601 UTC timestamp).  A stale or missing file indicates the daemon
        has crashed or hung.  The file is removed on clean shutdown.
        """
        if self._heartbeat_path is None:
            return
        try:
            import json as _json
            self._heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self._heartbeat_path.write_text(
                _json.dumps({
                    "pid": _get_pid(),
                    "status": status,
                    "ts": _iso_now(),
                }),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _remove_heartbeat(self) -> None:
        """Delete the heartbeat file on clean shutdown."""
        if self._heartbeat_path is not None:
            try:
                self._heartbeat_path.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Instance lock (prevents duplicate daemon processes)
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def _instance_lock(self) -> Generator[None, None, None]:
        """Acquire an exclusive per-queue daemon lock using a PID file.

        Raises :class:`DaemonAlreadyRunningError` immediately if another
        process already holds the lock (non-blocking attempt).  Falls back to
        a no-op on platforms that lack ``fcntl`` (e.g. Windows).

        The PID file contains the holding process's PID so operators can
        identify or kill the existing daemon.
        """
        if not _HAS_FCNTL:
            yield
            return

        self._pid_lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self._pid_lock_path.open("a+", encoding="utf-8")
        try:
            _fcntl.flock(lock_file, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError:
            lock_file.close()
            # Read the existing PID for a helpful error message.
            try:
                existing = self._pid_lock_path.read_text(encoding="utf-8").strip()
                pid_info = f" (existing daemon PID: {existing})" if existing else ""
            except OSError:
                pid_info = ""
            raise DaemonAlreadyRunningError(
                f"Another dormammu daemon is already running against "
                f"{self.daemon_config.prompt_path}{pid_info}.\n"
                "Stop it first or use a different prompt_path."
            )
        # Write our PID so operators can identify the process.
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        self._pid_lock_file = lock_file
        try:
            yield
        finally:
            try:
                _fcntl.flock(lock_file, _fcntl.LOCK_UN)
            except OSError:
                pass
            lock_file.close()
            self._pid_lock_file = None
            try:
                self._pid_lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _process_prompt(self, prompt_path: Path, *, watcher_backend: str) -> DaemonPromptResult:
        if hasattr(self.progress_stream, "reset_session_log"):
            log_path = self._session_progress_log_path(prompt_path)
            self.progress_stream.reset_session_log(log_path)
            for line in self._startup_banner_lines(watcher_backend=watcher_backend):
                self._log(line)
            self._log(f"progress log: {log_path}")
        with self._in_progress_lock:
            self._in_progress.add(prompt_path)
        started_at = _iso_now()
        sort_key = prompt_sort_key(prompt_path.name)
        result_path = self._result_path_for_prompt(prompt_path)
        self._log(
            "daemon prompt detected: "
            f"{prompt_path.name} (sort_key={sort_key}, watcher={watcher_backend}, result={result_path.name})"
        )
        status = "failed"
        error: str | None = None
        session_id: str | None = None
        plan_all_completed: bool | None = None
        next_pending_task: str | None = None
        loop_result: LoopRunResult | None = None
        interrupted = False
        lifecycle: LifecycleRecorder | None = None

        skipped = False
        try:
            if result_path.exists():
                result_path.unlink()
            try:
                prompt_text = prompt_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                self._log(
                    f"daemon prompt {prompt_path.name}: prompt file was deleted before processing; skipping"
                )
                skipped = True
                status = "skipped"
                error = "Prompt file was deleted before processing."
                # Jump to finally by re-raising a sentinel; handled as non-interrupted exit
                raise _PromptSkipped()
            self._log(
                "daemon prompt summary: "
                f"{summarize_prompt_goal(prompt_text, fallback=prompt_path.name)}"
            )
            session_repository, scoped_config, session_id = self._start_prompt_session(
                prompt_path=prompt_path,
                prompt_text=prompt_text,
            )
            lifecycle = LifecycleRecorder.for_execution(
                session_repository,
                scope="daemon",
                session_id=session_id,
                label=prompt_path.stem,
                default_metadata={"source": "daemon_runner", "entrypoint": "DaemonRunner._process_prompt"},
            )
            lifecycle.emit(
                event_type=LifecycleEventType.RUN_REQUESTED,
                role="daemon",
                stage="daemon",
                status="requested",
                payload=RunEventPayload(
                    source="daemon_runner",
                    entrypoint="DaemonRunner._process_prompt",
                    trigger="daemon_queue",
                    prompt_summary=prompt_text.splitlines()[0].strip() if prompt_text.strip() else None,
                ),
                metadata={"prompt_path": str(prompt_path)},
            )
            lifecycle.emit(
                event_type=LifecycleEventType.RUN_STARTED,
                role="daemon",
                stage="daemon",
                status="started",
                payload=RunEventPayload(
                    source="daemon_runner",
                    entrypoint="DaemonRunner._process_prompt",
                    trigger="daemon_queue",
                ),
            )
            lifecycle.emit(
                event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                role="daemon",
                stage="daemon",
                status="persisted",
                payload=ArtifactPersistedPayload(
                    artifact_kind="input_prompt",
                    summary="Persisted the daemon prompt into the active session workspace.",
                ),
                artifact_refs=(
                    self._daemon_artifact_writer(
                        base_dir=session_repository.dev_dir,
                        logs_dir=session_repository.logs_dir,
                        run_id=lifecycle.run_id,
                        session_id=session_id,
                    ).reference(
                        kind="input_prompt",
                        path=session_repository.state_file("PROMPT.md"),
                        label="input_prompt",
                        content_type="text/markdown",
                        created_at=_path_created_at(session_repository.state_file("PROMPT.md")),
                    ),
                ),
            )
            loop_result = self._run_prompt_loop(
                scoped_config=scoped_config,
                session_repository=session_repository,
                prompt_path=prompt_path,
                prompt_text=prompt_text,
                lifecycle=lifecycle,
            )
            plan_all_completed, next_pending_task = self._sync_plan_state(session_repository)
            status = loop_result.status
            if status == "completed" and not plan_all_completed:
                if run_result_has_clean_terminal_stage_evidence(loop_result):
                    self._log(
                        f"daemon prompt {prompt_path.name}: preserving completed status "
                        "because terminal stage results completed cleanly despite stale PLAN sync"
                    )
                else:
                    status = "failed"
                    error = "Loop returned completed but session PLAN.md is not fully complete."
            elif status != "completed":
                error = self._terminal_error_message(loop_result, next_pending_task)
        except _PromptSkipped:
            pass  # status/error already set; handled cleanly in finally
        except KeyboardInterrupt:
            interrupted = True
            status = "interrupted"
            error = "Interrupted by user."
            self._log(f"daemon prompt {prompt_path.name}: interrupted by user; preserving source prompt file")
        except Exception as exc:
            status = "failed"
            error = str(exc)
        finally:
            completed_at = _iso_now()
            prompt_result = DaemonPromptResult(
                prompt_path=prompt_path,
                result_path=result_path,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                watcher_backend=watcher_backend,
                sort_key=sort_key,
                session_id=session_id,
                daemon_run_id=lifecycle.run_id if lifecycle is not None else None,
                run_result=loop_result,
                error=error,
                plan_all_completed=plan_all_completed,
                next_pending_task=next_pending_task,
            )
            if not interrupted and not skipped:
                prompt_result = self._publish_result_report(prompt_result)
            with self._in_progress_lock:
                self._in_progress.discard(prompt_path)
            result_report_ref = self._result_report_artifact_ref(prompt_result)
            if lifecycle is not None and result_report_ref is not None:
                lifecycle.emit(
                    event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                    role="daemon",
                    stage="daemon",
                    status="persisted",
                    payload=ArtifactPersistedPayload(
                        artifact_kind="result_report",
                        summary="Persisted the daemon result report.",
                    ),
                    artifact_refs=(result_report_ref,),
                )
            if lifecycle is not None:
                lifecycle.emit(
                    event_type=LifecycleEventType.RUN_FINISHED,
                    role="daemon",
                    stage="daemon",
                    status=status,
                    payload=RunEventPayload(
                        source="daemon_runner",
                        entrypoint="DaemonRunner._process_prompt",
                        attempts_completed=(loop_result.attempts_completed if loop_result else None),
                        retries_used=(loop_result.retries_used if loop_result else None),
                        supervisor_verdict=(loop_result.supervisor_verdict if loop_result else None),
                        outcome=status,
                        error=error,
                    ),
                    artifact_refs=(result_report_ref,) if result_report_ref is not None else (),
                )
            print(f"daemon prompt {prompt_path.name}: {status} -> {result_path}", file=self.progress_stream)
            self.progress_stream.flush()
            if interrupted:
                raise KeyboardInterrupt()
            return prompt_result

    def _start_prompt_session(
        self,
        *,
        prompt_path: Path,
        prompt_text: str,
    ) -> tuple[StateRepository, AppConfig, str]:
        goal = summarize_prompt_goal(prompt_text, fallback=f"Process daemon prompt {prompt_path.name}")
        roadmap_phase_id = infer_primary_roadmap_phase_id(goal=goal, prompt_text=prompt_text) or "phase_4"
        self.repository.start_new_session(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=[roadmap_phase_id],
        )
        session_state = self.repository.read_session_state()
        session_id = str(session_state.get("active_session_id") or session_state.get("session_id") or "").strip()
        if not session_id:
            raise RuntimeError("daemonize failed to determine the new session id.")
        session_repository = StateRepository(self.app_config, session_id=session_id)
        scoped_config = self.app_config.with_overrides(
            dev_dir=session_repository.dev_dir,
            logs_dir=session_repository.logs_dir,
        )
        scoped_repository = StateRepository(scoped_config, session_id=session_id)
        scoped_repository.persist_input_prompt(prompt_text=prompt_text, source_path=prompt_path)
        return scoped_repository, scoped_config, session_id

    def _run_prompt_loop(
        self,
        *,
        scoped_config: AppConfig,
        session_repository: StateRepository,
        prompt_path: Path,
        prompt_text: str,
        lifecycle: LifecycleRecorder | None = None,
    ) -> LoopRunResult:
        enriched_text = build_guidance_prompt(
            prompt_text,
            guidance_files=scoped_config.guidance_files,
            repo_root=scoped_config.repo_root,
            runtime_paths_text=scoped_config.runtime_path_prompt(),
        )
        goal_file_path = self._extract_goal_file_path(prompt_text)
        request_class = resolve_request_class(
            prompt_text,
            workflow_state=session_repository.read_workflow_state(),
        )

        # When an agents config is present, use the full role-based pipeline.
        if scoped_config.agents is not None:
            evaluator_config = (
                self.daemon_config.goals.evaluator
                if self.daemon_config.goals is not None
                else None
            )
            return PipelineRunner(
                scoped_config,
                scoped_config.agents,
                repository=session_repository,
                progress_stream=self.progress_stream,
                stop_event=self._shutdown_requested,
            ).run(
                enriched_text,
                stem=prompt_path.stem,
                goal_file_path=goal_file_path,
                evaluator_config=evaluator_config,
            )

        if request_class == "direct_response":
            direct_agents = AgentsConfig()
            return PipelineRunner(
                scoped_config.with_overrides(agents=direct_agents),
                direct_agents,
                repository=session_repository,
                progress_stream=self.progress_stream,
                stop_event=self._shutdown_requested,
            ).run(
                enriched_text,
                stem=prompt_path.stem,
                goal_file_path=goal_file_path,
            )

        # Default: enforce refine -> plan before the single-agent loop.
        agent_cli = self._resolve_agent_cli(scoped_config)
        prelude_agents = AgentsConfig()
        PipelineRunner(
            scoped_config.with_overrides(agents=prelude_agents),
            prelude_agents,
            repository=session_repository,
            progress_stream=self.progress_stream,
            stop_event=self._shutdown_requested,
        ).run_refine_and_plan(
            enriched_text,
            stem=prompt_path.stem,
            enable_plan_evaluator=goal_file_path is not None,
        )
        if lifecycle is not None:
            lifecycle.emit(
                event_type=LifecycleEventType.SUPERVISOR_HANDOFF,
                role="planner",
                stage="developer",
                status="handoff",
                payload=SupervisorHandoffPayload(
                    from_role="planner",
                    to_role="developer",
                    reason="Mandatory refine/plan prelude completed; handing off to the supervised developer loop.",
                    attempt=1,
                ),
            )

        request = LoopRunRequest(
            cli_path=agent_cli,
            prompt_text=build_supervisor_handoff_prompt_for_repository(
                repository=session_repository,
                agents_dir=scoped_config.agents_dir,
                original_prompt_text=enriched_text,
                runtime_paths_text=scoped_config.runtime_path_prompt(),
                patterns_text=session_repository.read_patterns_text(),
            ),
            repo_root=scoped_config.repo_root,
            workdir=scoped_config.repo_root,
            input_mode="auto",
            prompt_flag=None,
            extra_args=(),
            run_label=f"daemon-{prompt_path.stem}",
            max_retries=DEFAULT_DAEMON_MAX_RETRIES,
            expected_roadmap_phase_id=self._expected_roadmap_phase_id(session_repository),
        )
        return LoopRunner(
            scoped_config,
            repository=session_repository,
            adapter=CliAdapter(
                scoped_config,
                live_output_stream=self.progress_stream,
                stop_event=self._shutdown_requested,
            ),
            progress_stream=self.progress_stream,
        ).run(request)

    def _expected_roadmap_phase_id(self, repository: StateRepository) -> str:
        workflow_state = repository.read_workflow_state()
        roadmap = workflow_state.get("roadmap", {})
        active_phase_ids = roadmap.get("active_phase_ids", [])
        if isinstance(active_phase_ids, list):
            for phase_id in active_phase_ids:
                if isinstance(phase_id, str) and phase_id.strip():
                    return phase_id
        return "phase_4"

    def _resolve_agent_cli(self, config: AppConfig) -> Path:
        if config.active_agent_cli is not None:
            return config.active_agent_cli
        raise RuntimeError(
            "daemonize requires active_agent_cli in dormammu.json or ~/.dormammu/config. "
            "It now reuses the normal dormammu run loop instead of per-phase daemon CLI settings."
        )

    def _extract_goal_file_path(self, prompt_text: str) -> Path | None:
        """Extract the original goal file path from the dormammu:goal_source tag.

        Returns ``None`` when the tag is absent (prompt was not generated by the
        goals scheduler). Raises when the tag is present but the referenced goal
        file no longer exists, because post-commit evaluation is mandatory for
        goals-scheduler prompts.
        """
        match = _GOAL_SOURCE_RE.search(prompt_text)
        if match is None:
            return None
        raw_path = match.group(1).strip()
        if not raw_path:
            return None
        candidate = Path(raw_path)
        if not candidate.exists():
            raise RuntimeError(
                "daemon: goal_source path not found for mandatory evaluator: "
                f"{raw_path}"
            )
        return candidate

    def _terminal_error_message(self, loop_result: LoopRunResult, next_pending_task: str | None) -> str:
        if loop_result.status == "failed":
            suffix = f" Next pending PLAN task: {next_pending_task}." if next_pending_task else ""
            return f"Loop retry budget was exhausted before PLAN.md completed.{suffix}"
        if loop_result.status == "blocked":
            return "Loop stopped because the configured coding-agent CLIs were blocked."
        if loop_result.status == "manual_review_needed":
            return "Loop stopped because manual review is required."
        return f"Loop finished with terminal status: {loop_result.status}."

    def _render_result_report(
        self,
        prompt_result: DaemonPromptResult,
    ) -> str:
        return ResultReportAuthor(
            self.app_config,
            progress_stream=self.progress_stream,
            stop_event=self._shutdown_requested,
        ).render(prompt_result)

    def _render_result_report_with_fallback(
        self,
        prompt_result: DaemonPromptResult,
    ) -> tuple[DaemonPromptResult, str]:
        try:
            return prompt_result, self._render_result_report(prompt_result)
        except Exception as exc:
            self._log(
                "daemon result report fallback: configured CLI authoring failed for "
                f"{prompt_result.prompt_path.name}: {exc}"
            )
            fallback_note = (
                "Configured CLI result report authoring failed; "
                f"wrote fallback report instead. Cause: {exc}"
            )
            combined_error = fallback_note
            if prompt_result.error:
                combined_error = f"{prompt_result.error}\n\n{fallback_note}"
            fallback_result = replace(prompt_result, error=combined_error)
            return fallback_result, render_result_markdown(fallback_result)

    def _publish_result_report(
        self,
        prompt_result: DaemonPromptResult,
    ) -> DaemonPromptResult:
        prompt_result, markdown = self._render_result_report_with_fallback(prompt_result)
        writer = self._daemon_result_artifact_writer(prompt_result)
        temp_result_path = prompt_result.result_path.with_name(
            f".{prompt_result.result_path.name}.tmp"
        )
        temp_ref = writer.write_markdown_report(
            kind="result_report",
            markdown=markdown,
            path=temp_result_path,
            label="result_report",
        )
        try:
            if prompt_result.prompt_path.exists():
                prompt_result.prompt_path.unlink()
            temp_result_path.replace(prompt_result.result_path)
        except Exception:
            temp_result_path.unlink(missing_ok=True)
            raise
        artifact_ref = writer.reference(
            kind="result_report",
            path=prompt_result.result_path,
            label="result_report",
            content_type="text/markdown",
            created_at=temp_ref.created_at,
        )
        return replace(prompt_result, daemon_artifacts=(artifact_ref,))

    def _daemon_artifact_writer(
        self,
        *,
        base_dir: Path,
        logs_dir: Path | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> ArtifactWriter:
        return ArtifactWriter(base_dir=base_dir, logs_dir=logs_dir).bind(
            run_id=run_id,
            role="daemon",
            stage_name="daemon",
            session_id=session_id,
        )

    def _daemon_result_artifact_writer(
        self,
        prompt_result: DaemonPromptResult,
    ) -> ArtifactWriter:
        return self._daemon_artifact_writer(
            base_dir=prompt_result.result_path.parent,
            run_id=prompt_result.daemon_run_id or prompt_result.latest_run_id,
            session_id=prompt_result.session_id,
        )

    def _result_report_artifact_ref(
        self,
        prompt_result: DaemonPromptResult,
    ) -> ArtifactRef | None:
        artifact_ref = prompt_result.result_report_artifact
        if artifact_ref is not None:
            return artifact_ref
        if not prompt_result.result_path.exists():
            return None
        return self._daemon_result_artifact_writer(prompt_result).reference(
            kind="result_report",
            path=prompt_result.result_path,
            label="result_report",
            content_type="text/markdown",
            created_at=_path_created_at(prompt_result.result_path),
        )

    def _sync_plan_state(self, session_repository: StateRepository) -> tuple[bool | None, str | None]:
        session_repository.sync_operator_state()
        session_state = session_repository.read_session_state()
        workflow_state = session_repository.read_workflow_state()
        if resolve_request_class("", workflow_state=workflow_state) == "direct_response":
            return True, None
        task_sync = session_state.get("task_sync")
        if not isinstance(task_sync, Mapping):
            return None, None
        all_completed_raw = task_sync.get("all_completed")
        next_pending_raw = task_sync.get("next_pending_task")
        all_completed = bool(all_completed_raw) if all_completed_raw is not None else None
        next_pending_task = next_pending_raw.strip() if isinstance(next_pending_raw, str) and next_pending_raw.strip() else None
        return all_completed, next_pending_task

    def _existing_result_status(self, result_path: Path) -> str | None:
        try:
            text = result_path.read_text(encoding="utf-8")
        except OSError:
            return None
        match = _RESULT_STATUS_RE.search(text)
        if match is None:
            return None
        return match.group(1).strip()

    def _result_path_for_prompt(self, prompt_path: Path) -> Path:
        return self.daemon_config.result_path / f"{prompt_path.stem}_RESULT.md"

    def _session_progress_log_path(self, prompt_path: Path) -> Path:
        return self.daemon_config.result_path.parent / "progress" / f"{prompt_path.stem}_progress.log"
