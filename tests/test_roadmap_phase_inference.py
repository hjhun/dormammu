from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu._cli_utils import _resolve_bootstrap_inputs
from dormammu.config import AppConfig
from dormammu.state import StateRepository
from dormammu.state.models import infer_primary_roadmap_phase_id


def test_infer_primary_roadmap_phase_id_prefers_explicit_phase_prompt_over_guidance_noise() -> None:
    prompt_text = """# Phase 06 Prompt: MCP Registration and Resolution

## Objective

Implement MCP server registration and resolution for Phase 6 from `docs/PLAN.md`.

## Guidance

0. Refine
1. Plan
2. Design
"""

    assert (
        infer_primary_roadmap_phase_id(prompt_text=prompt_text)
        == "phase_6"
    )


def test_infer_primary_roadmap_phase_id_reads_embedded_task_prompt_from_continuation_wrapper() -> None:
    prompt_text = """You are continuing a previous coding-agent attempt inside the same repository.

Recommended resume phase: plan

Original prompt:
Follow the guidance files below before making changes.

Task prompt:
# Phase 06 Prompt: MCP Registration and Resolution

## Objective

Implement MCP server registration and resolution for Phase 6 from `docs/PLAN.md`.
"""

    assert infer_primary_roadmap_phase_id(prompt_text=prompt_text) == "phase_6"


def test_resolve_bootstrap_inputs_infers_roadmap_phase_from_prompt_text(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    config = AppConfig.load(
        repo_root=repo_root,
        env={
            "HOME": str(home_dir),
            **{key: value for key, value in os.environ.items() if key != "HOME"},
        },
    )
    repository = StateRepository(config)

    _, roadmap_phases = _resolve_bootstrap_inputs(
        repository=repository,
        goal=None,
        roadmap_phases=None,
        default_phase="phase_4",
        prompt_text="# Phase 06 Prompt: MCP Registration and Resolution",
        prompt_text_provided=True,
    )

    assert roadmap_phases == ["phase_6"]


def test_resolve_bootstrap_inputs_infers_roadmap_phase_from_continuation_prompt_text(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    config = AppConfig.load(
        repo_root=repo_root,
        env={
            "HOME": str(home_dir),
            **{key: value for key, value in os.environ.items() if key != "HOME"},
        },
    )
    repository = StateRepository(config)

    continuation_prompt = """You are continuing a previous coding-agent attempt inside the same repository.

Recommended resume phase: plan

Original prompt:
Follow the guidance files below before making changes.

Task prompt:
# Phase 06 Prompt: MCP Registration and Resolution
"""

    _, roadmap_phases = _resolve_bootstrap_inputs(
        repository=repository,
        goal=None,
        roadmap_phases=None,
        default_phase="phase_4",
        prompt_text=continuation_prompt,
        prompt_text_provided=True,
    )

    assert roadmap_phases == ["phase_6"]
