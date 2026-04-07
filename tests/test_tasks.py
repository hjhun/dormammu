from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.state import parse_tasks_document


class TaskParsingTests(unittest.TestCase):
    def test_parse_tasks_document_collects_checkbox_summary(self) -> None:
        parsed = parse_tasks_document(
            "\n".join(
                [
                    "# TASKS",
                    "",
                    "## Current Workflow",
                    "",
                    "- [O] First task",
                    "- [x] Second task",
                    "- [ ] Third task",
                    "",
                    "## Resume Checkpoint",
                    "",
                    "Resume from the third task.",
                    "",
                ]
            )
        )

        sync_state = parsed.current_workflow
        self.assertEqual(sync_state.total_tasks, 3)
        self.assertEqual(sync_state.completed_tasks, 2)
        self.assertEqual(sync_state.pending_tasks, 1)
        self.assertEqual(sync_state.next_pending_task, "Third task")
        self.assertEqual(sync_state.resume_checkpoint, "Resume from the third task.")


if __name__ == "__main__":
    unittest.main()
