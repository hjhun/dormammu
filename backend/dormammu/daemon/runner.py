from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time
from typing import Mapping, TextIO

from dormammu.config import AppConfig
from dormammu.daemon.models import DaemonConfig, DaemonPromptResult
from dormammu.daemon.queue import is_prompt_candidate, prompt_sort_key
from dormammu.daemon.reports import render_result_markdown
from dormammu.daemon.watchers import EFFECTIVE_POLL_INTERVAL_SECONDS, PromptWatcher, build_watcher
from dormammu.guidance import build_guidance_prompt
from dormammu.loop_runner import LoopRunResult, LoopRunRequest, LoopRunner
from dormammu.state import StateRepository
from dormammu.state.models import summarize_prompt_goal


DEFAULT_DAEMON_MAX_RETRIES = 49
_RESULT_STATUS_RE = re.compile(r"^- Status: `([^`]+)`$", re.MULTILINE)


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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

    def run_forever(self) -> int:
        self.daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
        self.daemon_config.result_path.mkdir(parents=True, exist_ok=True)
        watcher = self.watcher or build_watcher(
            self.daemon_config.prompt_path,
            self.daemon_config.watch,
            event_logger=self._log,
        )
        self._emit_startup_banner(watcher_backend=watcher.backend_name)
        watcher.start()
        try:
            while True:
                processed = self.run_pending_once(watcher_backend=watcher.backend_name)
                if processed == 0:
                    watcher.wait_for_changes()
        finally:
            watcher.close()

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
                    time.sleep(retry_after_seconds)
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
            if path in self._in_progress:
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
        print("=== dormammu daemonize ===", file=self.progress_stream)
        print(f"repo root: {self.app_config.repo_root.resolve()}", file=self.progress_stream)
        print(f"daemon config: {self.daemon_config.config_path}", file=self.progress_stream)
        print(f"prompt path: {self.daemon_config.prompt_path}", file=self.progress_stream)
        print(f"result path: {self.daemon_config.result_path}", file=self.progress_stream)
        print(
            "watcher: "
            f"{watcher_backend} (requested={self.daemon_config.watch.backend}, "
            f"poll_interval={self._watcher_poll_interval_seconds(watcher_backend)}s, "
            f"settle={self.daemon_config.watch.settle_seconds}s)",
            file=self.progress_stream,
        )
        print(
            "prompt detection: "
            f"hidden_files={'ignore' if self.daemon_config.queue.ignore_hidden_files else 'include'}, "
            f"extensions={self._describe_allowed_extensions()}, "
            "replace_completed_result_on_requeued_prompt=yes, "
            "order=numeric-prefix -> alpha-prefix -> remaining-name",
            file=self.progress_stream,
        )
        print(
            "prompt lifecycle: each accepted prompt reuses the dormammu run loop and writes its result only after the loop reaches a terminal outcome",
            file=self.progress_stream,
        )
        self.progress_stream.flush()

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

    def _process_prompt(self, prompt_path: Path, *, watcher_backend: str) -> DaemonPromptResult:
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

        try:
            if result_path.exists():
                result_path.unlink()
            prompt_text = prompt_path.read_text(encoding="utf-8")
            session_repository, scoped_config, session_id = self._start_prompt_session(
                prompt_path=prompt_path,
                prompt_text=prompt_text,
            )
            loop_result = self._run_prompt_loop(
                scoped_config=scoped_config,
                session_repository=session_repository,
                prompt_path=prompt_path,
                prompt_text=prompt_text,
            )
            plan_all_completed, next_pending_task = self._sync_plan_state(session_repository)
            status = loop_result.status
            if status == "completed" and not plan_all_completed:
                status = "failed"
                error = "Loop returned completed but session PLAN.md is not fully complete."
            elif status != "completed":
                error = self._terminal_error_message(loop_result, next_pending_task)
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
                error=error,
                plan_all_completed=plan_all_completed,
                next_pending_task=next_pending_task,
                attempts_completed=(loop_result.attempts_completed if loop_result else None),
                latest_run_id=(loop_result.latest_run_id if loop_result else None),
                supervisor_verdict=(loop_result.supervisor_verdict if loop_result else None),
                supervisor_report_path=(loop_result.report_path if loop_result else None),
                continuation_prompt_path=(loop_result.continuation_prompt_path if loop_result else None),
            )
            if not interrupted:
                self._write_result_report_from_result(prompt_result)
                if prompt_path.exists():
                    prompt_path.unlink()
            self._in_progress.discard(prompt_path)
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
        self.repository.start_new_session(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=["phase_4"],
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
    ) -> LoopRunResult:
        agent_cli = self._resolve_agent_cli(scoped_config)
        request = LoopRunRequest(
            cli_path=agent_cli,
            prompt_text=build_guidance_prompt(
                prompt_text,
                guidance_files=scoped_config.guidance_files,
                repo_root=scoped_config.repo_root,
            ),
            repo_root=scoped_config.repo_root,
            workdir=scoped_config.repo_root,
            input_mode="auto",
            prompt_flag=None,
            extra_args=(),
            run_label=f"daemon-{prompt_path.stem}",
            max_retries=DEFAULT_DAEMON_MAX_RETRIES,
            expected_roadmap_phase_id="phase_4",
        )
        return LoopRunner(
            scoped_config,
            repository=session_repository,
            progress_stream=self.progress_stream,
        ).run(request)

    def _resolve_agent_cli(self, config: AppConfig) -> Path:
        if config.active_agent_cli is not None:
            return config.active_agent_cli
        raise RuntimeError(
            "daemonize requires active_agent_cli in dormammu.json or ~/.dormammu/config. "
            "It now reuses the normal dormammu run loop instead of per-phase daemon CLI settings."
        )

    def _terminal_error_message(self, loop_result: LoopRunResult, next_pending_task: str | None) -> str:
        if loop_result.status == "failed":
            suffix = f" Next pending PLAN task: {next_pending_task}." if next_pending_task else ""
            return f"Loop retry budget was exhausted before PLAN.md completed.{suffix}"
        if loop_result.status == "blocked":
            return "Loop stopped because the configured coding-agent CLIs were blocked."
        if loop_result.status == "manual_review_needed":
            return "Loop stopped because manual review is required."
        return f"Loop finished with terminal status: {loop_result.status}."

    def _write_result_report_from_result(self, prompt_result: DaemonPromptResult) -> None:
        prompt_result.result_path.write_text(render_result_markdown(prompt_result), encoding="utf-8")

    def _sync_plan_state(self, session_repository: StateRepository) -> tuple[bool | None, str | None]:
        session_repository.sync_operator_state()
        session_state = session_repository.read_session_state()
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
