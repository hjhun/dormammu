from __future__ import annotations

import sys
from typing import TextIO

from dormammu._utils import iso_now as _iso_now
from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.config import AppConfig
from dormammu.daemon.cli_output import select_agent_output
from dormammu.daemon.models import DaemonPromptResult


def render_result_markdown(
    result: DaemonPromptResult,
    *,
    generated_at: str | None = None,
) -> str:
    lines = [
        f"# Result: {result.prompt_path.name}",
        "",
        "## Summary",
        "",
        f"- Generated at: `{generated_at or _iso_now()}`",
        f"- Status: `{result.status}`",
        f"- Prompt path: `{result.prompt_path}`",
        f"- Result path: `{result.result_path}`",
        f"- Session id: `{result.session_id or 'unknown'}`",
        f"- Watcher backend: `{result.watcher_backend}`",
        f"- Started at: `{result.started_at}`",
        f"- Completed at: `{result.completed_at or 'not completed'}`",
        f"- Queue sort key: `{result.sort_key}`",
    ]
    if result.status == "in_progress":
        lines.append("- Processing state: `active`")
    if result.plan_all_completed is not None:
        lines.append(f"- PLAN complete: `{'yes' if result.plan_all_completed else 'no'}`")
    if result.next_pending_task:
        lines.append(f"- Next pending PLAN task: `{result.next_pending_task}`")
    if result.attempts_completed is not None:
        lines.append(f"- Attempts completed: `{result.attempts_completed}`")
    if result.latest_run_id:
        lines.append(f"- Latest run id: `{result.latest_run_id}`")
    if result.supervisor_verdict:
        lines.append(f"- Supervisor verdict: `{result.supervisor_verdict}`")
    if result.supervisor_report_path:
        lines.append(f"- Supervisor report: `{result.supervisor_report_path}`")
    if result.continuation_prompt_path:
        lines.append(f"- Continuation prompt: `{result.continuation_prompt_path}`")
    if result.error:
        lines.extend(["", "## Error", "", result.error])
    if result.phase_results:
        lines.extend(["", "## Phases", ""])
        for phase_result in result.phase_results:
            lines.append(f"### {phase_result.phase_name}")
            lines.append("")
            lines.append(f"- Exit code: `{phase_result.exit_code}`")
            lines.append(f"- CLI: `{phase_result.cli_path}`")
            lines.append(f"- Run id: `{phase_result.run_id or 'n/a'}`")
            lines.append(f"- Prompt artifact: `{phase_result.prompt_path or 'n/a'}`")
            lines.append(f"- Stdout artifact: `{phase_result.stdout_path or 'n/a'}`")
            lines.append(f"- Stderr artifact: `{phase_result.stderr_path or 'n/a'}`")
            lines.append(f"- Metadata artifact: `{phase_result.metadata_path or 'n/a'}`")
            if phase_result.error:
                lines.append(f"- Error: {phase_result.error}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_result_report_prompt(
    result: DaemonPromptResult,
    *,
    generated_at: str,
    runtime_paths_text: str,
) -> str:
    facts = render_result_markdown(result, generated_at=generated_at).strip()
    return (
        "Write a deterministic operator-facing Markdown result report.\n\n"
        "Requirements:\n"
        "- Preserve the exact factual content provided below.\n"
        "- Include the explicit generation date and time exactly as given.\n"
        "- Keep the output concise and structured with headings and bullet points.\n"
        "- Do not invent facts that are not present in the supplied data.\n\n"
        "# Runtime Paths\n\n"
        f"{runtime_paths_text.strip()}\n\n"
        "# Structured Facts\n\n"
        f"{facts}\n"
    )


class ResultReportAuthor:
    def __init__(
        self,
        app_config: AppConfig,
        *,
        progress_stream: TextIO | None = None,
        stop_event: object | None = None,
    ) -> None:
        self._app_config = app_config
        self._progress_stream = progress_stream or sys.stderr
        self._stop_event = stop_event

    def render(self, result: DaemonPromptResult) -> str:
        generated_at = _iso_now()
        cli = self._app_config.active_agent_cli
        if cli is None:
            return render_result_markdown(result, generated_at=generated_at)

        prompt = _build_result_report_prompt(
            result,
            generated_at=generated_at,
            runtime_paths_text=self._app_config.runtime_path_prompt(),
        )
        adapter = CliAdapter(
            self._app_config.with_overrides(fallback_agent_clis=()),
            live_output_stream=self._progress_stream,
            stop_event=self._stop_event,
        )
        try:
            run = adapter.run_once(
                AgentRunRequest(
                    cli_path=cli,
                    prompt_text=prompt,
                    repo_root=self._app_config.repo_root,
                    workdir=self._app_config.repo_root,
                    run_label=f"result-report-{result.prompt_path.stem}",
                )
            )
        except Exception as exc:
            raise RuntimeError(
                f"Configured CLI failed while authoring result report for {result.prompt_path.name}."
            ) from exc

        stdout_text = run.stdout_path.read_text(encoding="utf-8") if run.stdout_path.exists() else ""
        stderr_text = run.stderr_path.read_text(encoding="utf-8") if run.stderr_path.exists() else ""
        authored = select_agent_output(stdout_text, stderr_text).strip()
        if not authored:
            raise RuntimeError(
                f"Configured CLI returned no result report content for {result.prompt_path.name}."
            )
        if "Generated at:" not in authored or generated_at not in authored:
            raise RuntimeError(
                "Configured CLI result report did not preserve the required generated-at timestamp."
            )
        return authored.rstrip() + "\n"
