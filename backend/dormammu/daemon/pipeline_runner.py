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
from typing import TYPE_CHECKING, TextIO

from dormammu.agent import CliAdapter
from dormammu.agent.models import AgentRunRequest
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
from dormammu.loop_runner import LoopRunRequest, LoopRunResult, LoopRunner
from dormammu.state import StateRepository

if TYPE_CHECKING:
    from dormammu.agent.role_config import AgentsConfig
    from dormammu.config import AppConfig
    from dormammu.daemon.goals_config import EvaluatorConfig

_DEFAULT_MAX_RETRIES = 49
MAX_STAGE_ITERATIONS = _DEFAULT_MAX_RETRIES + 1


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
                return loop_result

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
                dev_prompt = self._append_feedback(
                    prompt_text, tester_stage.output, source="tester"
                )
            else:
                self._log(
                    f"pipeline: tester FAIL — max iterations ({MAX_STAGE_ITERATIONS}) "
                    "reached; continuing to reviewer"
                )

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
                dev_prompt = self._append_feedback(
                    prompt_text, reviewer_stage.output, source="reviewer"
                )
                loop_result = self._run_developer(dev_prompt, stem=stem)
                if loop_result.status not in ("completed",):
                    return loop_result
            else:
                self._log(
                    f"pipeline: reviewer NEEDS_WORK — max iterations "
                    f"({MAX_STAGE_ITERATIONS}) reached; continuing to committer"
                )

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

        assert loop_result is not None
        return loop_result

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
        refiner_cfg = self._agents.for_role("refiner")
        cli = refiner_cfg.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            raise RuntimeError("No CLI available for refiner role.")

        self._log("pipeline: refiner stage starting")
        prompt = self._refiner_prompt(goal_text, stem=stem, date_str=date_str)
        output = self._call_once(
            role="refiner",
            cli=cli,
            model=refiner_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            save_doc=False,
        )
        self._log("pipeline: refiner stage completed")
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
        planner_cfg = self._agents.for_role("planner")
        cli = planner_cfg.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            raise RuntimeError("No CLI available for planner role.")

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
            model=planner_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            save_doc=False,
        )
        self._log("pipeline: planner stage completed")
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
        evaluator_cfg = self._agents.for_role("evaluator")
        cli = evaluator_cfg.resolve_cli(self._app_config.active_agent_cli)
        if cli is None:
            raise RuntimeError("No CLI available for mandatory evaluator role.")

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
            model=evaluator_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            doc_path=report_path,
        )

        verdict = "proceed" if _CHECKPOINT_PROCEED_RE.search(output) else "rework"
        return StageResult(role="evaluator", verdict=verdict, output=output, report_path=report_path)

    # ------------------------------------------------------------------
    # Developer stage (LoopRunner)
    # ------------------------------------------------------------------

    def _run_developer(self, prompt_text: str, *, stem: str) -> LoopRunResult:
        self._log("pipeline: developer stage starting")
        dev_cfg = self._agents.for_role("developer")
        active_cli = self._app_config.active_agent_cli
        cli = dev_cfg.resolve_cli(active_cli)
        if cli is None:
            raise RuntimeError("No CLI available for developer role.")

        extra_args = _model_args(cli.name, dev_cfg.model)
        request = LoopRunRequest(
            cli_path=cli,
            prompt_text=prompt_text,
            repo_root=self._app_config.repo_root,
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
        ).run(request)
        self._log(f"pipeline: developer stage completed with status '{result.status}'")
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
        tester_cfg = self._agents.for_role("tester")
        active_cli = self._app_config.active_agent_cli
        cli = tester_cfg.resolve_cli(active_cli)
        if cli is None:
            return None

        self._log("pipeline: tester stage starting")
        prompt = self._tester_prompt(goal_text, stem=stem, date_str=date_str)
        output = self._call_once(
            role="tester",
            cli=cli,
            model=tester_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
        )

        verdict = "fail" if _TESTER_FAIL_RE.search(output) else "pass"
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
        reviewer_cfg = self._agents.for_role("reviewer")
        active_cli = self._app_config.active_agent_cli
        cli = reviewer_cfg.resolve_cli(active_cli)
        if cli is None:
            return None

        self._log("pipeline: reviewer stage starting")
        design_text = self._read_designer_doc(stem, date_str)
        prompt = self._reviewer_prompt(goal_text, design_text, stem=stem, date_str=date_str)
        output = self._call_once(
            role="reviewer",
            cli=cli,
            model=reviewer_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
        )

        verdict = "needs_work" if _REVIEWER_REJECT_RE.search(output) else "approved"
        return StageResult(role="reviewer", verdict=verdict, output=output)

    # ------------------------------------------------------------------
    # Committer stage (one-shot)
    # ------------------------------------------------------------------

    def _run_committer(self, *, stem: str, date_str: str) -> None:
        committer_cfg = self._agents.for_role("committer")
        active_cli = self._app_config.active_agent_cli
        cli = committer_cfg.resolve_cli(active_cli)
        if cli is None:
            self._log("pipeline: committer has no CLI — skipping commit")
            return

        self._log("pipeline: committer stage starting")
        prompt = self._committer_prompt(stem, date_str=date_str)
        self._call_once(
            role="committer",
            cli=cli,
            model=committer_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
        )

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

        evaluator_cfg = self._agents.for_role("evaluator")
        active_cli = self._app_config.active_agent_cli
        cli = resolve_evaluator_cli(
            effective_config,
            evaluator_cfg.resolve_cli(None),  # agents.evaluator.cli only
            active_cli,
        )
        if cli is None:
            raise RuntimeError(
                "No CLI available for mandatory post-commit evaluator stage."
            )

        model = resolve_evaluator_model(effective_config, evaluator_cfg.model)

        # Extract the original goal text (strip the metadata comment if present).
        goal_text = _strip_goal_source_tag(prompt_text)

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
        self._log(
            f"pipeline: evaluator stage completed "
            f"(status={result.status}, verdict={result.verdict})"
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
