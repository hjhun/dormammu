from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.continuation import build_continuation_prompt
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
