from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoleTaxonomyEntry:
    """Canonical role contract shared by config, profiles, and docs."""

    name: str
    scope: str
    description: str


ROLE_TAXONOMY: tuple[RoleTaxonomyEntry, ...] = (
    RoleTaxonomyEntry(
        name="refiner",
        scope="runtime",
        description="Refines the raw request into explicit implementation requirements.",
    ),
    RoleTaxonomyEntry(
        name="analyzer",
        scope="goals_autonomous_only",
        description=(
            "Analyzes scheduled goals or autonomous repository context before "
            "a runtime prompt is queued."
        ),
    ),
    RoleTaxonomyEntry(
        name="planner",
        scope="runtime_and_goals_prelude",
        description="Plans the task and updates the operator-facing workflow state.",
    ),
    RoleTaxonomyEntry(
        name="designer",
        scope="goals_prelude_only",
        description=(
            "Adds optional technical design context to goals-scheduler prompts; "
            "runtime review reads its design document when present."
        ),
    ),
    RoleTaxonomyEntry(
        name="developer",
        scope="runtime",
        description="Implements the active product-code slice under supervisor control.",
    ),
    RoleTaxonomyEntry(
        name="tester",
        scope="runtime",
        description="Runs black-box validation against the observable behavior of the slice.",
    ),
    RoleTaxonomyEntry(
        name="reviewer",
        scope="runtime",
        description="Reviews changed code for regressions, bugs, and missing coverage.",
    ),
    RoleTaxonomyEntry(
        name="committer",
        scope="runtime",
        description="Prepares validated changes for version-control handoff.",
    ),
    RoleTaxonomyEntry(
        name="evaluator",
        scope="goals_checkpoint_only",
        description="Evaluates goals-scheduler plan checkpoints and final goal completion.",
    ),
)

ROLE_NAMES: tuple[str, ...] = tuple(entry.name for entry in ROLE_TAXONOMY)
ROLE_TAXONOMY_BY_NAME: dict[str, RoleTaxonomyEntry] = {
    entry.name: entry for entry in ROLE_TAXONOMY
}

RUNTIME_PIPELINE_ROLE_NAMES: tuple[str, ...] = (
    "refiner",
    "planner",
    "developer",
    "tester",
    "reviewer",
    "committer",
)
GOALS_PRELUDE_ROLE_NAMES: tuple[str, ...] = ("analyzer", "planner", "designer")
GOALS_OR_AUTONOMOUS_ONLY_ROLE_NAMES: tuple[str, ...] = (
    "analyzer",
    "designer",
    "evaluator",
)
