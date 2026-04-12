"""Parse operator-facing task documents (PLAN.md / TASKS.md) into structured state.

This module is responsible for turning the human-readable Markdown checklists
that dormammu writes to `.dev/PLAN.md` into machine-readable
:class:`OperatorTaskSyncState` objects consumed by the loop runner and daemon.

Recognised section titles (case-insensitive):
    - ``## Current Workflow``
    - ``## Prompt-Derived Development Queue``
    - ``## Prompt-Derived Implementation Plan``

Task lines inside those sections must match the format::

    - [ ] Pending task description
    - [O] Completed task description   (or [X] / [x])

A ``## Resume Checkpoint`` section, if present, is captured verbatim and
stored in :attr:`OperatorTaskSyncState.resume_checkpoint`.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from dormammu.state.models import OperatorTaskSyncState, TaskSyncItem


SECTION_HEADER_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
TASK_LINE_RE = re.compile(r"^- \[(?P<marker>[ OXx])\] (?P<text>.+?)\s*$")


@dataclass(frozen=True, slots=True)
class ParsedTasksDocument:
    """The structured result of parsing a dormammu task document.

    Attributes:
        current_workflow: Parsed task items and optional resume checkpoint
            extracted from the active workflow section of the document.
    """

    current_workflow: OperatorTaskSyncState


def parse_tasks_document(text: str, *, source: str = ".dev/PLAN.md") -> ParsedTasksDocument:
    """Parse a dormammu PLAN.md or TASKS.md document.

    Args:
        text: Full Markdown content of the document to parse.
        source: Human-readable label used as the ``source`` field on the
            returned :class:`OperatorTaskSyncState` (defaults to
            ``".dev/PLAN.md"``).

    Returns:
        A :class:`ParsedTasksDocument` whose ``current_workflow`` attribute
        contains the discovered task items and optional resume checkpoint.
        Returns an empty workflow (no items, no checkpoint) when no recognised
        section is found.
    """
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
