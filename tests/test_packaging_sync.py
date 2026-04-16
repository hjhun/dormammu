"""Packaging verification: agents/ source bundle must match packaged assets.

Fails if ``agents/`` and ``backend/dormammu/assets/agents/`` have diverged.
Run ``scripts/sync-agents.sh`` to fix a failure.
"""
from __future__ import annotations

import filecmp
import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SOURCE = _REPO_ROOT / "agents"
_PACKAGED = _REPO_ROOT / "backend" / "dormammu" / "assets" / "agents"


def _collect_relative_paths(root: Path) -> set[str]:
    """Return all relative file paths under *root*."""
    result: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = Path(dirpath) / name
            result.add(str(full.relative_to(root)))
    return result


class TestAgentsBundleSync:
    """The packaged agents bundle must be an exact mirror of the source bundle."""

    def test_source_and_packaged_have_same_file_set(self) -> None:
        source_files = _collect_relative_paths(_SOURCE)
        packaged_files = _collect_relative_paths(_PACKAGED)
        only_in_source = source_files - packaged_files
        only_in_packaged = packaged_files - source_files
        errors: list[str] = []
        if only_in_source:
            errors.append(
                "Files in agents/ missing from packaged bundle:\n  "
                + "\n  ".join(sorted(only_in_source))
            )
        if only_in_packaged:
            errors.append(
                "Files in packaged bundle not present in agents/:\n  "
                + "\n  ".join(sorted(only_in_packaged))
            )
        assert not errors, (
            "agents/ and backend/dormammu/assets/agents/ have diverged.\n"
            + "\n".join(errors)
            + "\nRun scripts/sync-agents.sh to fix."
        )

    def test_source_and_packaged_file_contents_match(self) -> None:
        relative_paths = _collect_relative_paths(_SOURCE)
        mismatched: list[str] = []
        for rel in sorted(relative_paths):
            src_file = _SOURCE / rel
            pkg_file = _PACKAGED / rel
            if not pkg_file.exists():
                continue  # caught by the file-set test above
            if not filecmp.cmp(src_file, pkg_file, shallow=False):
                mismatched.append(rel)
        assert not mismatched, (
            "agents/ and backend/dormammu/assets/agents/ have diverged "
            "(content mismatch):\n  "
            + "\n  ".join(mismatched)
            + "\nRun scripts/sync-agents.sh to fix."
        )
