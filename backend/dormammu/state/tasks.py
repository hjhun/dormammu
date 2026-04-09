from __future__ import annotations

from dataclasses import dataclass
import re

from dormammu.state.models import OperatorTaskSyncState, TaskSyncItem


SECTION_HEADER_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
TASK_LINE_RE = re.compile(r"^- \[(?P<marker>[ OXx])\] (?P<text>.+?)\s*$")


@dataclass(frozen=True, slots=True)
class ParsedTasksDocument:
    current_workflow: OperatorTaskSyncState


def parse_tasks_document(text: str, *, source: str = ".dev/PLAN.md") -> ParsedTasksDocument:
    queue_sections = {
        "current workflow",
        "prompt-derived development queue",
        "prompt-derived implementation plan",
    }
    current_section: str | None = None
    task_items: list[TaskSyncItem] = []
    resume_lines: list[str] = []

    for raw_line in text.splitlines():
        header = SECTION_HEADER_RE.match(raw_line)
        if header:
            current_section = header.group("title").strip().lower()
            continue

        if current_section in queue_sections:
            task_match = TASK_LINE_RE.match(raw_line)
            if task_match:
                marker = task_match.group("marker")
                task_items.append(
                    TaskSyncItem(
                        text=task_match.group("text").strip(),
                        completed=marker.upper() in {"O", "X"},
                    )
                )
        elif current_section == "resume checkpoint":
            stripped = raw_line.strip()
            if stripped:
                resume_lines.append(stripped)

    return ParsedTasksDocument(
        current_workflow=OperatorTaskSyncState(
            source=source,
            resume_checkpoint="\n".join(resume_lines) or None,
            items=tuple(task_items),
        )
    )
