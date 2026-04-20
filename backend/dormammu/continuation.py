from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Mapping

from dormammu._utils import iso_now as _iso_now
from dormammu.supervisor import SupervisorReport

# Packaged fallback directory — always resolvable relative to this module so
# that the template is found even when the repo's templates/ directory is
# absent (e.g. installed as a wheel).
_PACKAGED_TEMPLATES_DIR = Path(__file__).resolve().parent / "assets" / "templates"


def _load_template(templates_dir: Path | None, relative_path: str) -> Template:
    """Load a Template from *templates_dir* with a packaged-asset fallback.

    Resolution order (mirrors StateRepository._template_path):
    1. ``<templates_dir>/<relative_path>`` — project-local override
    2. ``<packaged>/<relative_path>``       — bundled asset (always present)
    """
    candidates: list[Path] = []
    if templates_dir is not None:
        candidates.append(templates_dir / relative_path)
    candidates.append(_PACKAGED_TEMPLATES_DIR / relative_path)

    for path in candidates:
        try:
            return Template(path.read_text(encoding="utf-8"))
        except OSError:
            continue

    searched = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"Continuation template not found: {searched}")


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
    runtime_paths_text: str | None = None,
    patterns_text: str | None = None,
    templates_dir: Path | None = None,
) -> ContinuationPrompt:
    """Build a continuation prompt by rendering the bundled template file.

    All agent-facing instruction text lives in
    ``templates/continuation/continuation-prompt.md.tmpl`` so it can be
    reviewed and overridden without touching Python source.  This function
    computes only the dynamic substitution values.

    Args:
        templates_dir: Project-local templates directory (``AppConfig.templates_dir``).
            When supplied, a project-level override of the template is checked
            first.  Falls back to the packaged asset when absent or missing.
    """
    prior_prompt = (original_prompt_text or "").strip()
    if not prior_prompt:
        prior_prompt = load_prompt_text(latest_run).strip()
    artifacts = latest_run.get("artifacts", {})

    # ── findings ─────────────────────────────────────────────────────────────
    findings_lines: list[str] = []
    for check in report.checks:
        if not check.ok:
            findings_lines.append(f"- {check.name}: {check.summary}")
            for detail in check.details:
                findings_lines.append(f"  - {detail}")
    if not findings_lines:
        findings_lines.append(
            "- No failing checks were recorded, but another supervised attempt was requested."
        )

    # ── optional guidance section ─────────────────────────────────────────────
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
    # When guidance is present, append a blank line so the next paragraph is
    # visually separated in the rendered prompt.
    guidance_section = ("\n".join(guidance_lines) + "\n\n") if guidance_lines else ""
    runtime_paths_section = (
        "Runtime paths for this run:\n"
        f"{runtime_paths_text.strip()}\n\n"
        if runtime_paths_text and runtime_paths_text.strip()
        else ""
    )

    # ── optional patterns section ─────────────────────────────────────────────
    _default_placeholder = "(no patterns recorded yet"
    patterns_section = ""
    if patterns_text and patterns_text.strip() and _default_placeholder not in patterns_text:
        patterns_section = "\n".join([
            "",
            "Codebase patterns accumulated from prior agent runs (.dev/PATTERNS.md):",
            "Review these patterns before making changes.",
            "After completing your work, append any new patterns you discovered to .dev/PATTERNS.md.",
            "",
            patterns_text.rstrip(),
            "",
            "End of codebase patterns.",
            "",
        ])

    # ── scalar substitution values ────────────────────────────────────────────
    phase_line = report.recommended_next_phase or "manual review"
    resume_instruction = (
        "Return to the Develop phase, repair the implementation, update validation if needed, "
        "and pass final verification again before you stop."
        if report.recommended_next_phase == "develop"
        else "Resume from the recommended phase and keep the workflow state aligned as you progress."
    )
    task_line = next_task or "Review the latest supervisor report and continue from the saved state."

    template = _load_template(
        templates_dir,
        "continuation/continuation-prompt.md.tmpl",
    )
    text = template.safe_substitute(
        latest_run_id=latest_run.get("run_id", "unknown"),
        prompt_artifact=_safe_artifact_ref(artifacts.get("prompt")),
        stdout_artifact=_safe_artifact_ref(artifacts.get("stdout")),
        stderr_artifact=_safe_artifact_ref(artifacts.get("stderr")),
        supervisor_report=(
            _safe_artifact_ref(report.report_path)
            if report.report_path
            else ".dev/supervisor_report.md"
        ),
        supervisor_verdict=report.verdict,
        supervisor_summary=report.summary,
        phase_line=phase_line,
        guidance_section=guidance_section + runtime_paths_section,
        findings="\n".join(findings_lines),
        resume_instruction=resume_instruction,
        task_line=task_line,
        patterns_section=patterns_section,
        prior_prompt=prior_prompt or "(previous prompt artifact was empty)",
    )
    return ContinuationPrompt(
        generated_at=_iso_now(),
        text=text,
        source_run_id=latest_run.get("run_id"),
    )


def build_supervisor_handoff_prompt(
    *,
    workflow_state: Mapping[str, Any],
    original_prompt_text: str,
    workflow_text: str,
    skill_text: str,
    runtime_paths_text: str | None = None,
    patterns_text: str | None = None,
) -> str:
    workflow = workflow_state.get("workflow", {})
    supervisor = workflow_state.get("supervisor", {})
    bootstrap = workflow_state.get("bootstrap", {})
    repo_guidance = (
        bootstrap.get("repo_guidance", {})
        if isinstance(bootstrap, Mapping)
        else {}
    )

    guidance_lines: list[str] = []
    if isinstance(repo_guidance, Mapping):
        rule_files = repo_guidance.get("rule_files")
        workflow_files = repo_guidance.get("workflow_files")
        if isinstance(rule_files, list) and rule_files:
            guidance_lines.append(
                "Repository rules: " + ", ".join(str(item) for item in rule_files)
            )
        if isinstance(workflow_files, list) and workflow_files:
            guidance_lines.append(
                "Repository workflows: " + ", ".join(str(item) for item in workflow_files)
            )

    _default_placeholder = "(no patterns recorded yet"
    patterns_section: list[str] = []
    if patterns_text and patterns_text.strip() and _default_placeholder not in patterns_text:
        patterns_section = [
            "",
            "Codebase patterns accumulated from prior agent runs (.dev/PATTERNS.md):",
            "Review these patterns before making changes.",
            "After completing your work, append any new patterns you discovered to .dev/PATTERNS.md.",
            "",
            patterns_text.rstrip(),
            "",
            "End of codebase patterns.",
        ]

    active_phase = workflow.get("active_phase", "unknown")
    last_completed = workflow.get("last_completed_phase", "unknown")
    resume_from = workflow.get("resume_from_phase", active_phase)
    supervisor_verdict = supervisor.get("verdict", "unknown")

    lines = [
        "Mandatory refine -> plan has already completed for this run.",
        "",
        "Workflow guidance:",
        workflow_text.strip(),
        "",
        "Skill guidance:",
        skill_text.strip(),
        "",
        "Current state snapshot:",
        f"Current workflow phase: {active_phase}",
        f"Last completed workflow phase: {last_completed}",
        f"Recommended resume phase: {resume_from}",
        f"Latest supervisor verdict: {supervisor_verdict}",
        "",
    ]
    if runtime_paths_text and runtime_paths_text.strip():
        lines.extend([
            "Runtime paths for this run:",
            runtime_paths_text.strip(),
            "",
        ])
    lines.extend([
        *guidance_lines,
        *([""] if guidance_lines else []),
        "Original prompt:",
        original_prompt_text.strip() or "(empty prompt)",
        *patterns_section,
        "",
        "Continue from the saved `.dev` state and follow the workflow and skill guidance above.",
    ])
    return "\n".join(lines) + "\n"


def build_supervisor_handoff_prompt_from_agents(
    *,
    agents_dir: Path,
    workflow_state: Mapping[str, Any],
    original_prompt_text: str,
    runtime_paths_text: str | None = None,
    patterns_text: str | None = None,
) -> str:
    from dormammu.daemon.rules import load_agent_guidance_text

    workflow_text = load_agent_guidance_text(
        agents_dir, "workflows/supervised-downstream.md"
    )
    skill_text = load_agent_guidance_text(
        agents_dir, "skills/supervising-agent/SKILL.md"
    )
    return build_supervisor_handoff_prompt(
        workflow_state=workflow_state,
        original_prompt_text=original_prompt_text,
        workflow_text=workflow_text,
        skill_text=skill_text,
        runtime_paths_text=runtime_paths_text,
        patterns_text=patterns_text,
    )
