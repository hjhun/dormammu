from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Mapping, Sequence

from dormammu._utils import iso_now as _iso_now
from dormammu.agent.models import AgentRunResult, AgentRunStarted
from dormammu.config import AppConfig
from dormammu.guidance import resolve_guidance_files
from dormammu.state.models import (
    ManagedWorktreeState,
    default_dashboard_context,
    default_plan_context,
    default_session_state,
    default_workflow_state,
    discover_repo_guidance,
    prompt_fingerprint,
    summarize_prompt_goal,
)
from dormammu.state.operator_sync import OperatorSync
from dormammu.state.persistence import (
    deep_merge as _deep_merge,
    ensure_json_file as _ensure_json_file,
    read_json as _read_json,
    write_json as _write_json,
)
from dormammu.state.session_manager import SessionManager
from dormammu.worktree import ManagedWorktree


@dataclass(frozen=True, slots=True)
class BootstrapArtifacts:
    dashboard: Path
    plan: Path
    tasks: Path
    session: Path
    workflow_state: Path
    logs_dir: Path
    prompt: Path | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "dashboard": str(self.dashboard),
            "plan": str(self.plan),
            "tasks": str(self.tasks),
            "session": str(self.session),
            "workflow_state": str(self.workflow_state),
            "logs_dir": str(self.logs_dir),
        }
        if self.prompt is not None:
            payload["prompt"] = str(self.prompt)
        return payload


class StateRepository:
    """Create and maintain the bootstrap `.dev/` state files."""

    CORE_STATE_FILENAMES = (
        "DASHBOARD.md",
        "PLAN.md",
        "session.json",
        "workflow_state.json",
    )
    OPTIONAL_STATE_FILENAMES = (
        "supervisor_report.md",
        "continuation_prompt.txt",
    )
    ROOT_OPERATOR_MIRROR_FILENAMES = (
        "DASHBOARD.md",
        "PLAN.md",
        "TASKS.md",
        "WORKFLOWS.md",
    )

    def __init__(self, config: AppConfig, session_id: str | None = None) -> None:
        self.config = config
        self.base_dev_dir = config.base_dev_dir
        self.templates_dir = config.templates_dir / "dev"
        self.sessions_dir = config.sessions_dir
        self._session_mgr = SessionManager(
            config,
            self.base_dev_dir,
            self.sessions_dir,
            legacy_base_dev_dir=config.repo_dev_dir,
        )
        self._op_sync = OperatorSync(config, self.base_dev_dir)
        self.session_id = self._normalize_session_id(session_id) if session_id else None
        self.dev_dir = (
            self.sessions_dir / self.session_id
            if self.session_id is not None
            else config.dev_dir
        )
        self.logs_dir = self.dev_dir / "logs"

    def for_session(self, session_id: str) -> StateRepository:
        return StateRepository(self.config, session_id=session_id)

    def state_file(self, name: str) -> Path:
        return self.dev_dir / name

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def ensure_bootstrap_state(
        self,
        *,
        goal: str | None = None,
        prompt_text: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
    ) -> BootstrapArtifacts:
        if self.session_id is None:
            return self._ensure_root_bootstrap_state(
                goal=goal,
                prompt_text=prompt_text,
                active_roadmap_phase_ids=active_roadmap_phase_ids,
            )
        return self._ensure_session_bootstrap_state(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=active_roadmap_phase_ids,
        )

    def _ensure_root_bootstrap_state(
        self,
        *,
        goal: str | None = None,
        prompt_text: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
    ) -> BootstrapArtifacts:
        timestamp = _iso_now()
        self._ensure_workspace_roots()
        self.base_dev_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        legacy_session_payload = self._session_mgr.read_legacy_root_session_payload()
        active_session_id = self._session_mgr.read_active_session_id()
        if active_session_id is None:
            active_session_id = self._session_mgr.migrate_legacy_root_snapshot(
                timestamp=timestamp
            )
        if active_session_id is None:
            active_session_id = self._session_mgr.generated_session_id(timestamp)

        self._ensure_patterns_file()
        session_repository = self.for_session(active_session_id)
        artifacts = session_repository._ensure_session_bootstrap_state(
            goal=goal,
            prompt_text=prompt_text,
            active_roadmap_phase_ids=active_roadmap_phase_ids,
        )
        if legacy_session_payload is not None:
            migrated_session = _read_json(session_repository.state_file("session.json"))
            merged_session = _deep_merge(migrated_session, legacy_session_payload)
            merged_session["session_id"] = active_session_id
            _write_json(session_repository.state_file("session.json"), merged_session)
        self._write_root_index_for_session(
            session_repository=session_repository,
            timestamp=timestamp,
        )
        return artifacts

    def _ensure_session_bootstrap_state(
        self,
        *,
        goal: str | None = None,
        prompt_text: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
    ) -> BootstrapArtifacts:
        timestamp = _iso_now()
        roadmap_phase_ids = list(active_roadmap_phase_ids or ["phase_1"])
        guidance = discover_repo_guidance(
            self.config.repo_root,
            rule_paths=resolve_guidance_files(self.config),
        )
        session_id = (
            self._session_mgr.current_session_id(self.dev_dir / "session.json")
            or self.session_id
        )
        resolved_goal = (
            goal
            or self._existing_goal()
            or summarize_prompt_goal(
                prompt_text,
                fallback="Bootstrap dormammu in the current repository.",
            )
        )

        self._ensure_workspace_roots()
        self.dev_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        dashboard_path = self.state_file("DASHBOARD.md")
        plan_path = self.state_file("PLAN.md")
        tasks_path = self.state_file("TASKS.md")
        session_path = self.state_file("session.json")
        workflow_path = self.state_file("workflow_state.json")
        state_root = self._state_root_display()
        self._ensure_plan_file(plan_path)

        existing_goal = self._existing_goal()
        should_reset_for_goal_change = (
            goal is not None
            and existing_goal is not None
            and goal.strip()
            and goal.strip() != existing_goal.strip()
        )

        if should_reset_for_goal_change or self._should_regenerate_operator_state(
            prompt_text=prompt_text,
            dashboard_path=dashboard_path,
            plan_path=plan_path,
        ):
            self._reset_bootstrap_state(
                goal=resolved_goal,
                prompt_text=prompt_text,
                roadmap_phase_ids=roadmap_phase_ids,
                session_id=session_id or self._session_mgr.generated_session_id(timestamp),
                timestamp=timestamp,
            )
            self._sync_root_index(timestamp=timestamp)
            return self._artifacts()

        dashboard_context = default_dashboard_context(
            goal=resolved_goal,
            roadmap_phase_ids=roadmap_phase_ids,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )
        plan_context = default_plan_context(
            goal=resolved_goal,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )

        self._ensure_template_file(
            dashboard_path,
            "dashboard.md.tmpl",
            dashboard_context.render_values(),
        )
        self._ensure_template_file(plan_path, "plan.md.tmpl", plan_context.render_values())
        self._ensure_tasks_file(
            tasks_path,
            plan_path=plan_path,
            values=plan_context.render_values(),
        )

        session_defaults = default_session_state(
            timestamp=timestamp,
            app_name=self.config.app_name,
            roadmap_phase_ids=roadmap_phase_ids,
            goal=resolved_goal,
            state_root=state_root,
            prompt_text=prompt_text,
            repo_guidance=guidance,
            session_id=session_id,
        )
        workflow_defaults = default_workflow_state(
            timestamp=timestamp,
            roadmap_phase_ids=roadmap_phase_ids,
            goal=resolved_goal,
            state_root=state_root,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )

        _ensure_json_file(session_path, session_defaults)
        _ensure_json_file(workflow_path, workflow_defaults)
        self._op_sync.refresh_active_roadmap_phase_ids(
            session_path=session_path,
            workflow_path=workflow_path,
            roadmap_phase_ids=roadmap_phase_ids,
            timestamp=timestamp,
        )
        self._sync_operator_state(
            session_path=session_path,
            workflow_path=workflow_path,
            operator_task_path=self._operator_task_path(),
            timestamp=timestamp,
        )
        self._sync_root_index(timestamp=timestamp)
        return self._artifacts()

    def _should_regenerate_operator_state(
        self,
        *,
        prompt_text: str | None,
        dashboard_path: Path,
        plan_path: Path,
    ) -> bool:
        if not dashboard_path.exists() or not plan_path.exists():
            return False
        incoming_fingerprint = prompt_fingerprint(prompt_text)
        if incoming_fingerprint is None:
            return False
        stored_fingerprint = self._stored_prompt_fingerprint()
        if stored_fingerprint is None:
            return False
        return stored_fingerprint != incoming_fingerprint

    def _stored_prompt_fingerprint(self) -> str | None:
        for candidate in (
            self.state_file("session.json"),
            self.state_file("workflow_state.json"),
        ):
            if not candidate.exists():
                continue
            try:
                payload = _read_json(candidate)
            except Exception:
                continue
            bootstrap = payload.get("bootstrap")
            if not isinstance(bootstrap, Mapping):
                continue
            fingerprint = bootstrap.get("prompt_fingerprint")
            if isinstance(fingerprint, str) and fingerprint.strip():
                return fingerprint
            for key in ("prompt_path", "global_prompt_path"):
                prompt_path_value = bootstrap.get(key)
                if not isinstance(prompt_path_value, str) or not prompt_path_value.strip():
                    continue
                prompt_path = Path(prompt_path_value)
                if not prompt_path.is_absolute():
                    prompt_path = self.config.repo_root / prompt_path
                if prompt_path.exists():
                    return prompt_fingerprint(prompt_path.read_text(encoding="utf-8"))
        return None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_new_session(
        self,
        *,
        goal: str | None = None,
        prompt_text: str | None = None,
        active_roadmap_phase_ids: Sequence[str] | None = None,
        session_id: str | None = None,
    ) -> BootstrapArtifacts:
        if self.session_id is not None:
            raise RuntimeError("start_new_session must be called from the active repository.")

        timestamp = _iso_now()
        roadmap_phase_ids = list(active_roadmap_phase_ids or ["phase_1"])
        next_session_id = self._session_mgr.normalize_session_id(
            session_id or self._session_mgr.generated_session_id(timestamp)
        )

        self.base_dev_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._session_mgr.migrate_legacy_root_snapshot(timestamp=timestamp)

        session_repository = self.for_session(next_session_id)
        session_repository._reset_bootstrap_state(
            goal=goal or "Bootstrap dormammu in the current repository.",
            prompt_text=prompt_text,
            roadmap_phase_ids=roadmap_phase_ids,
            session_id=next_session_id,
            timestamp=timestamp,
        )
        self._write_root_index_for_session(
            session_repository=session_repository,
            timestamp=timestamp,
        )
        return self._artifacts_for_dir(session_repository.dev_dir)

    def restore_session(self, session_id: str) -> BootstrapArtifacts:
        normalized_session_id = self._session_mgr.normalize_session_id(session_id)
        target_dir = self.sessions_dir / normalized_session_id
        if not target_dir.exists():
            raise RuntimeError(f"Saved session was not found: {normalized_session_id}")
        self.for_session(normalized_session_id)._ensure_plan_file(target_dir / "PLAN.md")
        required_files = (
            "DASHBOARD.md",
            "PLAN.md",
            "session.json",
            "workflow_state.json",
        )
        for filename in required_files:
            if not (target_dir / filename).exists():
                raise RuntimeError(
                    f"Saved session {normalized_session_id} is missing required file: {filename}"
                )

        self.base_dev_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._session_mgr.migrate_legacy_root_snapshot()
        self._write_root_index_for_session(
            session_repository=self.for_session(normalized_session_id),
            timestamp=_iso_now(),
        )
        return self._artifacts_for_dir(target_dir)

    def read_session_state(self) -> dict[str, Any]:
        if self.session_id is None:
            return self._active_session_repository().read_session_state()
        return _read_json(self.state_file("session.json"))

    def write_session_state(self, payload: Mapping[str, Any]) -> None:
        if self.session_id is None:
            self._active_session_repository().write_session_state(payload)
            return
        session_payload = dict(payload)
        _write_json(self.state_file("session.json"), session_payload)

        active_phase = session_payload.get("active_phase")
        if isinstance(active_phase, str) and active_phase.strip():
            workflow_state = _read_json(self.state_file("workflow_state.json"))
            workflow_state.setdefault("workflow", {})
            workflow_state["workflow"]["active_phase"] = active_phase
            if "updated_at" in session_payload:
                workflow_state["updated_at"] = session_payload["updated_at"]
            _write_json(self.state_file("workflow_state.json"), workflow_state)
        self._sync_root_index()

    def read_workflow_state(self) -> dict[str, Any]:
        if self.session_id is None:
            return self._active_session_repository().read_workflow_state()
        return _read_json(self.state_file("workflow_state.json"))

    def read_session_worktree_state(self) -> ManagedWorktreeState:
        if self.session_id is None:
            return self._active_session_repository().read_session_worktree_state()
        session_state = _read_json(self.state_file("session.json"))
        return ManagedWorktreeState.from_dict(session_state.get("worktrees"))

    def read_workflow_worktree_state(self) -> ManagedWorktreeState:
        if self.session_id is None:
            return self._active_session_repository().read_workflow_worktree_state()
        workflow_state = _read_json(self.state_file("workflow_state.json"))
        return ManagedWorktreeState.from_dict(workflow_state.get("worktrees"))

    def upsert_managed_worktree(
        self,
        worktree: ManagedWorktree,
        *,
        active: bool | None = None,
        timestamp: str | None = None,
    ) -> None:
        if self.session_id is None:
            self._active_session_repository().upsert_managed_worktree(
                worktree,
                active=active,
                timestamp=timestamp,
            )
            return

        update_timestamp = timestamp or _iso_now()

        def _updater(state: ManagedWorktreeState) -> ManagedWorktreeState:
            return state.upsert(worktree, active=active)

        self._update_managed_worktree_state(_updater, timestamp=update_timestamp)

    def forget_managed_worktree(
        self,
        worktree_id: str,
        *,
        timestamp: str | None = None,
    ) -> None:
        if self.session_id is None:
            self._active_session_repository().forget_managed_worktree(
                worktree_id,
                timestamp=timestamp,
            )
            return

        normalized_id = str(worktree_id).strip()
        if not normalized_id:
            return
        update_timestamp = timestamp or _iso_now()

        def _updater(state: ManagedWorktreeState) -> ManagedWorktreeState:
            return state.forget(normalized_id)

        self._update_managed_worktree_state(_updater, timestamp=update_timestamp)

    def write_workflow_state(self, payload: Mapping[str, Any]) -> None:
        if self.session_id is None:
            self._active_session_repository().write_workflow_state(payload)
            return
        workflow_payload = dict(payload)
        _write_json(self.state_file("workflow_state.json"), workflow_payload)

        active_phase = workflow_payload.get("workflow", {}).get("active_phase")
        if isinstance(active_phase, str) and active_phase.strip():
            session_state = _read_json(self.state_file("session.json"))
            session_state["active_phase"] = active_phase
            if "updated_at" in workflow_payload:
                session_state["updated_at"] = workflow_payload["updated_at"]
            _write_json(self.state_file("session.json"), session_state)
        self._sync_root_index()

    def sync_operator_state(self, *, timestamp: str | None = None) -> None:
        if self.session_id is None:
            self._active_session_repository().sync_operator_state(timestamp=timestamp)
            return
        self._op_sync.sync_active_root_operator_mirrors_into_session(
            session_dev_dir=self.dev_dir,
            active_session_id=self.session_id,
        )
        sync_time = timestamp or _iso_now()
        self._sync_operator_state(
            session_path=self.state_file("session.json"),
            workflow_path=self.state_file("workflow_state.json"),
            operator_task_path=self._operator_task_path(),
            timestamp=sync_time,
        )

    def record_latest_run(self, result: AgentRunResult) -> None:
        if self.session_id is None:
            self._active_session_repository().record_latest_run(result)
            return
        session_path = self.state_file("session.json")
        workflow_path = self.state_file("workflow_state.json")
        latest_run = result.to_dict()

        session_state = _read_json(session_path)
        session_state["updated_at"] = result.completed_at
        session_state["current_run"] = None
        session_state["latest_run"] = latest_run
        _write_json(session_path, session_state)

        workflow_state = _read_json(workflow_path)
        workflow_state["updated_at"] = result.completed_at
        workflow_state["current_run"] = None
        workflow_state["latest_run"] = latest_run
        _write_json(workflow_path, workflow_state)
        self._sync_root_index(timestamp=result.completed_at)

    def record_current_run(self, started: AgentRunStarted) -> None:
        if self.session_id is None:
            self._active_session_repository().record_current_run(started)
            return
        session_path = self.state_file("session.json")
        workflow_path = self.state_file("workflow_state.json")
        current_run = started.to_dict()

        session_state = _read_json(session_path)
        session_state["updated_at"] = started.started_at
        session_state["current_run"] = current_run
        _write_json(session_path, session_state)

        workflow_state = _read_json(workflow_path)
        workflow_state["updated_at"] = started.started_at
        workflow_state["current_run"] = current_run
        _write_json(workflow_path, workflow_state)
        self._sync_root_index(timestamp=started.started_at)

    def write_supervisor_report(self, markdown: str) -> Path:
        if self.session_id is None:
            return self._active_session_repository().write_supervisor_report(markdown)
        report_path = self.state_file("supervisor_report.md")
        report_path.write_text(markdown, encoding="utf-8")
        self._sync_root_index()
        return report_path

    def write_continuation_prompt(self, text: str) -> Path:
        if self.session_id is None:
            return self._active_session_repository().write_continuation_prompt(text)
        prompt_path = self.state_file("continuation_prompt.txt")
        prompt_path.write_text(text, encoding="utf-8")
        self._sync_root_index()
        return prompt_path

    def record_hook_event(
        self,
        payload: Mapping[str, Any],
        *,
        history_limit: int = 25,
    ) -> None:
        if self.session_id is None:
            active_session_id = self._session_mgr.read_active_session_id()
            if active_session_id is None:
                # Runtime hooks can fire before bootstrap establishes a
                # session-scoped state directory. In that pre-session window
                # there is nowhere durable to write hook diagnostics yet, so
                # skip persistence rather than crashing the runtime.
                return
            self.for_session(active_session_id).record_hook_event(
                payload,
                history_limit=history_limit,
            )
            return

        timestamp = str(payload.get("recorded_at") or _iso_now())
        entry = dict(payload)
        session_state = _read_json(self.state_file("session.json"))
        workflow_state = _read_json(self.state_file("workflow_state.json"))

        for state in (session_state, workflow_state):
            state["updated_at"] = timestamp
            hooks_block = state.get("hooks")
            if not isinstance(hooks_block, Mapping):
                hooks_block = {}
            history = hooks_block.get("history")
            normalized_history = []
            if isinstance(history, list):
                normalized_history = [
                    dict(item) for item in history if isinstance(item, Mapping)
                ]
            normalized_history.append(entry)
            hooks_payload = {
                "updated_at": timestamp,
                "latest_event": entry,
                "history": normalized_history[-history_limit:],
            }
            state["hooks"] = hooks_payload

        _write_json(self.state_file("session.json"), session_state)
        _write_json(self.state_file("workflow_state.json"), workflow_state)
        self._sync_root_index(timestamp=timestamp)

    def read_patterns_text(self) -> str:
        """Return the content of .dev/PATTERNS.md, or empty string if not present."""
        patterns_path = self.base_dev_dir / "PATTERNS.md"
        if not patterns_path.exists():
            return ""
        content = patterns_path.read_text(encoding="utf-8").strip()
        return content if content else ""

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._session_mgr.list_sessions()

    def persist_input_prompt(
        self,
        *,
        prompt_text: str,
        source_path: Path | None = None,
    ) -> Path:
        if self.session_id is None:
            return self._active_session_repository().persist_input_prompt(
                prompt_text=prompt_text,
                source_path=source_path,
            )

        import shutil

        prompt_path = self.state_file("PROMPT.md")
        if source_path is not None and source_path.exists():
            shutil.copyfile(source_path, prompt_path)
        else:
            prompt_path.write_text(prompt_text, encoding="utf-8")

        mirror_path = self._global_prompt_mirror_path()
        mirror_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path is not None and source_path.exists():
            shutil.copyfile(source_path, mirror_path)
        else:
            mirror_path.write_text(prompt_text, encoding="utf-8")

        timestamp = _iso_now()
        session_state = _read_json(self.state_file("session.json"))
        session_state["updated_at"] = timestamp
        session_state.setdefault("bootstrap", {})
        session_state["bootstrap"]["prompt_path"] = self._display_state_path(prompt_path)
        session_state["bootstrap"]["global_prompt_path"] = str(mirror_path)
        _write_json(self.state_file("session.json"), session_state)

        workflow_state = _read_json(self.state_file("workflow_state.json"))
        workflow_state["updated_at"] = timestamp
        workflow_state.setdefault("bootstrap", {})
        workflow_state["bootstrap"]["prompt_path"] = self._display_state_path(prompt_path)
        workflow_state["bootstrap"]["global_prompt_path"] = str(mirror_path)
        workflow_state.setdefault("artifacts", {})
        workflow_state["artifacts"]["prompt"] = self._display_state_path(prompt_path)
        _write_json(self.state_file("workflow_state.json"), workflow_state)
        self._sync_root_index(timestamp=timestamp)
        return prompt_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _root_index_lock(self):  # type: ignore[return]
        """Acquire an exclusive file lock on the root .dev/ index files."""
        return self._op_sync.root_index_lock()

    def _normalize_session_id(self, value: str) -> str:
        return self._session_mgr.normalize_session_id(value)

    def _active_session_repository(self) -> StateRepository:
        session_id = self._session_mgr.read_active_session_id()
        if session_id is None:
            raise RuntimeError("No active session is available.")
        return self.for_session(session_id)

    def _sync_root_index(self, *, timestamp: str | None = None) -> None:
        if self.session_id is None:
            return
        active_session_id = self._session_mgr.read_active_session_id()
        if active_session_id != self.session_id:
            return
        self._op_sync.sync_active_root_operator_mirrors_into_session(
            session_dev_dir=self.dev_dir,
            active_session_id=self.session_id,
        )
        self._write_root_index_for_session(
            session_repository=self,
            timestamp=timestamp or _iso_now(),
        )

    def _write_root_index_for_session(
        self,
        *,
        session_repository: StateRepository,
        timestamp: str,
    ) -> None:
        self._op_sync.write_root_index_for_session(
            session_dev_dir=session_repository.dev_dir,
            session_id=session_repository.session_id or "",
            state_root=session_repository._state_root_display(),
            timestamp=timestamp,
            list_sessions_fn=self._session_mgr.list_sessions,
        )

    def _sync_operator_state(
        self,
        *,
        session_path: Path,
        workflow_path: Path,
        operator_task_path: Path,
        timestamp: str,
    ) -> None:
        self._op_sync.sync_operator_state(
            session_path=session_path,
            workflow_path=workflow_path,
            operator_task_path=operator_task_path,
            timestamp=timestamp,
            dev_dir=self.dev_dir,
            display_state_path_fn=self._display_state_path,
        )
        self._sync_root_index(timestamp=timestamp)

    def _existing_goal(self) -> str | None:
        for candidate in (
            self.state_file("workflow_state.json"),
            self.state_file("session.json"),
        ):
            if not candidate.exists():
                continue
            try:
                payload = _read_json(candidate)
            except Exception:
                continue
            bootstrap = payload.get("bootstrap")
            if isinstance(bootstrap, Mapping):
                goal = bootstrap.get("goal")
                if isinstance(goal, str) and goal.strip():
                    return goal
        return None

    def _update_managed_worktree_state(
        self,
        updater: Any,
        *,
        timestamp: str,
    ) -> None:
        session_state = _read_json(self.state_file("session.json"))
        workflow_state = _read_json(self.state_file("workflow_state.json"))

        next_session_worktrees = updater(
            ManagedWorktreeState.from_dict(session_state.get("worktrees"))
        )
        next_workflow_worktrees = updater(
            ManagedWorktreeState.from_dict(workflow_state.get("worktrees"))
        )

        session_state["updated_at"] = timestamp
        workflow_state["updated_at"] = timestamp

        if next_session_worktrees.is_empty:
            session_state.pop("worktrees", None)
        else:
            session_state["worktrees"] = next_session_worktrees.to_dict()

        if next_workflow_worktrees.is_empty:
            workflow_state.pop("worktrees", None)
        else:
            workflow_state["worktrees"] = next_workflow_worktrees.to_dict()

        _write_json(self.state_file("session.json"), session_state)
        _write_json(self.state_file("workflow_state.json"), workflow_state)
        self._sync_root_index(timestamp=timestamp)

    def _reset_bootstrap_state(
        self,
        *,
        goal: str,
        prompt_text: str | None,
        roadmap_phase_ids: Sequence[str],
        session_id: str,
        timestamp: str,
    ) -> None:
        guidance = discover_repo_guidance(
            self.config.repo_root,
            rule_paths=resolve_guidance_files(self.config),
        )
        self._ensure_workspace_roots()
        self.dev_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        dashboard_path = self.state_file("DASHBOARD.md")
        plan_path = self.state_file("PLAN.md")
        tasks_path = self.state_file("TASKS.md")
        session_path = self.state_file("session.json")
        workflow_path = self.state_file("workflow_state.json")
        state_root = self._state_root_display()

        dashboard_context = default_dashboard_context(
            goal=goal,
            roadmap_phase_ids=roadmap_phase_ids,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )
        plan_context = default_plan_context(
            goal=goal,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )
        self._write_template_file(
            dashboard_path,
            "dashboard.md.tmpl",
            dashboard_context.render_values(),
        )
        self._write_template_file(plan_path, "plan.md.tmpl", plan_context.render_values())
        self._write_template_file(tasks_path, "tasks.md.tmpl", plan_context.render_values())

        session_defaults = default_session_state(
            timestamp=timestamp,
            app_name=self.config.app_name,
            roadmap_phase_ids=roadmap_phase_ids,
            goal=goal,
            state_root=state_root,
            prompt_text=prompt_text,
            repo_guidance=guidance,
            session_id=session_id,
            run_type="session",
        )
        workflow_defaults = default_workflow_state(
            timestamp=timestamp,
            roadmap_phase_ids=roadmap_phase_ids,
            goal=goal,
            state_root=state_root,
            prompt_text=prompt_text,
            repo_guidance=guidance,
        )
        _write_json(session_path, session_defaults)
        _write_json(workflow_path, workflow_defaults)

        for extra_name in self.OPTIONAL_STATE_FILENAMES:
            extra_path = self.state_file(extra_name)
            if extra_path.exists():
                extra_path.unlink()

        self._sync_operator_state(
            session_path=session_path,
            workflow_path=workflow_path,
            operator_task_path=tasks_path,
            timestamp=timestamp,
        )

    def _artifacts(self) -> BootstrapArtifacts:
        return self._artifacts_for_dir(self.dev_dir)

    def _artifacts_for_dir(self, directory: Path) -> BootstrapArtifacts:
        plan_path = directory / "PLAN.md"
        tasks_path = directory / "TASKS.md"
        if not plan_path.exists() and tasks_path.exists():
            plan_path.write_text(tasks_path.read_text(encoding="utf-8"), encoding="utf-8")
        if not tasks_path.exists() and plan_path.exists():
            tasks_path.write_text(plan_path.read_text(encoding="utf-8"), encoding="utf-8")
        return BootstrapArtifacts(
            dashboard=directory / "DASHBOARD.md",
            plan=plan_path,
            tasks=tasks_path,
            session=directory / "session.json",
            workflow_state=directory / "workflow_state.json",
            logs_dir=directory / "logs",
            prompt=(directory / "PROMPT.md") if (directory / "PROMPT.md").exists() else None,
        )

    def _ensure_patterns_file(self) -> None:
        patterns_path = self.base_dev_dir / "PATTERNS.md"
        if patterns_path.exists():
            return
        tmpl_path = self.templates_dir / "patterns.md.tmpl"
        if not tmpl_path.exists():
            return
        patterns_path.write_text(tmpl_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _ensure_workspace_roots(self) -> None:
        self.config.workspace_project_root.mkdir(parents=True, exist_ok=True)
        self.config.workspace_tmp_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_template_file(
        self,
        path: Path,
        template_name: str,
        values: Mapping[str, str],
    ) -> None:
        if path.exists():
            return
        template = Template(self._template_path(template_name).read_text(encoding="utf-8"))
        path.write_text(template.safe_substitute(values), encoding="utf-8")

    def _write_template_file(
        self,
        path: Path,
        template_name: str,
        values: Mapping[str, str],
    ) -> None:
        template = Template(self._template_path(template_name).read_text(encoding="utf-8"))
        path.write_text(template.safe_substitute(values), encoding="utf-8")

    def _ensure_plan_file(self, plan_path: Path) -> None:
        if plan_path.exists():
            return
        legacy_tasks_path = self.state_file("TASKS.md")
        if legacy_tasks_path.exists():
            plan_path.write_text(legacy_tasks_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _ensure_tasks_file(
        self,
        task_path: Path,
        *,
        plan_path: Path | None = None,
        values: Mapping[str, str] | None = None,
    ) -> None:
        if task_path.exists():
            return
        if plan_path is not None and plan_path.exists():
            task_path.write_text(plan_path.read_text(encoding="utf-8"), encoding="utf-8")
            return
        if values is not None:
            self._write_template_file(task_path, "tasks.md.tmpl", values)

    def _operator_plan_path(self) -> Path:
        plan_path = self.state_file("PLAN.md")
        self._ensure_plan_file(plan_path)
        if plan_path.exists():
            return plan_path
        return self.state_file("TASKS.md")

    def _operator_task_path(self) -> Path:
        task_path = self.state_file("TASKS.md")
        self._ensure_tasks_file(task_path, plan_path=self.state_file("PLAN.md"))
        if task_path.exists():
            return task_path
        return self._operator_plan_path()

    def _state_root_display(self) -> str:
        try:
            return self.dev_dir.relative_to(self.config.repo_root).as_posix()
        except ValueError:
            return str(self.dev_dir)

    def _display_state_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.config.repo_root).as_posix()
        except ValueError:
            return str(path)

    def _template_path(self, template_name: str) -> Path:
        candidate = self.templates_dir / template_name
        if candidate.exists():
            return candidate
        if template_name == "plan.md.tmpl":
            fallback = self.templates_dir / "tasks.md.tmpl"
            if fallback.exists():
                return fallback
        raise FileNotFoundError(f"Template file was not found: {candidate}")

    def _global_prompt_mirror_path(self) -> Path:
        session_state = _read_json(self.state_file("session.json"))
        session_id = str(session_state.get("session_id") or self.session_id)
        return self.config.sessions_dir / session_id / ".dev" / "PROMPT.md"
