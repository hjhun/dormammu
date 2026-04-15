"""Compiled regular expressions shared across the daemon package.

Each pattern group is documented with its purpose and which modules consume it.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Pipeline stage verdict patterns
# Used by: pipeline_runner.py
# ---------------------------------------------------------------------------

#: Matches a tester agent that explicitly reported failure.
TESTER_FAIL_RE = re.compile(r"OVERALL\s*:\s*FAIL", re.IGNORECASE)

#: Matches a reviewer agent that requested additional work.
REVIEWER_REJECT_RE = re.compile(r"VERDICT\s*:\s*NEEDS[_\s]WORK", re.IGNORECASE)

#: Matches a mid-pipeline evaluator checkpoint requesting a rework loop.
CHECKPOINT_REWORK_RE = re.compile(r"DECISION\s*:\s*REWORK", re.IGNORECASE)

#: Matches a mid-pipeline evaluator checkpoint approving forward progress.
CHECKPOINT_PROCEED_RE = re.compile(r"DECISION\s*:\s*PROCEED", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Goal-source metadata tag patterns
# Used by: runner.py (_GOAL_SOURCE_RE), pipeline_runner.py (_GOAL_SOURCE_TAG_RE)
# ---------------------------------------------------------------------------

#: Extracts the goal-source path from the metadata comment (capture group 1).
GOAL_SOURCE_RE = re.compile(
    r"^<!--\s*dormammu:goal_source=([^\s>]+)\s*-->",
    re.MULTILINE,
)

#: Matches the full metadata comment line (including trailing newlines) for removal.
GOAL_SOURCE_TAG_RE = re.compile(
    r"^<!--\s*dormammu:goal_source=[^\s>]+\s*-->\n\n?",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Daemon result-status patterns
# Used by: runner.py
# ---------------------------------------------------------------------------

#: Extracts the status field from a rendered result markdown document.
RESULT_STATUS_RE = re.compile(r"^- Status: `([^`]+)`$", re.MULTILINE)
