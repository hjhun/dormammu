from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.continuation import (
    build_continuation_prompt,
    build_supervisor_handoff_prompt_from_agents,
)
from dormammu.supervisor import SupervisorCheck, SupervisorReport


class ContinuationPromptTests(unittest.TestCase):
    def test_build_continuation_prompt_preserves_original_prompt_instead_of_nested_retry_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "retry.prompt.txt"
            prompt_path.write_text(
                "You are continuing a previous coding-agent attempt.\n\n"
                "Original prompt:\n"
                "Nested retry prompt that should not be reused.\n",
                encoding="utf-8",
            )
            report = SupervisorReport(
                generated_at="2026-04-10T09:00:00+09:00",
                verdict="rework_required",
                escalation="rework_required",
                summary="Required output paths are still missing.",
                checks=(
                    SupervisorCheck(
                        name="required-paths",
                        ok=False,
                        summary="Required output paths are still missing.",
                    ),
                ),
                latest_run_id="run-123",
                changed_files=(),
                required_paths=("done.txt",),
                report_path=None,
            )

            continuation = build_continuation_prompt(
                latest_run={
                    "run_id": "run-123",
                    "artifacts": {"prompt": str(prompt_path)},
                },
                report=report,
                next_task="Create done.txt",
                original_prompt_text="Build a tool that reads /proc/<pid>/status and prints memory usage.",
            )

        self.assertIn("Build a tool that reads /proc/<pid>/status", continuation.text)
        self.assertNotIn("Nested retry prompt that should not be reused.", continuation.text)
        self.assertIn("describe the completed work clearly in DASHBOARD.md", continuation.text)

    def test_build_continuation_prompt_allows_task_specific_external_system_paths(self) -> None:
        report = SupervisorReport(
            generated_at="2026-04-10T09:00:00+09:00",
            verdict="rework_required",
            escalation="rework_required",
            summary="Required output paths are still missing.",
            checks=(
                SupervisorCheck(
                    name="required-paths",
                    ok=False,
                    summary="Required output paths are still missing.",
                ),
            ),
            latest_run_id="run-456",
            changed_files=(),
            required_paths=("done.txt",),
            report_path=None,
        )

        continuation = build_continuation_prompt(
            latest_run={"run_id": "run-456", "artifacts": {}},
            report=report,
            next_task="Implement the CLI",
            original_prompt_text="Read /proc/<pid>/status and report VmRSS.",
        )

        self.assertIn("If the original task explicitly requires a specific external system path", continuation.text)
        self.assertIn("such as /proc", continuation.text)
        self.assertIn("Do not inspect or modify unrelated paths outside the repository", continuation.text)


class ContinuationPromptEdgeCaseTests(unittest.TestCase):
    def _make_report(
        self,
        *,
        verdict: str = "rework_required",
        checks: tuple = (),
        recommended_next_phase: str | None = None,
    ) -> "SupervisorReport":
        return SupervisorReport(
            generated_at="2026-04-10T09:00:00+09:00",
            verdict=verdict,
            escalation=verdict,
            summary="Supervisor summary.",
            checks=checks,
            latest_run_id="run-001",
            changed_files=(),
            required_paths=(),
            report_path=None,
            recommended_next_phase=recommended_next_phase,
        )

    def test_empty_original_prompt_falls_back_to_prompt_artifact(self) -> None:
        """When original_prompt_text is empty, prompt text is loaded from the artifact file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = Path(tmpdir) / "prompt.txt"
            artifact.write_text("Original task from artifact.", encoding="utf-8")
            report = self._make_report()

            continuation = build_continuation_prompt(
                latest_run={"run_id": "r1", "artifacts": {"prompt": str(artifact)}},
                report=report,
                next_task="Do something",
                original_prompt_text="",
            )

        self.assertIn("Original task from artifact.", continuation.text)

    def test_missing_prompt_artifact_produces_placeholder(self) -> None:
        """When no artifact path is given and original_prompt_text is empty, a placeholder is written."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "r2", "artifacts": {}},
            report=report,
            next_task="Do something",
            original_prompt_text="",
        )

        self.assertIn("(previous prompt artifact was empty)", continuation.text)

    def test_no_failing_checks_produces_fallback_finding(self) -> None:
        """When all checks pass but a retry is still requested, a default finding is emitted."""
        report = self._make_report(verdict="rework_required", checks=())

        continuation = build_continuation_prompt(
            latest_run={"run_id": "r3", "artifacts": {}},
            report=report,
            next_task=None,
            original_prompt_text="Do the work.",
        )

        self.assertIn("No failing checks were recorded", continuation.text)

    def test_next_task_none_uses_default_task_line(self) -> None:
        """When next_task is None, a sensible default task line is used."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "r4", "artifacts": {}},
            report=report,
            next_task=None,
            original_prompt_text="Do the work.",
        )

        self.assertIn("Review the latest supervisor report and continue from the saved state.", continuation.text)

    def test_develop_phase_recommendation_adds_repair_instruction(self) -> None:
        """When recommended_next_phase is 'develop', the prompt includes a return-to-develop instruction."""
        report = self._make_report(recommended_next_phase="develop")

        continuation = build_continuation_prompt(
            latest_run={"run_id": "r5", "artifacts": {}},
            report=report,
            next_task="Fix the implementation",
            original_prompt_text="Build the feature.",
        )

        self.assertIn("Return to the Develop phase", continuation.text)
        self.assertIn("Recommended resume phase: develop", continuation.text)

    def test_repo_guidance_rule_files_appear_in_prompt(self) -> None:
        """When repo_guidance contains rule_files, they are listed in the continuation prompt."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "r6", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
            repo_guidance={
                "rule_files": ["AGENTS.md", "CLAUDE.md"],
                "workflow_files": [],
            },
        )

        self.assertIn("Repository rules:", continuation.text)
        self.assertIn("AGENTS.md", continuation.text)
        self.assertIn("CLAUDE.md", continuation.text)

    def test_repo_guidance_workflow_files_appear_in_prompt(self) -> None:
        """When repo_guidance contains workflow_files, they are listed in the continuation prompt."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "r7", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
            repo_guidance={
                "rule_files": [],
                "workflow_files": ["agents/workflows/refine-plan.md"],
            },
        )

        self.assertIn("Repository workflows:", continuation.text)
        self.assertIn("agents/workflows/refine-plan.md", continuation.text)

    def test_source_run_id_matches_latest_run(self) -> None:
        """The returned ContinuationPrompt.source_run_id matches the run_id in latest_run."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "my-special-run-id", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
        )

        self.assertEqual(continuation.source_run_id, "my-special-run-id")

    def test_patterns_text_appears_in_continuation_prompt(self) -> None:
        """When patterns_text is provided, it appears in the continuation prompt."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "p1", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
            patterns_text="## Patterns\n\n- Use dataclasses for state models.",
        )

        self.assertIn("## Patterns", continuation.text)
        self.assertIn("Use dataclasses for state models", continuation.text)
        self.assertIn(".dev/PATTERNS.md", continuation.text)
        self.assertIn("append any new patterns", continuation.text)

    def test_default_placeholder_patterns_are_not_injected(self) -> None:
        """When patterns file contains only the default placeholder, it is not injected."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "p2", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
            patterns_text="# Codebase Patterns\n\n(no patterns recorded yet — add entries as you discover them)\n",
        )

        self.assertNotIn(".dev/PATTERNS.md", continuation.text)


class SupervisorHandoffPromptTests(ContinuationPromptEdgeCaseTests):
    def test_handoff_prompt_uses_workflow_and_skill_documents(self) -> None:
        prompt = build_supervisor_handoff_prompt_from_agents(
            agents_dir=ROOT / "agents",
            workflow_state={
                "workflow": {
                    "active_phase": "plan",
                    "last_completed_phase": "plan",
                    "resume_from_phase": "design",
                },
                "supervisor": {"verdict": "approved"},
                "bootstrap": {
                    "repo_guidance": {
                        "rule_files": ["AGENTS.md"],
                        "workflow_files": ["agents/workflows/supervised-downstream.md"],
                    }
                },
            },
            original_prompt_text="Implement the requested feature.",
        )

        self.assertIn(
            "This workflow keeps downstream execution under the supervising-agent contract",
            prompt,
        )
        self.assertIn("Orchestrates planning, design, development", prompt)
        self.assertIn("Recommended resume phase: design", prompt)
        self.assertIn("agents/workflows/supervised-downstream.md", prompt)

    def test_none_patterns_text_does_not_add_patterns_section(self) -> None:
        """When patterns_text is None, no patterns section appears."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "p3", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
            patterns_text=None,
        )

        self.assertNotIn("Codebase patterns accumulated", continuation.text)

    def test_continuation_prompt_to_dict_has_required_keys(self) -> None:
        """ContinuationPrompt.to_dict() includes generated_at, text, and source_run_id."""
        report = self._make_report()

        continuation = build_continuation_prompt(
            latest_run={"run_id": "dict-test", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
        )
        d = continuation.to_dict()

        self.assertIn("generated_at", d)
        self.assertIn("text", d)
        self.assertIn("source_run_id", d)
        self.assertEqual(d["source_run_id"], "dict-test")
