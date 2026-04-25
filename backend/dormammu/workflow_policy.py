"""Workflow simplification policy for dormammu.

Given a request class (``direct_response``, ``planning_only``, ``light_edit``,
``full_workflow``),
returns the minimal set of pipeline stages that must run, the stages that are
eligible to be skipped, and the rationale for each skip decision.

The policy is deterministic and does not call any LLM.  It is computed once at
intake and stored in ``workflow_state.json`` under ``workflow_policy`` so that
every downstream stage (planner, supervisor, loop runner) can branch on it
without re-deriving the same logic.

Public API
----------
``resolve_workflow_policy(request_class)``
    Returns a :class:`WorkflowPolicy` for the given class.

``MINIMAL_WORKFLOWS``
    Dict mapping each request class to its canonical minimal stage sequence.

``SKIP_POLICY``
    Dict mapping each request class to per-stage skip decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from dormammu.intake import RequestClass


# ── Phase registry ────────────────────────────────────────────────────────────

# All known pipeline phases in their natural full-workflow order.
# Keys are the canonical machine identifiers used in workflow_state.json.
ALL_PHASES: list[str] = [
    "refine",
    "plan",
    "evaluator_check",
    "design",
    "develop",
    "test_author",
    "test_and_review",
    "final_verify",
    "commit",
    "evaluate",  # goals-scheduler only; always skipped for manual runs
]

# Human-readable phase labels for dashboard output.
PHASE_LABELS: dict[str, str] = {
    "refine": "Refine — refining-agent",
    "plan": "Plan — planning-agent",
    "evaluator_check": "Evaluator check — evaluating-agent (post-plan)",
    "design": "Design — designing-agent",
    "develop": "Develop — developing-agent",
    "test_author": "Test Author — test-authoring-agent",
    "test_and_review": "Test and Review — testing-and-reviewing",
    "final_verify": "Final Verify — supervisor gate",
    "commit": "Commit — committing-agent",
    "evaluate": "Evaluate — evaluating-agent (goals-scheduler only)",
}


# ── Skip policy ───────────────────────────────────────────────────────────────

# Describes which phases each request class may skip and why.
# Each entry: phase_id -> skip_rationale (non-empty = may be skipped).
# Empty string means the phase is required and must not be skipped.

_DIRECT_SKIP: dict[str, str] = {
    "refine": (
        "direct_response tasks are read-only or analysis work; "
        "REQUIREMENTS.md is not needed when no code changes are planned."
    ),
    "plan": (
        "direct_response tasks do not require a multi-phase implementation plan; "
        "a single inline execution is sufficient."
    ),
    "evaluator_check": (
        "evaluator checkpoint is only meaningful after planning; "
        "not applicable for direct_response."
    ),
    "design": (
        "no interface or implementation decisions are needed for read-only tasks."
    ),
    "develop": (
        "no code changes are expected for direct_response tasks."
    ),
    "test_author": (
        "no new code means no new tests are needed."
    ),
    "test_and_review": (
        "nothing to validate when no code was changed."
    ),
    "final_verify": (
        "supervisor verification targets code-change correctness; "
        "not applicable for read-only work."
    ),
    "commit": (
        "no repository changes to commit for direct_response tasks."
    ),
    "evaluate": (
        "goals-scheduler post-commit evaluation; not applicable for "
        "direct_response tasks."
    ),
}

_PLANNING_ONLY_SKIP: dict[str, str] = {
    "refine": "",
    "plan": "",
    "evaluator_check": (
        "planning_only tasks need a planner decision, but not the goals-style "
        "post-plan evaluator checkpoint unless explicitly scheduled."
    ),
    "design": (
        "deep_thinking structure deliberation is captured by the planner output "
        "for this request class; no separate implementation design stage is "
        "required."
    ),
    "develop": (
        "planning_only tasks are about structure or workflow direction; no "
        "product-code implementation is expected."
    ),
    "test_author": (
        "no product-code implementation means no new automated test code is "
        "required."
    ),
    "test_and_review": (
        "developer and tester loops are skipped because there is no executable "
        "implementation to validate."
    ),
    "final_verify": (
        "planner output is the terminal artifact for planning_only tasks; "
        "there is no downstream implementation slice to verify."
    ),
    "commit": (
        "planning_only runs normally produce planning artifacts only and do not "
        "require a source commit unless the user explicitly asks."
    ),
    "evaluate": (
        "goals-scheduler post-commit evaluation; not applicable for "
        "planning_only tasks."
    ),
}

_LIGHT_SKIP: dict[str, str] = {
    "refine": (
        "light_edit tasks use normalize mode (no clarifying questions); "
        "a full REQUIREMENTS.md is optional when scope is trivially bounded."
    ),
    "plan": "",  # required — even light edits need a minimal plan
    "evaluator_check": (
        "post-plan evaluator checkpoint is reserved for high-risk or ambiguous "
        "plans; light edits do not warrant this overhead."
    ),
    "design": (
        "light edits are single-file or config changes that do not require "
        "interface or contract decisions before implementation."
    ),
    "develop": "",  # required
    "test_author": (
        "test authoring is optional when the change carries no behavior risk; "
        "include when the change touches executable logic."
    ),
    "test_and_review": "",  # required — validate even light edits
    "final_verify": "",  # required
    "commit": "",  # required
    "evaluate": (
        "goals-scheduler post-commit evaluation; not applicable for "
        "manually-invoked light_edit runs."
    ),
}

_FULL_SKIP: dict[str, str] = {
    "refine": "",
    "plan": "",
    "evaluator_check": "",
    "design": "",
    "develop": "",
    "test_author": "",
    "test_and_review": "",
    "final_verify": "",
    "commit": "",
    "evaluate": (
        "final evaluating-agent is added only for goals-scheduler runs, "
        "not for manually-invoked full_workflow runs."
    ),
}

SKIP_POLICY: dict[str, dict[str, str]] = {
    "direct_response": _DIRECT_SKIP,
    "planning_only": _PLANNING_ONLY_SKIP,
    "light_edit": _LIGHT_SKIP,
    "full_workflow": _FULL_SKIP,
}


# ── Minimal workflow sequences ────────────────────────────────────────────────

# The canonical stage sequences for each request class.
# Only phases that are NOT skipped appear in these lists.
MINIMAL_WORKFLOWS: dict[str, list[str]] = {
    "direct_response": [
        # No structured phases — execute inline and optionally record to memory.
        # We represent this as an empty stage list so supervisors know not to
        # require plan/develop/commit evidence.
    ],
    "planning_only": [
        "refine",
        "plan",
    ],
    "light_edit": [
        "plan",
        "develop",
        "test_and_review",
        "final_verify",
        "commit",
    ],
    "full_workflow": [
        "refine",
        "plan",
        "evaluator_check",
        "design",
        "develop",
        "test_author",
        "test_and_review",
        "final_verify",
        "commit",
    ],
}


# ── Policy dataclass ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WorkflowPolicy:
    """Result of resolving the workflow simplification policy.

    Attributes:
        request_class:
            The intake class that drove this policy resolution.
        required_phases:
            Ordered list of phases that MUST run for this request class.
        skipped_phases:
            Ordered list of phases that are eligible to be skipped, with
            skip rationales.
        skip_rationale:
            Dict mapping skipped phase IDs to their human-readable skip reason.
        phase_labels:
            Dict mapping all phase IDs to their human-readable labels for
            dashboard display.
    """

    request_class: RequestClass
    required_phases: Sequence[str]
    skipped_phases: Sequence[str]
    skip_rationale: dict[str, str]
    phase_labels: dict[str, str] = field(default_factory=lambda: dict(PHASE_LABELS))

    def to_dict(self) -> dict[str, object]:
        return {
            "request_class": self.request_class,
            "required_phases": list(self.required_phases),
            "skipped_phases": list(self.skipped_phases),
            "skip_rationale": dict(self.skip_rationale),
        }

    def is_phase_required(self, phase: str) -> bool:
        """Return True when *phase* must not be skipped for this request class."""
        return phase in self.required_phases

    def is_phase_skipped(self, phase: str) -> bool:
        """Return True when *phase* is eligible to be skipped."""
        return phase in self.skipped_phases

    def skip_reason(self, phase: str) -> str | None:
        """Return the skip rationale for *phase*, or None if not skipped."""
        return self.skip_rationale.get(phase)

    def dashboard_summary(self) -> str:
        """Return a short operator-facing summary for DASHBOARD.md."""
        lines = [
            f"Request class: {self.request_class}",
            f"Required phases ({len(self.required_phases)}): "
            + (", ".join(self.required_phases) if self.required_phases else "none"),
            f"Skipped phases ({len(self.skipped_phases)}): "
            + (", ".join(self.skipped_phases) if self.skipped_phases else "none"),
        ]
        return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────


def resolve_workflow_policy(request_class: RequestClass) -> WorkflowPolicy:
    """Return the :class:`WorkflowPolicy` for *request_class*.

    Args:
        request_class: One of ``direct_response``, ``planning_only``,
            ``light_edit``, or ``full_workflow``.

    Returns:
        A :class:`WorkflowPolicy` encoding the required phases, skipped
        phases, and per-phase skip rationale.

    Raises:
        ValueError: If *request_class* is not a recognized value.
    """
    skip_map = SKIP_POLICY.get(request_class)
    if skip_map is None:
        raise ValueError(
            f"Unknown request_class {request_class!r}. "
            f"Expected one of: {list(SKIP_POLICY)}"
        )

    required: list[str] = []
    skipped: list[str] = []
    skip_rationale: dict[str, str] = {}

    for phase in ALL_PHASES:
        reason = skip_map.get(phase, "")
        if reason:
            skipped.append(phase)
            skip_rationale[phase] = reason
        else:
            required.append(phase)

    return WorkflowPolicy(
        request_class=request_class,
        required_phases=tuple(required),
        skipped_phases=tuple(skipped),
        skip_rationale=skip_rationale,
    )


def default_workflow_policy_state(request_class: RequestClass) -> dict[str, object]:
    """Return the ``workflow_policy`` block for workflow_state.json.

    This is a convenience wrapper around :func:`resolve_workflow_policy` that
    returns a plain dict suitable for JSON serialization.
    """
    policy = resolve_workflow_policy(request_class)
    return policy.to_dict()
