from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from enum import Enum
from typing import Mapping, TextIO

from dormammu._utils import iso_now as _iso_now
from dormammu.agent import AgentRunRequest, CliAdapter
from dormammu.config import AppConfig
from dormammu.daemon.cli_output import select_agent_output
from dormammu.daemon.models import DaemonPromptResult


def _display_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return value


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
        f"- Status: `{_display_value(result.status)}`",
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
        lines.append(f"- Supervisor verdict: `{_display_value(result.supervisor_verdict)}`")
    if result.summary:
        lines.append(f"- Run summary: {result.summary}")
    if result.supervisor_report_path:
        lines.append(f"- Supervisor report: `{result.supervisor_report_path}`")
    if result.continuation_prompt_path:
        lines.append(f"- Continuation prompt: `{result.continuation_prompt_path}`")
    if result.error:
        lines.extend(["", "## Error", "", result.error])
    if result.stage_results:
        lines.extend(["", "## Stage Results", ""])
        for stage_result in result.stage_results:
            lines.append(f"### {stage_result.stage_name or stage_result.role}")
            lines.append("")
            lines.append(f"- Role: `{stage_result.role}`")
            lines.append(f"- Status: `{_display_value(stage_result.status)}`")
            lines.append(
                f"- Verdict: `{_display_value(stage_result.verdict) if stage_result.verdict else 'n/a'}`"
            )
            lines.append(f"- Report: `{stage_result.report_path or 'n/a'}`")
            if stage_result.summary:
                lines.append(f"- Summary: {stage_result.summary}")
            if stage_result.retry is not None:
                lines.append(
                    f"- Retry: `attempt={stage_result.retry.attempt}, "
                    f"retries_used={stage_result.retry.retries_used}, "
                    f"max_retries={stage_result.retry.max_retries}, "
                    f"max_iterations={stage_result.retry.max_iterations}`"
                )
            if stage_result.timing is not None:
                lines.append(
                    f"- Timing: `started_at={stage_result.timing.started_at or 'n/a'}, "
                    f"completed_at={stage_result.timing.completed_at or 'n/a'}, "
                    f"duration_seconds={stage_result.timing.duration_seconds if stage_result.timing.duration_seconds is not None else 'n/a'}`"
                )
            lines.append("")
    if result.artifacts:
        lines.extend(["", "## Artifacts", ""])
        for artifact in result.artifacts:
            lines.append(
                f"- `{artifact.kind}`: `{artifact.path}`"
                + (f" ({artifact.label})" if artifact.label else "")
            )
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


def _typescript_runner_env(app_config: AppConfig) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(app_config.home_dir)
    env["DORMAMMU_SESSIONS_DIR"] = str(app_config.sessions_dir)
    env["DORMAMMU_BASE_DEV_DIR"] = str(app_config.base_dev_dir)
    env["DORMAMMU_WORKSPACE_ROOT"] = str(app_config.workspace_root)
    env["DORMAMMU_WORKSPACE_PROJECT_ROOT"] = str(app_config.workspace_project_root)
    env["DORMAMMU_TMP_DIR"] = str(app_config.workspace_tmp_dir)
    env["DORMAMMU_RESULTS_DIR"] = str(app_config.results_dir)
    return env


def _run_typescript_runner_payload(
    app_config: AppConfig,
    payload: Mapping[str, object],
    *,
    progress_stream: TextIO,
) -> dict[str, object] | None:
    runner_cli = app_config.typescript_agent_runner_cli
    if runner_cli is None:
        return None
    try:
        completed = subprocess.run(
            [str(runner_cli)],
            input=json.dumps(payload, ensure_ascii=True),
            text=True,
            capture_output=True,
            check=False,
            env=_typescript_runner_env(app_config),
        )
    except Exception as exc:
        print(f"result report TypeScript bridge failed: {exc}", file=progress_stream)
        return None
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        print(
            "result report TypeScript bridge exited "
            f"{completed.returncode}{suffix}",
            file=progress_stream,
        )
        return None
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        print("result report TypeScript bridge returned invalid JSON", file=progress_stream)
        return None
    if not isinstance(result, dict):
        return None
    return result


def _result_report_authoring_expectations(
    app_config: AppConfig,
    result: DaemonPromptResult,
    *,
    generated_at: str,
    runtime_paths_text: str,
) -> dict[str, object]:
    cli = app_config.active_agent_cli
    if cli is None:
        return {
            "action": "fallback_markdown",
            "promptText": None,
            "cliPath": None,
            "repoRoot": str(app_config.repo_root),
            "workdir": str(app_config.repo_root),
            "runLabel": None,
            "generatedAt": generated_at,
            "reason": "active_agent_cli_missing",
        }
    return {
        "action": "run_configured_cli",
        "promptText": _build_result_report_prompt(
            result,
            generated_at=generated_at,
            runtime_paths_text=runtime_paths_text,
        ),
        "cliPath": str(cli),
        "repoRoot": str(app_config.repo_root),
        "workdir": str(app_config.repo_root),
        "runLabel": f"result-report-{result.prompt_path.stem}",
        "generatedAt": generated_at,
        "reason": "configured_cli_authoring_requested",
    }


def _project_typescript_result_report_authoring_decision(
    app_config: AppConfig,
    result: DaemonPromptResult,
    *,
    generated_at: str,
    runtime_paths_text: str,
    progress_stream: TextIO,
) -> dict[str, object] | None:
    payload = {
        "entrypoint": "daemon_result_report_authoring_decision",
        "result": result.to_dict(),
        "generated_at": generated_at,
        "runtime_paths_text": runtime_paths_text,
        "cli_path": (
            str(app_config.active_agent_cli)
            if app_config.active_agent_cli is not None
            else None
        ),
        "repo_root": str(app_config.repo_root),
    }
    bridge_result = _run_typescript_runner_payload(
        app_config,
        payload,
        progress_stream=progress_stream,
    )
    if bridge_result is None:
        return None
    expected = _result_report_authoring_expectations(
        app_config,
        result,
        generated_at=generated_at,
        runtime_paths_text=runtime_paths_text,
    )
    for field_name, expected_value in expected.items():
        if bridge_result.get(field_name) != expected_value:
            return None
    return expected


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
        runtime_paths_text = self._app_config.runtime_path_prompt()
        authoring_decision = _project_typescript_result_report_authoring_decision(
            self._app_config,
            result,
            generated_at=generated_at,
            runtime_paths_text=runtime_paths_text,
            progress_stream=self._progress_stream,
        )
        if authoring_decision is None:
            authoring_decision = _result_report_authoring_expectations(
                self._app_config,
                result,
                generated_at=generated_at,
                runtime_paths_text=runtime_paths_text,
            )
        if authoring_decision["action"] == "fallback_markdown":
            return render_result_markdown(result, generated_at=generated_at)

        adapter = CliAdapter(
            self._app_config.with_overrides(fallback_agent_clis=()),
            live_output_stream=self._progress_stream,
            stop_event=self._stop_event,
        )
        try:
            run = adapter.run_once(
                AgentRunRequest(
                    cli_path=Path(str(authoring_decision["cliPath"])),
                    prompt_text=str(authoring_decision["promptText"]),
                    repo_root=Path(str(authoring_decision["repoRoot"])),
                    workdir=Path(str(authoring_decision["workdir"])),
                    run_label=str(authoring_decision["runLabel"]),
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
