"""PipelineRunner — orchestrates the role-based agent pipeline.

Pipeline stages
---------------
developer → tester (loop back to developer on FAIL) →
reviewer  (loop back to developer on NEEDS_WORK)  →
committer

Each stage writes a document to ``.dev/<slot>-<role>/<date>_<stem>.md``.
The developer stage reuses the existing :class:`LoopRunner` so the full
supervisor loop is preserved.  The tester, reviewer, and committer stages
are one-shot agent calls: the agent runs once, produces a report/action,
and the pipeline interprets the result.

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

from dormammu.loop_runner import LoopRunRequest, LoopRunResult, LoopRunner
from dormammu.state import StateRepository

if TYPE_CHECKING:
    from dormammu.agent.role_config import AgentsConfig
    from dormammu.config import AppConfig

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
    ) -> LoopRunResult:
        """Execute the full pipeline and return a :class:`LoopRunResult`."""
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        dev_prompt = prompt_text
        loop_result: LoopRunResult | None = None

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

        assert loop_result is not None
        return loop_result

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

    def _tester_prompt(self, goal_text: str, *, stem: str, date_str: str) -> str:
        return (
            "You are a black-box tester. Test the implementation described by the "
            "goal below WITHOUT looking at internal implementation details.\n\n"
            "Your task:\n"
            "1. Design test cases that verify the behaviour described in the goal.\n"
            "2. Execute each test case.\n"
            "3. Record each test case as PASS or FAIL with reproduction steps for failures.\n"
            "4. On the LAST line of your report write EITHER:\n"
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
            "You are a code reviewer. Review the implementation for correctness "
            "and adherence to the design.\n\n"
            "Check for:\n"
            "1. Correctness of logic against the goal and design.\n"
            "2. Coding rule violations or anti-patterns.\n"
            "3. Hard-coded values tied to a specific purpose that should be "
            "   generalised.\n"
            "4. Items from the architect design that are missing in the code.\n\n"
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
            "You are a Git committer. Create a commit for the completed "
            "implementation.\n\n"
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
