from __future__ import annotations

from dormammu.daemon.models import DaemonPromptResult


def render_result_markdown(result: DaemonPromptResult) -> str:
    lines = [
        f"# Result: {result.prompt_path.name}",
        "",
        "## Summary",
        "",
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
