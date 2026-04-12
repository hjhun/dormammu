from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dormammu._utils import iso_now as _iso_now
from dormammu.supervisor import SupervisorReport


@dataclass(frozen=True, slots=True)
class ContinuationPrompt:
    generated_at: str
    text: str
    source_run_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "text": self.text,
            "source_run_id": self.source_run_id,
        }


def _safe_artifact_ref(value: Any) -> str:
    if not value:
        return "unknown"
    path_str = str(value)
    if not Path(path_str).exists():
        return f"{path_str} (missing)"
    return path_str


def load_prompt_text(latest_run: Mapping[str, Any]) -> str:
    artifacts = latest_run.get("artifacts", {})
    prompt_path = artifacts.get("prompt")
    if not prompt_path:
        return ""
    return Path(str(prompt_path)).read_text(encoding="utf-8")


def build_continuation_prompt(
    *,
    latest_run: Mapping[str, Any],
    report: SupervisorReport,
    next_task: str | None,
    original_prompt_text: str | None = None,
    repo_guidance: Mapping[str, Any] | None = None,
) -> ContinuationPrompt:
    prior_prompt = (original_prompt_text or "").strip()
    if not prior_prompt:
        prior_prompt = load_prompt_text(latest_run).strip()
    artifacts = latest_run.get("artifacts", {})
    findings: list[str] = []
    for check in report.checks:
        if not check.ok:
            findings.append(f"- {check.name}: {check.summary}")
            for detail in check.details:
                findings.append(f"  - {detail}")

    if not findings:
        findings.append("- No failing checks were recorded, but another supervised attempt was requested.")

    guidance_lines: list[str] = []
    if isinstance(repo_guidance, Mapping):
        rule_files = repo_guidance.get("rule_files")
        workflow_files = repo_guidance.get("workflow_files")
        if isinstance(rule_files, list) and rule_files:
            guidance_lines.append("Repository rules: " + ", ".join(str(item) for item in rule_files))
        if isinstance(workflow_files, list) and workflow_files:
            guidance_lines.append(
                "Repository workflows: " + ", ".join(str(item) for item in workflow_files)
            )

    task_line = next_task or "Review the latest supervisor report and continue from the saved state."
    phase_line = report.recommended_next_phase or "manual review"
    lines = [
        "You are continuing a previous coding-agent attempt inside the same repository.",
        "Continue from the saved repository state instead of starting over.",
        (
            "Work inside the current repository and its active workdir by default. "
            "If the original task explicitly requires a specific external system path "
            "such as /proc, access only that path."
        ),
        (
            "Do not inspect or modify unrelated paths outside the repository such as "
            "/tmp, /bin, or arbitrary parent directories."
        ),
        "If your CLI supports a planning mode, leave planning mode now and make the required repository edits directly.",
        "Each time you complete a PLAN.md item, describe the completed work clearly in DASHBOARD.md and then mark that PLAN.md line as [O].",
        "Do not leave a PLAN.md item unchecked if the work is actually finished, and do not mark [O] before the repository and DASHBOARD.md both reflect the completion.",
        "",
        f"Latest run id: {latest_run.get('run_id', 'unknown')}",
        f"Previous prompt artifact: {_safe_artifact_ref(artifacts.get('prompt'))}",
        f"Previous stdout artifact: {_safe_artifact_ref(artifacts.get('stdout'))}",
        f"Previous stderr artifact: {_safe_artifact_ref(artifacts.get('stderr'))}",
        f"Supervisor report: {_safe_artifact_ref(report.report_path) if report.report_path else '.dev/supervisor_report.md'}",
        "",
        f"Supervisor verdict: {report.verdict}",
        f"Supervisor summary: {report.summary}",
        f"Recommended resume phase: {phase_line}",
        "",
        *guidance_lines,
        *([""] if guidance_lines else []),
        "Investigate the root cause of every failing verification before making more changes.",
        "Address these findings before you finish:",
        *findings,
        "",
        (
            "Return to the Develop phase, repair the implementation, update validation if needed, "
            "and pass final verification again before you stop."
            if report.recommended_next_phase == "develop"
            else "Resume from the recommended phase and keep the workflow state aligned as you progress."
        ),
        "",
        f"Next unchecked task: {task_line}",
        "",
        "Original prompt:",
        prior_prompt or "(previous prompt artifact was empty)",
        "",
        "Return only after updating the repository state needed to satisfy the supervisor checks.",
    ]
    return ContinuationPrompt(
        generated_at=_iso_now(),
        text="\n".join(lines) + "\n",
        source_run_id=latest_run.get("run_id"),
    )
