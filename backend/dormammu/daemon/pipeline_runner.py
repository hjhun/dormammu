"""PipelineRunner — orchestrates the role-based agent pipeline.

Pipeline stages
---------------
refiner   (optional, one-shot) →
planner   (optional, one-shot) →
developer (supervised LoopRunner) →
tester    (one-shot, loops back to developer on FAIL) →
reviewer  (one-shot, loops back to developer on NEEDS_WORK) →
committer (one-shot) →
evaluator (one-shot, goals-scheduler context only)

Each stage writes a document to ``.dev/<slot>-<role>/<date>_<stem>.md``.

Refiner
-------
Converts the raw goal into a structured ``.dev/REQUIREMENTS.md``.  Skipped
when ``agents.refiner`` has no resolvable CLI.

Planner
-------
Reads ``.dev/REQUIREMENTS.md`` (if present) and generates the adaptive
``.dev/WORKFLOWS.md`` stage sequence plus updates ``.dev/PLAN.md`` and
``.dev/DASHBOARD.md``.  Skipped when ``agents.planner`` has no resolvable CLI.

Developer
---------
Reuses :class:`LoopRunner` so the full supervisor retry loop is preserved.

Re-entry limits
---------------
``MAX_STAGE_ITERATIONS`` caps the developer-tester and developer-reviewer
loops independently, preventing infinite retries.

Return value
------------
:meth:`run` returns a :class:`~dormammu.loop_runner.LoopRunResult` so that
:class:`~dormammu.daemon.runner.DaemonRunner` needs no changes to its
result-handling logic.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from dormammu.daemon.evaluator import (
    EvaluatorRequest,
    EvaluatorStage,
    resolve_evaluator_cli,
    resolve_evaluator_model,
)
from dormammu.loop_runner import LoopRunRequest, LoopRunResult, LoopRunner
from dormammu.state import StateRepository

if TYPE_CHECKING:
    from dormammu.agent.role_config import AgentsConfig
    from dormammu.config import AppConfig
    from dormammu.daemon.goals_config import EvaluatorConfig

MAX_STAGE_ITERATIONS = 3

# Patterns used to parse one-shot agent output.
_TESTER_FAIL_RE = re.compile(r"OVERALL\s*:\s*FAIL", re.IGNORECASE)
_TESTER_PASS_RE = re.compile(r"OVERALL\s*:\s*PASS", re.IGNORECASE)
_REVIEWER_reject_RE = re.compile(r"VERDICT\s*:\s*NEEDS[_\s]WORK", re.IGNORECASE)
_REVIEWER_APPROVE_RE = re.compile(r"VERDICT\s*:\s*APPROVED", re.IGNORECASE)

_DEFAULT_MAX_RETRIES = 49


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
    ) -> None:
        self._app_config = app_config
        self._agents = agents_config
        self._repository = repository or StateRepository(app_config)
        self._progress_stream = progress_stream or sys.stderr

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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

        ``goal_file_path`` and ``evaluator_config`` are both required for the
        evaluator stage to run.  When either is None the evaluator is skipped.
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        dev_prompt = prompt_text
        loop_result: LoopRunResult | None = None

        # ---- refiner (optional) ---------------------------------------------
        self._run_refiner(prompt_text, stem=stem, date_str=date_str)

        # ---- planner (optional) ---------------------------------------------
        self._run_planner(prompt_text, stem=stem, date_str=date_str)

        # ---- developer → tester loop ----------------------------------------
        for tester_iter in range(MAX_STAGE_ITERATIONS):
            loop_result = self._run_developer(dev_prompt, stem=stem)
            if loop_result.status not in ("completed",):
                self._log(
                    f"pipeline: developer stage ended with status "
                    f"'{loop_result.status}' — aborting pipeline"
                )
                return loop_result

            tester_report = self._run_tester(prompt_text, stem=stem, date_str=date_str)
            if tester_report is None:
                # Tester not configured — skip tester stage
                break
            verdict, report_text = tester_report
            if verdict == "pass":
                self._log(f"pipeline: tester PASS (iteration {tester_iter + 1})")
                break
            if tester_iter < MAX_STAGE_ITERATIONS - 1:
                self._log(
                    f"pipeline: tester FAIL (iteration {tester_iter + 1}) "
                    "— re-entering developer"
                )
                dev_prompt = self._append_feedback(
                    prompt_text, report_text, source="tester"
                )
            else:
                self._log(
                    f"pipeline: tester FAIL — max iterations ({MAX_STAGE_ITERATIONS}) "
                    "reached; continuing to reviewer"
                )

        # ---- developer → reviewer loop --------------------------------------
        for reviewer_iter in range(MAX_STAGE_ITERATIONS):
            reviewer_report = self._run_reviewer(
                prompt_text, stem=stem, date_str=date_str
            )
            if reviewer_report is None:
                # Reviewer not configured — skip
                break
            verdict, report_text = reviewer_report
            if verdict == "approved":
                self._log(f"pipeline: reviewer APPROVED (iteration {reviewer_iter + 1})")
                break
            if reviewer_iter < MAX_STAGE_ITERATIONS - 1:
                self._log(
                    f"pipeline: reviewer NEEDS_WORK (iteration {reviewer_iter + 1}) "
                    "— re-entering developer"
                )
                dev_prompt = self._append_feedback(
                    prompt_text, report_text, source="reviewer"
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
    # Refiner stage (one-shot, optional)
    # ------------------------------------------------------------------

    def _run_refiner(
        self, goal_text: str, *, stem: str, date_str: str
    ) -> str | None:
        """Run the refiner agent once.

        Produces ``.dev/REQUIREMENTS.md`` and saves the output document to
        ``.dev/00-refiner/<date>_<stem>.md``.

        Returns the agent output string, or ``None`` if the refiner role has
        no resolvable CLI (stage is skipped).
        """
        refiner_cfg = self._agents.for_role("refiner")
        # Refiner is opt-in: only run when agents.refiner.cli is explicitly set.
        # Do NOT fall back to active_agent_cli so that existing single-agent
        # setups are unaffected.
        cli = refiner_cfg.cli
        if cli is None:
            self._log("pipeline: refiner has no explicit CLI — skipping refine stage")
            return None

        self._log("pipeline: refiner stage starting")
        prompt = self._refiner_prompt(goal_text, stem=stem, date_str=date_str)
        output = self._call_once(
            role="refiner",
            cli=cli,
            model=refiner_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            slot="00",
        )
        self._log("pipeline: refiner stage completed")
        return output

    # ------------------------------------------------------------------
    # Planner stage (one-shot, optional)
    # ------------------------------------------------------------------

    def _run_planner(
        self, goal_text: str, *, stem: str, date_str: str
    ) -> str | None:
        """Run the planner agent once.

        Reads ``.dev/REQUIREMENTS.md`` (produced by the refiner) if it exists,
        then instructs the agent to generate ``.dev/WORKFLOWS.md`` and update
        ``.dev/PLAN.md`` / ``.dev/DASHBOARD.md``.

        Saves output to ``.dev/01-planner/<date>_<stem>.md``.

        Returns the agent output string, or ``None`` if the planner role has
        no resolvable CLI (stage is skipped).
        """
        planner_cfg = self._agents.for_role("planner")
        # Planner is opt-in: only run when agents.planner.cli is explicitly set.
        # Do NOT fall back to active_agent_cli so that existing single-agent
        # setups are unaffected.
        cli = planner_cfg.cli
        if cli is None:
            self._log("pipeline: planner has no explicit CLI — skipping plan stage")
            return None

        self._log("pipeline: planner stage starting")
        requirements_text = self._read_requirements_doc()
        prompt = self._planner_prompt(
            goal_text, requirements_text, stem=stem, date_str=date_str
        )
        output = self._call_once(
            role="planner",
            cli=cli,
            model=planner_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            slot="01",
        )
        self._log("pipeline: planner stage completed")
        return output

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
            progress_stream=self._progress_stream,
        ).run(request)
        self._log(f"pipeline: developer stage completed with status '{result.status}'")
        return result

    # ------------------------------------------------------------------
    # Tester stage (one-shot)
    # ------------------------------------------------------------------

    def _run_tester(
        self, goal_text: str, *, stem: str, date_str: str
    ) -> tuple[str, str] | None:
        """Run the tester agent once.

        Returns ``(verdict, report_text)`` where verdict is ``"pass"`` or
        ``"fail"``, or ``None`` if the tester role has no resolvable CLI.
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
            slot="04",
        )

        if _TESTER_FAIL_RE.search(output):
            return "fail", output
        # Default to pass if the agent did not explicitly report failure.
        return "pass", output

    # ------------------------------------------------------------------
    # Reviewer stage (one-shot)
    # ------------------------------------------------------------------

    def _run_reviewer(
        self, goal_text: str, *, stem: str, date_str: str
    ) -> tuple[str, str] | None:
        """Run the reviewer agent once.

        Returns ``(verdict, report_text)`` where verdict is ``"approved"``
        or ``"needs_work"``, or ``None`` if no resolvable CLI.
        """
        reviewer_cfg = self._agents.for_role("reviewer")
        active_cli = self._app_config.active_agent_cli
        cli = reviewer_cfg.resolve_cli(active_cli)
        if cli is None:
            return None

        self._log("pipeline: reviewer stage starting")
        design_text = self._read_architect_doc(stem, date_str)
        prompt = self._reviewer_prompt(goal_text, design_text, stem=stem, date_str=date_str)
        output = self._call_once(
            role="reviewer",
            cli=cli,
            model=reviewer_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            slot="05",
        )

        if _REVIEWER_reject_RE.search(output):
            return "needs_work", output
        return "approved", output

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
        prompt = self._committer_prompt(stem)
        self._call_once(
            role="committer",
            cli=cli,
            model=committer_cfg.model,
            prompt=prompt,
            stem=stem,
            date_str=date_str,
            slot="06",
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
        """Run the evaluator stage if all conditions are met.

        Conditions for execution:
        1. ``goal_file_path`` is not None (pipeline was triggered by goals scheduler).
        2. ``evaluator_config`` is not None and ``evaluator_config.enabled`` is True.
        3. The evaluator has a resolvable CLI.
        """
        if goal_file_path is None or evaluator_config is None:
            return
        if not evaluator_config.enabled:
            self._log("pipeline: evaluator disabled in config — skipping")
            return

        evaluator_cfg = self._agents.for_role("evaluator")
        active_cli = self._app_config.active_agent_cli
        cli = resolve_evaluator_cli(
            evaluator_config,
            evaluator_cfg.resolve_cli(None),  # agents.evaluator.cli only
            active_cli,
        )
        if cli is None:
            self._log("pipeline: evaluator has no resolvable CLI — skipping")
            return

        model = resolve_evaluator_model(evaluator_config, evaluator_cfg.model)

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
            next_goal_strategy=evaluator_config.next_goal_strategy,
            stem=stem,
            date_str=date_str,
        )
        result = EvaluatorStage(
            progress_stream=self._progress_stream,
        ).run(request)
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
        slot: str,
    ) -> str:
        """Run an agent CLI once and return its stdout."""
        from dormammu.agent.presets import preset_for_executable_name

        executable_name = cli.name
        preset = preset_for_executable_name(executable_name)

        args: list[str] = [str(cli)]
        stdin_input: str | None = None
        tmp_path: Path | None = None

        if preset is not None:
            args.extend(preset.command_prefix)
            args.extend(preset.default_extra_args)

        extra = _model_args(executable_name, model)
        args.extend(extra)

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

        try:
            result = subprocess.run(
                args,
                input=stdin_input,
                capture_output=True,
                text=True,
                cwd=str(self._app_config.repo_root),
            )
            output = result.stdout or ""

            # Persist the agent output as a role document.
            doc_dir = self._app_config.base_dev_dir / f"{slot}-{role}"
            doc_dir.mkdir(parents=True, exist_ok=True)
            doc_path = doc_dir / f"{date_str}_{stem}.md"
            doc_path.write_text(
                f"# {role.capitalize()} — {stem}\n\n{output}",
                encoding="utf-8",
            )
            self._log(f"pipeline: {role} document → {doc_path}")
            return output
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Internal — prompt builders
    # ------------------------------------------------------------------

    def _refiner_prompt(self, goal_text: str, *, stem: str, date_str: str) -> str:
        return (
            "Follow the Pipeline Stage Protocol from AGENTS.md:\n"
            "Before starting your task, read and output the full content of "
            ".dev/DASHBOARD.md, .dev/PLAN.md, and .dev/WORKFLOWS.md (if they "
            "exist) so the current workflow state is visible in this stage's output.\n\n"
            "You are a requirement refiner. Your job is to convert the raw goal "
            "below into a structured, unambiguous requirements document that the "
            "planning agent can use without asking further questions.\n\n"
            "Your task:\n"
            "1. Read and output .dev/DASHBOARD.md, .dev/PLAN.md, and "
            ".dev/WORKFLOWS.md if they exist.\n"
            "2. Analyse the goal for ambiguities, missing scope boundaries, "
            "unspecified acceptance criteria, and open dependencies.\n"
            "3. Write .dev/REQUIREMENTS.md with these sections:\n"
            "   ## Goal — one-paragraph restatement\n"
            "   ## Scope / In Scope — explicit items that are included\n"
            "   ## Scope / Out of Scope — explicit exclusions\n"
            "   ## Acceptance Criteria — verifiable checkboxes\n"
            "   ## Constraints — technical, time, or resource limits\n"
            "   ## Dependencies — other phases, systems, or external factors\n"
            "   ## Open Questions — unresolved decisions planning must address\n"
            "   ## Risks — known risks and suggested mitigations\n"
            "4. Each acceptance criterion must be verifiable from the repository "
            "state (file exists, test passes, command succeeds). Avoid criteria "
            "like 'works correctly' or 'is intuitive'.\n"
            "5. If the goal is already clear enough, write the document "
            "immediately and note that no clarification was needed.\n\n"
            f"# Goal\n\n{goal_text.strip()}\n\n"
            f"Write .dev/REQUIREMENTS.md now, then save your report to: "
            f".dev/00-refiner/{date_str}_{stem}.md"
        )

    def _planner_prompt(
        self,
        goal_text: str,
        requirements_text: str | None,
        *,
        stem: str,
        date_str: str,
    ) -> str:
        req_section = (
            f"\n\n# Refined Requirements\n\n{requirements_text.strip()}"
            if requirements_text
            else ""
        )
        return (
            "Follow the Pipeline Stage Protocol from AGENTS.md:\n"
            "Before starting your task, read and output the full content of "
            ".dev/DASHBOARD.md, .dev/PLAN.md, and .dev/WORKFLOWS.md (if they "
            "exist) so the current workflow state is visible in this stage's output.\n\n"
            "You are a planning agent. Your job is to turn the goal and refined "
            "requirements into an actionable, adaptive workflow plan.\n\n"
            "Your task:\n"
            "1. Read and output .dev/DASHBOARD.md, .dev/PLAN.md, and "
            ".dev/WORKFLOWS.md if they exist.\n"
            "2. Read agents/skills/planning-agent/SKILL.md for the full planning "
            "protocol and WORKFLOWS.md format.\n"
            "3. Generate .dev/WORKFLOWS.md — the adaptive, task-specific stage "
            "sequence. Use [ ] for pending steps and [O] for completed steps. "
            "Include only the stages this task genuinely needs. Insert evaluator "
            "checkpoints where complexity or risk warrants them.\n"
            "4. Update .dev/PLAN.md with the prompt-derived phase checklist "
            "using [ ] Phase N. <title> for pending and [O] Phase N. <title> "
            "for completed items.\n"
            "5. Update .dev/DASHBOARD.md with the real current progress, active "
            "phase, next action, and any risks.\n"
            "6. Record any open questions from the requirements as blockers if "
            "they cannot be resolved without human input.\n\n"
            "Planning rules:\n"
            "- Keep phases outcome-focused, not tool-focused.\n"
            "- Prefer 4-8 top-level phase items for the active scope.\n"
            "- WORKFLOWS.md is the authoritative process map for this task.\n"
            "- Preserve existing completed work unless the state is clearly wrong.\n\n"
            f"# Goal\n\n{goal_text.strip()}"
            f"{req_section}\n\n"
            f"Write .dev/WORKFLOWS.md and update .dev/PLAN.md and "
            f".dev/DASHBOARD.md now, then save your report to: "
            f".dev/01-planner/{date_str}_{stem}.md"
        )

    def _tester_prompt(self, goal_text: str, *, stem: str, date_str: str) -> str:
        return (
            "Follow the Pipeline Stage Protocol from AGENTS.md:\n"
            "Before starting your task, read and output the full content of "
            ".dev/DASHBOARD.md, .dev/PLAN.md, and .dev/WORKFLOWS.md so the "
            "current workflow state is visible in this stage's output.\n\n"
            "You are a black-box tester. Test the implementation described by the "
            "goal below WITHOUT looking at internal implementation details.\n\n"
            "Your task:\n"
            "1. Read and output .dev/DASHBOARD.md, .dev/PLAN.md, and "
            ".dev/WORKFLOWS.md.\n"
            "2. Design test cases that verify the behaviour described in the goal.\n"
            "3. Execute each test case.\n"
            "4. Record each test case as PASS or FAIL with reproduction steps for failures.\n"
            "5. On the LAST line of your report write EITHER:\n"
            "   OVERALL: PASS\n"
            "   OR\n"
            "   OVERALL: FAIL\n\n"
            f"# Goal\n\n{goal_text.strip()}\n\n"
            f"Write your test report to: "
            f".dev/04-tester/{date_str}_{stem}.md"
        )

    def _reviewer_prompt(
        self,
        goal_text: str,
        design_text: str | None,
        *,
        stem: str,
        date_str: str,
    ) -> str:
        design_section = (
            f"\n\n# Architect Design\n\n{design_text.strip()}"
            if design_text
            else ""
        )
        return (
            "Follow the Pipeline Stage Protocol from AGENTS.md:\n"
            "Before starting your task, read and output the full content of "
            ".dev/DASHBOARD.md, .dev/PLAN.md, and .dev/WORKFLOWS.md so the "
            "current workflow state is visible in this stage's output.\n\n"
            "You are a code reviewer. Review the implementation for correctness "
            "and adherence to the design.\n\n"
            "Check for:\n"
            "1. Read and output .dev/DASHBOARD.md, .dev/PLAN.md, and "
            ".dev/WORKFLOWS.md.\n"
            "2. Correctness of logic against the goal and design.\n"
            "3. Coding rule violations or anti-patterns.\n"
            "4. Hard-coded values tied to a specific purpose that should be "
            "   generalised.\n"
            "5. Items from the architect design that are missing in the code.\n\n"
            "On the LAST line of your review write EITHER:\n"
            "   VERDICT: APPROVED\n"
            "   OR\n"
            "   VERDICT: NEEDS_WORK\n\n"
            f"# Goal\n\n{goal_text.strip()}"
            f"{design_section}\n\n"
            f"Write your review to: .dev/05-reviewer/{date_str}_{stem}.md"
        )

    def _committer_prompt(self, stem: str) -> str:
        return (
            "Follow the Pipeline Stage Protocol from AGENTS.md:\n"
            "Before starting your task, read and output the full content of "
            ".dev/DASHBOARD.md, .dev/PLAN.md, and .dev/WORKFLOWS.md so the "
            "current workflow state is visible in this stage's output.\n\n"
            "You are a Git committer. Create a commit for the completed "
            "implementation.\n\n"
            "Steps:\n"
            "1. Read and output .dev/DASHBOARD.md, .dev/PLAN.md, and "
            ".dev/WORKFLOWS.md.\n"
            "2. Inspect the working tree and confirm which files belong to the active scope.\n"
            "3. Stage only the intended files and create the commit.\n\n"
            "Commit message format:\n"
            "  <title (max 80 chars)>\n"
            "  <blank line>\n"
            "  <body — wrap at 80 chars on word boundaries>\n\n"
            "Rules:\n"
            "- English only.\n"
            "- Title must be 80 characters or fewer.\n"
            "- Separate title and body with a blank line.\n"
            "- Wrap body lines at 80 characters.\n\n"
            f"The implementation scope is: {stem}\n\n"
            "Run git add -A and git commit now."
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

    def _read_architect_doc(self, stem: str, date_str: str) -> str | None:
        """Return architect document text if it exists, else None."""
        doc = self._app_config.base_dev_dir / "02-architect" / f"{date_str}_{stem}.md"
        if doc.exists():
            return doc.read_text(encoding="utf-8")
        return None

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


def _model_args(executable_name: str, model: str | None) -> list[str]:
    """Build the model flag arguments for the given CLI and model."""
    if model is None:
        return []
    flag = _MODEL_FLAGS.get(executable_name.lower())
    if flag is None:
        return []
    return [flag, model]


_MODEL_FLAGS: dict[str, str] = {
    "claude": "--model",
    "claude-code": "--model",
    "gemini": "--model",
    "codex": "-m",
    "aider": "--model",
}

# Matches the metadata comment prepended by GoalsScheduler.
_GOAL_SOURCE_TAG_RE = re.compile(
    r"^<!--\s*dormammu:goal_source=[^\s>]+\s*-->\n\n?",
    re.MULTILINE,
)


def _strip_goal_source_tag(text: str) -> str:
    """Remove the dormammu:goal_source metadata comment from prompt text."""
    return _GOAL_SOURCE_TAG_RE.sub("", text, count=1).lstrip()
