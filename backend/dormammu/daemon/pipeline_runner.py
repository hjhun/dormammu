"""PipelineRunner — orchestrates the role-based agent pipeline.

Pipeline stages
---------------
refiner   (mandatory, one-shot) →
planner   (mandatory, one-shot; loops with evaluator on REWORK only for goals) →
evaluator (mandatory plan checkpoint for goals-scheduler prompts, one-shot) →
developer (supervised LoopRunner) →
tester    (one-shot, loops back to developer on FAIL) →
reviewer  (one-shot, loops back to developer on NEEDS_WORK) →
committer (one-shot) →
evaluator (mandatory post-commit, goals-scheduler context only)

Each stage writes a document to ``.dev/<slot>-<role>/<date>_<stem>.md``.

Refiner
-------
Converts the raw goal into a structured ``.dev/REQUIREMENTS.md``.

Planner
-------
Reads ``.dev/REQUIREMENTS.md`` (if present) and generates the adaptive
``.dev/WORKFLOWS.md`` stage sequence plus updates ``.dev/PLAN.md`` and
``.dev/DASHBOARD.md``.

Developer
---------
Reuses :class:`LoopRunner` so the full supervisor retry loop is preserved.

Re-entry limits
---------------
``MAX_STAGE_ITERATIONS`` caps the planner-evaluator, developer-tester, and
developer-reviewer loops independently. It is derived from the developer
stage's default iteration budget so the prelude and downstream pipeline loops
use the same retry ceiling.

Return value
------------
:meth:`run` returns a :class:`~dormammu.loop_runner.LoopRunResult` so that
:class:`~dormammu.daemon.runner.DaemonRunner` needs no changes to its
result-handling logic.
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, TextIO

from dormammu.agent import CliAdapter
from dormammu.agent.models import AgentRunRequest
from dormammu.agent.profiles import AgentProfile
from dormammu.daemon._patterns import (
    CHECKPOINT_PROCEED_RE as _CHECKPOINT_PROCEED_RE,
    CHECKPOINT_REWORK_RE as _CHECKPOINT_REWORK_RE,
    GOAL_SOURCE_TAG_RE as _GOAL_SOURCE_TAG_RE,
    REVIEWER_REJECT_RE as _REVIEWER_REJECT_RE,
    TESTER_FAIL_RE as _TESTER_FAIL_RE,
)
from dormammu.daemon.cli_output import model_args as _model_args, select_agent_output
from dormammu.daemon.models import StageResult
from dormammu.daemon.evaluator import (
    EvaluatorRequest,
    EvaluatorStage,
    resolve_evaluator_cli,
    resolve_evaluator_model,
)
from dormammu.daemon.rules import build_rule_prompt, load_rule_text
from dormammu.lifecycle import (
    ArtifactPersistedPayload,
    ArtifactRef,
    EvaluatorCheckpointPayload,
    LifecycleEventType,
    LifecycleRecorder,
    RunEventPayload,
    StageEventPayload,
    SupervisorHandoffPayload,
)
from dormammu.loop_runner import LoopRunRequest, LoopRunResult, LoopRunner
from dormammu.runtime_hooks import RuntimeHookBlocked, RuntimeHookController
from dormammu.skills import runtime_skill_summary
from dormammu.state import StateRepository

if TYPE_CHECKING:
    from dormammu.agent.role_config import AgentsConfig
    from dormammu.config import AppConfig
    from dormammu.daemon.goals_config import EvaluatorConfig

_DEFAULT_MAX_RETRIES = 49
MAX_STAGE_ITERATIONS = _DEFAULT_MAX_RETRIES + 1
_STAGE_FAILURE_VERDICTS = frozenset({"blocked", "failed", "fail", "needs_work", "rework"})


class PipelineRunner:
    """Runs the full planner→tester→reviewer→committer pipeline.

    The ``developer`` stage is handled by :class:`LoopRunner`.
    The ``tester``, ``reviewer``, and ``committer`` stages are one-shot
    agent CLI calls whose stdout is parsed to determine pass/fail.
    """

    def __init__(
        self,
        app_config: AppConfig,
        agents_config: AgentsConfig,
        *,
        repository: StateRepository | None = None,
        progress_stream: TextIO | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._app_config = app_config
        self._agents = agents_config
        self._repository = repository or StateRepository(app_config)
        self._progress_stream = progress_stream or sys.stderr
        self._stop_event = stop_event
        self._hook_controller = RuntimeHookController(
            app_config,
            repository=self._repository,
            progress_stream=self._progress_stream,
        )

    def _profile_for_role(self, role: str) -> AgentProfile:
        return self._app_config.resolve_agent_profile(role)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_refine_and_plan(
        self,
        goal_text: str,
        *,
        stem: str,
        date_str: str | None = None,
        enable_plan_evaluator: bool = False,
    ) -> None:
        """Execute the mandatory refine -> plan prelude for a prompt."""
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        self._run_refiner(goal_text, stem=stem, date_str=date_str)
        self._run_planner(
            goal_text,
            stem=stem,
            date_str=date_str,
            checkpoint_feedback_text=None,
        )
        if not enable_plan_evaluator:
            self._log("pipeline: plan evaluator disabled for non-goals prompt")
            return

        evaluator_feedback_text: str | None = None
        for iteration in range(MAX_STAGE_ITERATIONS):
            stage = self._run_plan_evaluator(
                goal_text,
                stem=stem,
                date_str=date_str,
            )
            if stage.verdict == "proceed":
                self._log(
                    f"pipeline: plan evaluator PROCEED (iteration {iteration + 1})"
                )
                return
            if iteration < MAX_STAGE_ITERATIONS - 1:
                self._log(
                    f"pipeline: plan evaluator REWORK (iteration {iteration + 1}) "
                    "— re-entering planner"
                )
                evaluator_feedback_text = stage.output
                if self._lifecycle is not None:
                    self._lifecycle.emit(
                        event_type=LifecycleEventType.STAGE_RETRIED,
                        role="planner",
                        stage="planner",
                        status="retried",
                        payload=StageEventPayload(
                            attempt=iteration + 1,
                            next_attempt=iteration + 2,
                            source_stage="evaluator",
                            target_stage="planner",
                            reason="Plan evaluator requested rework.",
                        ),
                    )
                    self._lifecycle.emit(
                        event_type=LifecycleEventType.SUPERVISOR_HANDOFF,
                        role="evaluator",
                        stage="planner",
                        status="handoff",
                        payload=SupervisorHandoffPayload(
                            from_role="evaluator",
                            to_role="planner",
                            reason="Plan checkpoint requested rework.",
                            attempt=iteration + 2,
                        ),
                    )
                self._run_planner(
                    goal_text,
                    stem=stem,
                    date_str=date_str,
                    checkpoint_feedback_text=evaluator_feedback_text,
                )
                continue
            raise RuntimeError(
                "Mandatory plan evaluator requested REWORK after the maximum "
                "planner retries."
            )

    def run(
        self,
        prompt_text: str,
        *,
        stem: str,
        date_str: str | None = None,
        goal_file_path: Path | None = None,
        evaluator_config: "EvaluatorConfig | None" = None,
    ) -> LoopRunResult:
        """Execute the full pipeline and return a :class:`LoopRunResult`.

        ``goal_file_path`` controls whether the mandatory post-commit evaluator
        runs. When it is None, the prompt did not come from the goals scheduler
        and the final evaluator is skipped.
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        dev_prompt = prompt_text
        loop_result: LoopRunResult | None = None
        final_result: LoopRunResult | None = None
        terminal_error: str | None = None
        session_id = self._session_id()
        self._lifecycle = LifecycleRecorder.for_execution(
            self._repository,
            scope="pipeline",
            session_id=session_id,
            label=stem,
            default_metadata={"source": "pipeline_runner", "entrypoint": "PipelineRunner.run"},
        )
        self._lifecycle.emit(
            event_type=LifecycleEventType.RUN_REQUESTED,
            role="pipeline",
            stage="pipeline",
            status="requested",
            payload=RunEventPayload(
                source="pipeline_runner",
                entrypoint="PipelineRunner.run",
                trigger="pipeline",
                prompt_summary=prompt_text.splitlines()[0].strip() if prompt_text.strip() else None,
            ),
            metadata={"goal_file_path": str(goal_file_path) if goal_file_path else None},
        )

        try:
            self._lifecycle.emit(
                event_type=LifecycleEventType.RUN_STARTED,
                role="pipeline",
                stage="pipeline",
                status="started",
                payload=RunEventPayload(
                    source="pipeline_runner",
                    entrypoint="PipelineRunner.run",
                    trigger="pipeline",
                ),
            )
            self._hook_controller.emit_prompt_intake(
                prompt_text=prompt_text,
                source="pipeline_runner",
                entrypoint="PipelineRunner.run",
                session_id=session_id,
                run_id=self._lifecycle.run_id,
                agent_role="pipeline",
            )

            # ---- refiner + planner (mandatory) ----------------------------------
            self.run_refine_and_plan(
                prompt_text,
                stem=stem,
                date_str=date_str,
                enable_plan_evaluator=goal_file_path is not None,
            )

            # ---- developer → tester loop ----------------------------------------
            for tester_iter in range(MAX_STAGE_ITERATIONS):
                loop_result = self._run_developer(dev_prompt, stem=stem)
                if loop_result.status not in ("completed",):
                    self._log(
                        f"pipeline: developer stage ended with status "
                        f"'{loop_result.status}' — aborting pipeline"
                    )
                    final_result = loop_result
                    break

                tester_stage = self._run_tester(prompt_text, stem=stem, date_str=date_str)
                if tester_stage is None:
                    # Tester not configured — skip tester stage
                    break
                if tester_stage.verdict == "pass":
                    self._log(f"pipeline: tester PASS (iteration {tester_iter + 1})")
                    break
                if tester_iter < MAX_STAGE_ITERATIONS - 1:
                    self._log(
                        f"pipeline: tester FAIL (iteration {tester_iter + 1}) "
                        "— re-entering developer"
                    )
                    if self._lifecycle is not None:
                        self._lifecycle.emit(
                            event_type=LifecycleEventType.STAGE_RETRIED,
                            role="developer",
                            stage="developer",
                            status="retried",
                            payload=StageEventPayload(
                                attempt=tester_iter + 1,
                                next_attempt=tester_iter + 2,
                                source_stage="tester",
                                target_stage="developer",
                                reason="Tester requested another developer pass.",
                            ),
                        )
                        self._lifecycle.emit(
                            event_type=LifecycleEventType.SUPERVISOR_HANDOFF,
                            role="tester",
                            stage="developer",
                            status="handoff",
                            payload=SupervisorHandoffPayload(
                                from_role="tester",
                                to_role="developer",
                                reason="Tester reported FAIL and handed the slice back to developer.",
                                attempt=tester_iter + 2,
                            ),
                        )
                    dev_prompt = self._append_feedback(
                        prompt_text, tester_stage.output, source="tester"
                    )
                else:
                    self._log(
                        f"pipeline: tester FAIL — max iterations ({MAX_STAGE_ITERATIONS}) "
                        "reached; continuing to reviewer"
                    )

            if final_result is not None:
                return self._finalize_pipeline_result(final_result)

            # ---- developer → reviewer loop --------------------------------------
            for reviewer_iter in range(MAX_STAGE_ITERATIONS):
                reviewer_stage = self._run_reviewer(
                    prompt_text, stem=stem, date_str=date_str
                )
                if reviewer_stage is None:
                    # Reviewer not configured — skip
                    break
                if reviewer_stage.verdict == "approved":
                    self._log(f"pipeline: reviewer APPROVED (iteration {reviewer_iter + 1})")
                    break
                if reviewer_iter < MAX_STAGE_ITERATIONS - 1:
                    self._log(
                        f"pipeline: reviewer NEEDS_WORK (iteration {reviewer_iter + 1}) "
                        "— re-entering developer"
                    )
                    if self._lifecycle is not None:
                        self._lifecycle.emit(
                            event_type=LifecycleEventType.STAGE_RETRIED,
                            role="developer",
                            stage="developer",
                            status="retried",
                            payload=StageEventPayload(
                                attempt=reviewer_iter + 1,
                                next_attempt=reviewer_iter + 2,
                                source_stage="reviewer",
                                target_stage="developer",
                                reason="Reviewer requested another developer pass.",
                            ),
                        )
                        self._lifecycle.emit(
                            event_type=LifecycleEventType.SUPERVISOR_HANDOFF,
                            role="reviewer",
                            stage="developer",
                            status="handoff",
                            payload=SupervisorHandoffPayload(
                                from_role="reviewer",
                                to_role="developer",
                                reason="Reviewer reported NEEDS_WORK and handed the slice back to developer.",
                                attempt=reviewer_iter + 2,
                            ),
                        )
                    dev_prompt = self._append_feedback(
                        prompt_text, reviewer_stage.output, source="reviewer"
                    )
                    loop_result = self._run_developer(dev_prompt, stem=stem)
                    if loop_result.status not in ("completed",):
                        final_result = loop_result
                        break
                else:
                    self._log(
                        f"pipeline: reviewer NEEDS_WORK — max iterations "
                        f"({MAX_STAGE_ITERATIONS}) reached; continuing to committer"
                    )

            if final_result is not None:
                return self._finalize_pipeline_result(final_result)

            # ---- committer -------------------------------------------------------
            self._run_committer(stem=stem, date_str=date_str)

            # ---- evaluator (goals-scheduler context only) -----------------------
            self._run_evaluator(
                prompt_text=prompt_text,
                stem=stem,
                date_str=date_str,
                goal_file_path=goal_file_path,
                evaluator_config=evaluator_config,
            )
        except RuntimeHookBlocked as exc:
            self._log(f"pipeline: runtime hook blocked execution: {exc}")
            final_result = self._blocked_loop_result(loop_result)
            terminal_error = str(exc)
        finally:
            active_exception = sys.exc_info()[1]
            if active_exception is not None:
                error_text = terminal_error or str(active_exception)
                self._emit_run_finished_event(
                    final_result or loop_result,
                    terminal_error=error_text,
                )

        assert loop_result is not None or final_result is not None
        final_result = self._finalize_pipeline_result(
            final_result or loop_result,
            terminal_error=terminal_error,
        )
        return final_result

    # ------------------------------------------------------------------
    # Refiner stage (one-shot, mandatory)
    # ------------------------------------------------------------------

    def _run_refiner(
        self, goal_text: str, *, stem: str, date_str: str
    ) -> str | None:
        """Run the refiner agent once.

        Produces ``.dev/REQUIREMENTS.md``.

        Returns the agent output string.
        """
        profile = self._profile_for_role("refiner")
        cli = profile.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            raise RuntimeError("No CLI available for refiner role.")

        self._emit_stage_queued(role="refiner", reason="Mandatory refine stage is ready to run.")
        self._emit_stage_start(role="refiner")
        self._log("pipeline: refiner stage starting")
        prompt = self._refiner_prompt(goal_text, stem=stem, date_str=date_str)
        output = self._call_once(
            role="refiner",
            cli=cli,
            model=profile.model_override,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            save_doc=False,
        )
        self._log("pipeline: refiner stage completed")
        self._emit_stage_complete(role="refiner", verdict="done")
        return output

    # ------------------------------------------------------------------
    # Planner stage (one-shot, mandatory)
    # ------------------------------------------------------------------

    def _run_planner(
        self,
        goal_text: str,
        *,
        stem: str,
        date_str: str,
        checkpoint_feedback_text: str | None = None,
    ) -> str | None:
        """Run the planner agent once.

        Reads ``.dev/REQUIREMENTS.md`` (produced by the refiner) if it exists,
        then instructs the agent to generate ``.dev/WORKFLOWS.md`` and update
        ``.dev/PLAN.md`` / ``.dev/DASHBOARD.md``.

        Returns the agent output string.
        """
        profile = self._profile_for_role("planner")
        cli = profile.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            raise RuntimeError("No CLI available for planner role.")

        self._hook_controller.emit_plan_start(
            source="pipeline_runner",
            goal_text=goal_text,
            stem=stem,
            date_str=date_str,
            session_id=self._session_id(),
            run_id=self._lifecycle.run_id if self._lifecycle is not None else None,
        )
        self._emit_stage_queued(role="planner", reason="Mandatory planning stage is ready to run.")
        self._emit_stage_start(role="planner")
        self._log("pipeline: planner stage starting")
        requirements_text = self._read_requirements_doc()
        prompt = self._planner_prompt(
            goal_text,
            requirements_text,
            stem=stem,
            date_str=date_str,
            checkpoint_feedback_text=checkpoint_feedback_text,
        )
        output = self._call_once(
            role="planner",
            cli=cli,
            model=profile.model_override,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            save_doc=False,
        )
        self._log("pipeline: planner stage completed")
        self._emit_stage_complete(role="planner", verdict="done")
        return output

    # ------------------------------------------------------------------
    # Plan evaluator stage (one-shot, goals-scheduler context only)
    # ------------------------------------------------------------------

    def _run_plan_evaluator(
        self, goal_text: str, *, stem: str, date_str: str
    ) -> StageResult:
        """Run the mandatory evaluator checkpoint after planning for goals.

        Returns a :class:`StageResult` with verdict ``"proceed"`` or ``"rework"``.
        Missing or ambiguous decisions fail closed as ``"rework"``.
        """
        profile = self._profile_for_role("evaluator")
        cli = profile.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            raise RuntimeError("No CLI available for mandatory evaluator role.")

        self._emit_stage_queued(role="evaluator", reason="Plan checkpoint evaluator is queued.")
        self._emit_stage_start(role="evaluator")
        self._log("pipeline: plan evaluator stage starting")
        requirements_text = self._read_requirements_doc()
        prompt = self._plan_evaluator_prompt(
            goal_text,
            requirements_text,
            stem=stem,
            date_str=date_str,
        )
        report_path = (
            self._app_config.base_dev_dir
            / "logs"
            / f"check_plan_{date_str}_{stem}.md"
        )
        output = self._call_once(
            role="evaluator",
            cli=cli,
            model=profile.model_override,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            doc_path=report_path,
        )

        verdict = "proceed" if _CHECKPOINT_PROCEED_RE.search(output) else "rework"
        if self._lifecycle is not None:
            self._lifecycle.emit(
                event_type=LifecycleEventType.EVALUATOR_CHECKPOINT_DECISION,
                role="evaluator",
                stage="evaluator",
                status=verdict,
                payload=EvaluatorCheckpointPayload(
                    checkpoint_kind="plan",
                    decision=verdict,
                ),
                artifact_refs=(
                    ArtifactRef.from_path(
                        kind="checkpoint_report",
                        path=report_path,
                        label="plan_checkpoint_report",
                        content_type="text/markdown",
                    ),
                ),
            )
        self._emit_stage_complete(role="evaluator", verdict=verdict)
        return StageResult(role="evaluator", verdict=verdict, output=output, report_path=report_path)

    # ------------------------------------------------------------------
    # Developer stage (LoopRunner)
    # ------------------------------------------------------------------

    def _run_developer(self, prompt_text: str, *, stem: str) -> LoopRunResult:
        self._emit_stage_queued(role="developer", reason="Developer stage is queued.")
        self._emit_stage_start(role="developer")
        self._log("pipeline: developer stage starting")
        profile = self._profile_for_role("developer")
        cli = profile.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            raise RuntimeError("No CLI available for developer role.")

        extra_args = _model_args(cli.name, profile.model_override)
        request = LoopRunRequest(
            cli_path=cli,
            prompt_text=prompt_text,
            repo_root=self._app_config.repo_root,
            agent_role="developer",
            workdir=self._app_config.repo_root,
            input_mode="auto",
            extra_args=tuple(extra_args),
            run_label=f"pipeline-developer-{stem}",
            max_retries=_DEFAULT_MAX_RETRIES,
            expected_roadmap_phase_id="phase_4",
        )
        result = LoopRunner(
            self._app_config,
            repository=self._repository,
            adapter=CliAdapter(
                self._app_config,
                live_output_stream=self._progress_stream,
                stop_event=self._stop_event,
            ),
            progress_stream=self._progress_stream,
        ).run(
            request,
            emit_prompt_intake=False,
            emit_stage_hooks=False,
            manage_session_lifecycle=False,
        )
        self._log(f"pipeline: developer stage completed with status '{result.status}'")
        self._emit_stage_complete(
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

    # ------------------------------------------------------------------
    # Tester stage (one-shot)
    # ------------------------------------------------------------------

    def _run_tester(
        self, goal_text: str, *, stem: str, date_str: str
    ) -> StageResult | None:
        """Run the tester agent once.

        Returns a :class:`StageResult` with verdict ``"pass"`` or ``"fail"``,
        or ``None`` if the tester role has no resolvable CLI.
        Defaults to ``"pass"`` when the agent does not explicitly report failure.
        """
        profile = self._profile_for_role("tester")
        cli = profile.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            return None

        self._emit_stage_queued(role="tester", reason="Tester stage is queued.")
        self._emit_stage_start(role="tester")
        self._log("pipeline: tester stage starting")
        prompt = self._tester_prompt(goal_text, stem=stem, date_str=date_str)
        output = self._call_once(
            role="tester",
            cli=cli,
            model=profile.model_override,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
        )

        verdict = "fail" if _TESTER_FAIL_RE.search(output) else "pass"
        self._emit_stage_complete(role="tester", verdict=verdict)
        return StageResult(role="tester", verdict=verdict, output=output)

    # ------------------------------------------------------------------
    # Reviewer stage (one-shot)
    # ------------------------------------------------------------------

    def _run_reviewer(
        self, goal_text: str, *, stem: str, date_str: str
    ) -> StageResult | None:
        """Run the reviewer agent once.

        Returns a :class:`StageResult` with verdict ``"approved"`` or
        ``"needs_work"``, or ``None`` if no resolvable CLI.
        """
        profile = self._profile_for_role("reviewer")
        cli = profile.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            return None

        self._emit_stage_queued(role="reviewer", reason="Reviewer stage is queued.")
        self._emit_stage_start(role="reviewer")
        self._log("pipeline: reviewer stage starting")
        design_text = self._read_designer_doc(stem, date_str)
        prompt = self._reviewer_prompt(goal_text, design_text, stem=stem, date_str=date_str)
        output = self._call_once(
            role="reviewer",
            cli=cli,
            model=profile.model_override,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
        )

        verdict = "needs_work" if _REVIEWER_REJECT_RE.search(output) else "approved"
        self._emit_stage_complete(role="reviewer", verdict=verdict)
        return StageResult(role="reviewer", verdict=verdict, output=output)

    # ------------------------------------------------------------------
    # Committer stage (one-shot)
    # ------------------------------------------------------------------

    def _run_committer(self, *, stem: str, date_str: str) -> None:
        profile = self._profile_for_role("committer")
        cli = profile.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            self._log("pipeline: committer has no CLI — skipping commit")
            return

        self._emit_stage_queued(role="committer", reason="Committer stage is queued.")
        self._emit_stage_start(role="committer")
        self._log("pipeline: committer stage starting")
        prompt = self._committer_prompt(stem, date_str=date_str)
        self._call_once(
            role="committer",
            cli=cli,
            model=profile.model_override,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
        )
        self._emit_stage_complete(role="committer", verdict="committed")

    # ------------------------------------------------------------------
    # Evaluator stage (goals-scheduler context only)
    # ------------------------------------------------------------------

    def _run_evaluator(
        self,
        *,
        prompt_text: str,
        stem: str,
        date_str: str,
        goal_file_path: Path | None,
        evaluator_config: "EvaluatorConfig | None",
    ) -> None:
        """Run the mandatory post-commit evaluator for goals-scheduler prompts."""
        if goal_file_path is None:
            return

        from dormammu.daemon.goals_config import EvaluatorConfig  # noqa: PLC0415

        effective_config = evaluator_config or EvaluatorConfig(enabled=True)
        if evaluator_config is not None and not evaluator_config.enabled:
            self._log(
                "pipeline: goals-triggered prompt requires post-commit "
                "evaluation — ignoring disabled evaluator flag"
            )

        profile = self._profile_for_role("evaluator")
        cli = resolve_evaluator_cli(
            effective_config,
            profile.cli_override,  # agents.evaluator.cli only
            self._app_config.active_agent_cli,
        )
        if cli is None:
            raise RuntimeError(
                "No CLI available for mandatory post-commit evaluator stage."
            )

        model = resolve_evaluator_model(effective_config, profile.model_override)

        # Extract the original goal text (strip the metadata comment if present).
        goal_text = _strip_goal_source_tag(prompt_text)

        self._emit_stage_queued(role="evaluator", reason="Post-commit evaluator is queued.")
        self._emit_stage_start(role="evaluator")
        self._log("pipeline: evaluator stage starting")
        request = EvaluatorRequest(
            cli=cli,
            model=model,
            goal_file_path=goal_file_path,
            goal_text=goal_text,
            repo_root=self._app_config.repo_root,
            dev_dir=self._app_config.base_dev_dir,
            tmp_dir=self._app_config.workspace_tmp_dir,
            agents_dir=self._app_config.agents_dir,
            runtime_paths_text=self._app_config.runtime_path_prompt(),
            next_goal_strategy=effective_config.next_goal_strategy,
            stem=stem,
            date_str=date_str,
        )
        result = EvaluatorStage(
            progress_stream=self._progress_stream,
        ).run(request)
        if result.status != "completed":
            raise RuntimeError("Mandatory post-commit evaluator stage failed.")
        if self._lifecycle is not None and result.report_path is not None:
            self._lifecycle.emit(
                event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                role="evaluator",
                stage="evaluator",
                status="persisted",
                payload=ArtifactPersistedPayload(
                    artifact_kind="evaluator_report",
                    summary="Persisted the post-commit evaluator report.",
                ),
                artifact_refs=(
                    ArtifactRef.from_path(
                        kind="evaluator_report",
                        path=result.report_path,
                        label="evaluator_report",
                        content_type="text/markdown",
                    ),
                ),
            )
        self._log(
            f"pipeline: evaluator stage completed "
            f"(status={result.status}, verdict={result.verdict})"
        )
        self._emit_stage_complete(
            role="evaluator",
            verdict=result.verdict,
            payload={
                "status": result.status,
                "goal_file_updated": result.goal_file_updated,
                "report_path": str(result.report_path) if result.report_path else None,
            },
        )

    # ------------------------------------------------------------------
    # Internal — one-shot agent call
    # ------------------------------------------------------------------

    def _call_once(
        self,
        *,
        role: str,
        cli: Path,
        model: str | None,
        prompt: str,
        stem: str,
        date_str: str,
        doc_path: Path | None = None,
        save_doc: bool = True,
    ) -> str:
        """Run an agent CLI once and return its stdout.

        Routes through :class:`CliAdapter` so that pipeline one-shot stages
        share the same command building, prompt injection, timeout, and
        shutdown logic as the supervised loop stages.

        When ``save_doc=False`` the agent output is not persisted to a stage
        document file.  Use this for roles (refiner, planner) whose important
        outputs are the files they write directly (REQUIREMENTS.md, PLAN.md,
        etc.) rather than a stage report file.
        """
        adapter = CliAdapter(
            self._app_config,
            live_output_stream=self._progress_stream,
            stop_event=self._stop_event,
        )
        request = AgentRunRequest(
            cli_path=cli,
            prompt_text=prompt,
            repo_root=self._app_config.repo_root,
            extra_args=tuple(_model_args(cli.name, model)),
            run_label=role,
        )
        self._emit_cli_command(
            role=role,
            args=[str(cli)] + list(_model_args(cli.name, model)),
            cwd=self._app_config.repo_root,
        )
        result = adapter.run_once(request)
        stdout_text = result.stdout_path.read_text(encoding="utf-8") if result.stdout_path.exists() else ""
        stderr_text = result.stderr_path.read_text(encoding="utf-8") if result.stderr_path.exists() else ""
        self._emit_cli_output(role=role, stdout_text=stdout_text, stderr_text=stderr_text)
        output = select_agent_output(stdout_text, stderr_text)

        if save_doc:
            target_path = doc_path
            if target_path is None:
                doc_dir = self._app_config.base_dev_dir / "logs"
                doc_dir.mkdir(parents=True, exist_ok=True)
                target_path = doc_dir / f"{date_str}_{role}_{stem}.md"
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                f"# {role.capitalize()} — {stem}\n\n{output}",
                encoding="utf-8",
            )
            self._log(f"pipeline: {role} document → {target_path}")
            if self._lifecycle is not None:
                self._lifecycle.emit(
                    event_type=LifecycleEventType.ARTIFACT_PERSISTED,
                    role=role,
                    stage=role,
                    status="persisted",
                    payload=ArtifactPersistedPayload(
                        artifact_kind="stage_report",
                        summary=f"Persisted the {role} stage report.",
                    ),
                    artifact_refs=(
                        ArtifactRef.from_path(
                            kind="stage_report",
                            path=target_path,
                            label=f"{role}_report",
                            content_type="text/markdown",
                        ),
                    ),
                )
        return output

    # ------------------------------------------------------------------
    # Internal — prompt builders
    # ------------------------------------------------------------------

    def _refiner_prompt(self, goal_text: str, *, stem: str, date_str: str) -> str:
        rule_text = self._load_rule("refiner-runtime.md")
        return build_rule_prompt(
            rule_text,
            runtime_paths_text=self._app_config.runtime_path_prompt(),
            sections=(
                ("Goal", goal_text),
                (
                    "Expected Outputs",
                    "- `.dev/REQUIREMENTS.md`",
                ),
            ),
        )

    def _planner_prompt(
        self,
        goal_text: str,
        requirements_text: str | None,
        *,
        stem: str,
        date_str: str,
        checkpoint_feedback_text: str | None = None,
    ) -> str:
        rule_text = self._load_rule("planner-runtime.md")
        return build_rule_prompt(
            rule_text,
            runtime_paths_text=self._app_config.runtime_path_prompt(),
            sections=(
                ("Goal", goal_text),
                ("Refined Requirements", requirements_text),
                ("Evaluator Feedback", checkpoint_feedback_text),
                (
                    "Expected Outputs",
                    (
                        "- `.dev/WORKFLOWS.md`\n"
                        "- `.dev/PLAN.md`\n"
                        "- `.dev/DASHBOARD.md`"
                    ),
                ),
            ),
        )

    def _plan_evaluator_prompt(
        self,
        goal_text: str,
        requirements_text: str | None,
        *,
        stem: str,
        date_str: str,
    ) -> str:
        rule_text = self._load_rule("evaluator-check-plan.md")
        report_path = (
            self._app_config.base_dev_dir
            / "logs"
            / f"check_plan_{date_str}_{stem}.md"
        )
        return build_rule_prompt(
            rule_text,
            runtime_paths_text=self._app_config.runtime_path_prompt(),
            sections=(
                ("Goal", goal_text),
                ("Refined Requirements", requirements_text),
                ("Expected Output Path", str(report_path)),
            ),
        )

    def _tester_prompt(self, goal_text: str, *, stem: str, date_str: str) -> str:
        rule_text = self._load_rule("tester-runtime.md")
        report_path = self._stage_doc_path("tester", stem=stem, date_str=date_str)
        return build_rule_prompt(
            rule_text,
            runtime_paths_text=self._app_config.runtime_path_prompt(),
            sections=(
                ("Goal", goal_text),
                ("Expected Output Path", str(report_path)),
            ),
        )

    def _reviewer_prompt(
        self,
        goal_text: str,
        design_text: str | None,
        *,
        stem: str,
        date_str: str,
    ) -> str:
        rule_text = self._load_rule("reviewer-runtime.md")
        report_path = self._stage_doc_path("reviewer", stem=stem, date_str=date_str)
        return build_rule_prompt(
            rule_text,
            runtime_paths_text=self._app_config.runtime_path_prompt(),
            sections=(
                ("Goal", goal_text),
                ("Architect Design", design_text),
                ("Expected Output Path", str(report_path)),
            ),
        )

    def _committer_prompt(self, stem: str, *, date_str: str) -> str:
        rule_text = self._load_rule("committer-runtime.md")
        report_path = self._stage_doc_path("committer", stem=stem, date_str=date_str)
        return build_rule_prompt(
            rule_text,
            runtime_paths_text=self._app_config.runtime_path_prompt(),
            sections=(
                ("Implementation Scope", stem),
                ("Expected Output Path", str(report_path)),
            ),
        )

    # ------------------------------------------------------------------
    # Internal — helpers
    # ------------------------------------------------------------------

    def _read_requirements_doc(self) -> str | None:
        """Return .dev/REQUIREMENTS.md text if it exists, else None."""
        doc = self._app_config.base_dev_dir / "REQUIREMENTS.md"
        if doc.exists():
            return doc.read_text(encoding="utf-8")
        return None

    def _read_designer_doc(self, stem: str, date_str: str) -> str | None:
        """Return designer document text if it exists, else None."""
        doc = self._app_config.base_dev_dir / "logs" / f"{date_str}_designer_{stem}.md"
        if doc.exists():
            return doc.read_text(encoding="utf-8")
        return None

    def _load_rule(self, rule_name: str) -> str:
        return load_rule_text(self._app_config.agents_dir, rule_name)

    def _stage_doc_path(self, role: str, *, stem: str, date_str: str) -> Path:
        return self._app_config.base_dev_dir / "logs" / f"{date_str}_{role}_{stem}.md"

    def _session_id(self) -> str | None:
        try:
            session_state = self._repository.read_session_state()
        except Exception:
            return None
        session_id = session_state.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            return session_id
        return None

    def _emit_stage_queued(self, *, role: str, reason: str) -> None:
        if self._lifecycle is None:
            return
        self._lifecycle.emit(
            event_type=LifecycleEventType.STAGE_QUEUED,
            role=role,
            stage=role,
            status="queued",
            payload=StageEventPayload(reason=reason),
        )

    def _emit_stage_start(self, *, role: str) -> None:
        profile = self._profile_for_role(role)
        runtime_skills = self._repository.record_runtime_skill_resolution(
            role=role,
            profile=profile,
        )
        summary = runtime_skill_summary(runtime_skills.get("latest"))
        if summary.get("interesting_for_operator"):
            self._log(
                "pipeline: runtime skills "
                f"for {role}/{profile.name} "
                f"(visible={summary.get('visible_count', 0)}, "
                f"custom={summary.get('custom_visible_count', 0)}, "
                f"hidden={summary.get('hidden_count', 0)}, "
                f"preloaded={summary.get('preloaded_count', 0)}, "
                f"missing_preloads={summary.get('missing_preload_count', 0)}, "
                f"shadowed={summary.get('shadowed_count', 0)})"
            )
        if self._lifecycle is not None:
            self._lifecycle.emit(
                event_type=LifecycleEventType.STAGE_STARTED,
                role=role,
                stage=role,
                status="started",
                payload=StageEventPayload(
                    reason="Pipeline stage entered active execution.",
                ),
                metadata={"runtime_skills": summary},
            )
        self._hook_controller.emit_stage_start(
            source="pipeline_runner",
            stage_name=role,
            agent_role=role,
            session_id=self._session_id(),
            run_id=self._lifecycle.run_id if self._lifecycle is not None else None,
            metadata={"runtime_skills": summary},
        )

    def _emit_stage_complete(
        self,
        *,
        role: str,
        verdict: str,
        run_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        completion_payload = {"verdict": verdict}
        if payload:
            completion_payload.update(dict(payload))
        if self._lifecycle is not None:
            event_type = (
                LifecycleEventType.STAGE_FAILED
                if verdict in _STAGE_FAILURE_VERDICTS
                else LifecycleEventType.STAGE_COMPLETED
            )
            self._lifecycle.emit(
                event_type=event_type,
                role=role,
                stage=role,
                status=verdict,
                payload=StageEventPayload(
                    verdict=verdict,
                    reason=completion_payload.get("status"),
                    error=completion_payload.get("error"),
                ),
                metadata={"run_id": run_id},
            )
        self._hook_controller.emit_stage_complete(
            source="pipeline_runner",
            stage_name=role,
            agent_role=role,
            session_id=self._session_id(),
            run_id=self._lifecycle.run_id if self._lifecycle is not None else run_id,
            payload=completion_payload,
        )

    def _blocked_loop_result(self, loop_result: LoopRunResult | None) -> LoopRunResult:
        return LoopRunResult(
            status="blocked",
            attempts_completed=loop_result.attempts_completed if loop_result else 0,
            retries_used=loop_result.retries_used if loop_result else 0,
            max_retries=loop_result.max_retries if loop_result else 0,
            max_iterations=loop_result.max_iterations if loop_result else 1,
            latest_run_id=loop_result.latest_run_id if loop_result else None,
            supervisor_verdict="blocked",
            report_path=loop_result.report_path if loop_result else None,
            continuation_prompt_path=(
                loop_result.continuation_prompt_path if loop_result else None
            ),
        )

    def _emit_run_finished_event(
        self,
        result: LoopRunResult | None,
        *,
        terminal_error: str | None = None,
    ) -> None:
        lifecycle = self._lifecycle
        if lifecycle is None:
            return
        if result is not None:
            status = result.status
            payload = RunEventPayload(
                source="pipeline_runner",
                entrypoint="PipelineRunner.run",
                attempts_completed=result.attempts_completed,
                retries_used=result.retries_used,
                supervisor_verdict=result.supervisor_verdict,
                outcome=result.status,
                error=terminal_error,
            )
        else:
            status = "failed"
            payload = RunEventPayload(
                source="pipeline_runner",
                entrypoint="PipelineRunner.run",
                outcome=status,
                error=terminal_error,
            )
        lifecycle.emit(
            event_type=LifecycleEventType.RUN_FINISHED,
            role="pipeline",
            stage="pipeline",
            status=status,
            payload=payload,
        )
        self._lifecycle = None

    def _finalize_pipeline_result(
        self,
        result: LoopRunResult,
        *,
        terminal_error: str | None = None,
    ) -> LoopRunResult:
        session_id = self._session_id()
        final_result = result
        try:
            self._hook_controller.emit_session_end(
                source="pipeline_runner",
                session_id=session_id,
                run_id=self._lifecycle.run_id if self._lifecycle is not None else result.latest_run_id,
                agent_role="pipeline",
                result=result.to_dict(),
            )
        except RuntimeHookBlocked as exc:
            self._log(f"pipeline: session-end hook blocked exit: {exc}")
            if terminal_error is None or result.status == "completed":
                terminal_error = str(exc)
            final_result = LoopRunResult(
                status="blocked",
                attempts_completed=result.attempts_completed,
                retries_used=result.retries_used,
                max_retries=result.max_retries,
                max_iterations=result.max_iterations,
                latest_run_id=result.latest_run_id,
                supervisor_verdict="blocked",
                report_path=result.report_path,
                continuation_prompt_path=result.continuation_prompt_path,
            )
        self._emit_run_finished_event(final_result, terminal_error=terminal_error)
        return final_result

    @staticmethod
    def _append_feedback(
        original_prompt: str,
        feedback_text: str,
        *,
        source: str,
    ) -> str:
        return (
            f"{original_prompt}\n\n"
            f"---\n\n"
            f"# Feedback from {source}\n\n"
            f"{feedback_text.strip()}"
        )

    def _log(self, message: str) -> None:
        print(message, file=self._progress_stream)
        self._progress_stream.flush()

    def _emit_cli_command(self, *, role: str, args: list[str], cwd: Path) -> None:
        lines = (
            f"=== pipeline {role} cli ===",
            f"command: {' '.join(args)}",
            f"cwd: {cwd}",
        )
        for line in lines:
            print(line, file=self._progress_stream)
        self._progress_stream.flush()

    def _emit_cli_output(
        self,
        *,
        role: str,
        stdout_text: str,
        stderr_text: str,
    ) -> None:
        stdout_lines = stdout_text.rstrip() if stdout_text.strip() else "(empty)"
        stderr_lines = stderr_text.rstrip() if stderr_text.strip() else "(empty)"
        print(f"=== pipeline {role} stdout ===", file=self._progress_stream)
        print(stdout_lines, file=self._progress_stream)
        print(f"=== pipeline {role} stderr ===", file=self._progress_stream)
        print(stderr_lines, file=self._progress_stream)
        self._progress_stream.flush()


def _strip_goal_source_tag(text: str) -> str:
    """Remove the dormammu:goal_source metadata comment from prompt text."""
    return _GOAL_SOURCE_TAG_RE.sub("", text, count=1).lstrip()
