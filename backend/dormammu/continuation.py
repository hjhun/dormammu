from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from dormammu.supervisor import SupervisorReport


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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
) -> ContinuationPrompt:
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

    task_line = next_task or "Review the latest supervisor report and continue from the saved state."
    lines = [
        "You are continuing a previous coding-agent attempt inside the same repository.",
        "Continue from the saved repository state instead of starting over.",
        "",
        f"Latest run id: {latest_run.get('run_id', 'unknown')}",
        f"Previous prompt artifact: {artifacts.get('prompt', 'unknown')}",
        f"Previous stdout artifact: {artifacts.get('stdout', 'unknown')}",
        f"Previous stderr artifact: {artifacts.get('stderr', 'unknown')}",
        f"Supervisor report: {report.report_path or '.dev/supervisor_report.md'}",
        "",
        f"Supervisor verdict: {report.verdict}",
        f"Supervisor summary: {report.summary}",
        "",
        "Address these findings before you finish:",
        *findings,
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
