from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import TextIO

from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.agent.models import AgentRunStarted
from dormammu.config import AppConfig
from dormammu.daemon.models import DaemonConfig, DaemonPromptResult, PHASE_SEQUENCE, PhaseExecutionConfig, PhaseExecutionResult
from dormammu.daemon.queue import is_prompt_candidate, prompt_sort_key
from dormammu.daemon.reports import render_result_markdown
from dormammu.daemon.watchers import PromptWatcher, build_watcher
from dormammu.guidance import build_guidance_prompt
from dormammu.state import StateRepository
from dormammu.state.models import summarize_prompt_goal


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
        self._processed_successes: set[Path] = set()
        self._in_progress: set[Path] = set()

    def run_forever(self) -> int:
        self.daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
        self.daemon_config.result_path.mkdir(parents=True, exist_ok=True)
        watcher = self.watcher or build_watcher(self.daemon_config.prompt_path, self.daemon_config.watch)
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
        for prompt_path in self._ready_prompt_paths():
            self._process_prompt(
                prompt_path,
                watcher_backend=watcher_backend or self.daemon_config.watch.backend,
            )
            processed += 1
        return processed

    def _ready_prompt_paths(self) -> list[Path]:
        candidates: list[Path] = []
        settle_seconds = self.daemon_config.watch.settle_seconds
        now = datetime.now(timezone.utc).timestamp()
        for path in sorted(self.daemon_config.prompt_path.iterdir(), key=lambda item: prompt_sort_key(item.name)):
            if path in self._processed_successes or path in self._in_progress:
                continue
            if not is_prompt_candidate(path, self.daemon_config.queue):
                continue
            result_path = self._result_path_for_prompt(path)
            if result_path.exists():
                self._processed_successes.add(path)
                continue
            try:
                stat_result = path.stat()
            except FileNotFoundError:
                continue
            if settle_seconds > 0 and now - stat_result.st_mtime < settle_seconds:
                continue
            candidates.append(path)
        return candidates

    def _process_prompt(self, prompt_path: Path, *, watcher_backend: str) -> DaemonPromptResult:
        self._in_progress.add(prompt_path)
        started_at = _iso_now()
        sort_key = prompt_sort_key(prompt_path.name)
        result_path = self._result_path_for_prompt(prompt_path)
        session_id: str | None = None
        phase_results: list[PhaseExecutionResult] = []
        status = "completed"
        error: str | None = None
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8")
            goal = summarize_prompt_goal(prompt_text, fallback=f"Process daemon prompt {prompt_path.name}")
            self.repository.start_new_session(
                goal=goal,
                prompt_text=prompt_text,
                active_roadmap_phase_ids=["phase_5", "phase_7"],
            )
            session_state = self.repository.read_session_state()
            for candidate_key in ("active_session_id", "session_id"):
                candidate = session_state.get(candidate_key)
                if isinstance(candidate, str) and candidate.strip():
                    session_id = candidate
                    break
            session_repository = StateRepository(self.app_config, session_id=session_id)
            scoped_config = self.app_config.with_overrides(
                dev_dir=session_repository.dev_dir,
                logs_dir=session_repository.logs_dir,
            )
            session_repository = StateRepository(scoped_config, session_id=session_id)
            session_repository.persist_input_prompt(prompt_text=prompt_text, source_path=prompt_path)
            for phase_name in PHASE_SEQUENCE:
                phase_result = self._run_phase(
                    scoped_config,
                    session_repository,
                    phase_config=self.daemon_config.phases[phase_name],
                    original_prompt=prompt_text,
                    prompt_path=prompt_path,
                )
                phase_results.append(phase_result)
                if phase_result.exit_code != 0:
                    status = "failed"
                    error = phase_result.error or f"Phase {phase_name} exited with code {phase_result.exit_code}."
                    break
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
                phase_results=tuple(phase_results),
                error=error,
            )
            result_path.write_text(render_result_markdown(prompt_result), encoding="utf-8")
            if status == "completed":
                self._processed_successes.add(prompt_path)
            self._in_progress.discard(prompt_path)
            print(f"daemon prompt {prompt_path.name}: {status} -> {result_path}", file=self.progress_stream)
            self.progress_stream.flush()
            return prompt_result

    def _run_phase(
        self,
        scoped_config: AppConfig,
        session_repository: StateRepository,
        *,
        phase_config: PhaseExecutionConfig,
        original_prompt: str,
        prompt_path: Path,
    ) -> PhaseExecutionResult:
        adapter = CliAdapter(scoped_config)
        skill_text = phase_config.skill_path.read_text(encoding="utf-8").rstrip()
        request = AgentRunRequest(
            cli_path=phase_config.agent_cli.path,
            prompt_text=build_guidance_prompt(
                self._compose_phase_prompt(
                    phase_name=phase_config.phase_name,
                    skill_name=phase_config.skill_name,
                    skill_path=phase_config.skill_path,
                    skill_text=skill_text,
                    original_prompt=original_prompt,
                    prompt_path=prompt_path,
                ),
                guidance_files=scoped_config.guidance_files,
                repo_root=scoped_config.repo_root,
            ),
            repo_root=scoped_config.repo_root,
            workdir=scoped_config.repo_root,
            input_mode=phase_config.agent_cli.input_mode,
            prompt_flag=phase_config.agent_cli.prompt_flag,
            extra_args=phase_config.agent_cli.extra_args,
            run_label=f"daemon-{phase_config.phase_name}",
        )
        started_ref: dict[str, AgentRunStarted] = {}

        def _handle_started(started: AgentRunStarted) -> None:
            started_ref["value"] = started
            session_repository.record_current_run(started)

        try:
            result = adapter.run_once(request, on_started=_handle_started)
            session_repository.record_latest_run(result)
            return PhaseExecutionResult(
                phase_name=phase_config.phase_name,
                cli_path=phase_config.agent_cli.path,
                exit_code=result.exit_code,
                run_id=result.run_id,
                started_at=result.started_at,
                completed_at=result.completed_at,
                stdout_path=result.stdout_path,
                stderr_path=result.stderr_path,
                prompt_path=result.prompt_path,
                metadata_path=result.metadata_path,
                command=tuple(result.command),
                error=None if result.exit_code == 0 else f"Phase exited with code {result.exit_code}",
            )
        except Exception as exc:
            started = started_ref.get("value")
            return PhaseExecutionResult(
                phase_name=phase_config.phase_name,
                cli_path=phase_config.agent_cli.path,
                exit_code=2,
                run_id=started.run_id if started else None,
                started_at=started.started_at if started else None,
                completed_at=_iso_now(),
                stdout_path=started.stdout_path if started else None,
                stderr_path=started.stderr_path if started else None,
                prompt_path=started.prompt_path if started else None,
                metadata_path=started.metadata_path if started else None,
                command=tuple(started.command) if started else (),
                error=str(exc),
            )

    def _compose_phase_prompt(
        self,
        *,
        phase_name: str,
        skill_name: str | None,
        skill_path: Path,
        skill_text: str,
        original_prompt: str,
        prompt_path: Path,
    ) -> str:
        skill_label = skill_name or skill_path.as_posix()
        return (
            f"Phase: {phase_name}\n"
            f"Prompt file: {prompt_path.name}\n\n"
            f"Required skill: {skill_label}\n"
            f"Skill file: {skill_path}\n\n"
            "Follow the skill document below as a required phase instruction.\n\n"
            f"Begin skill from {skill_path}:\n"
            f"{skill_text}\n"
            f"End skill from {skill_path}.\n\n"
            "Keep the repository `.dev` state aligned with the work you perform.\n"
            "Preserve resumability and leave enough state for the next phase.\n\n"
            "Original prompt:\n"
            f"{original_prompt.rstrip()}\n"
        )

    def _result_path_for_prompt(self, prompt_path: Path) -> Path:
        return self.daemon_config.result_path / f"{prompt_path.stem}_RESULT.md"
