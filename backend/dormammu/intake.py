"""Request intake classifier for dormammu.

Classifies incoming prompts into one of four execution classes before any
workflow state is generated:

    direct_response  — analysis, explanation, review, report (no code edits)
    planning_only    — structure/design deliberation that needs planning but no code
    light_edit       — single-file edits, config fixes, doc updates
    full_workflow    — multi-file changes, new features, interface changes

The classifier uses lightweight heuristic rules over the prompt text.  It does
not call an LLM and must be fast enough to run synchronously at intake.

Classification result is stored in ``workflow_state.json`` under
``intake.request_class`` and ``intake.execution_mode`` so every later stage can
branch on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


RequestClass = Literal["direct_response", "planning_only", "light_edit", "full_workflow"]

# ── Token sets ───────────────────────────────────────────────────────────────

# Verbs and noun phrases that signal read-only or explanatory intent.
_DIRECT_RESPONSE_SIGNALS: frozenset[str] = frozenset(
    {
        "analyze",
        "analyse",
        "explain",
        "summarize",
        "summarise",
        "describe",
        "review",
        "compare",
        "audit",
        "report",
        "list",
        "show",
        "what is",
        "what are",
        "how does",
        "how do",
        "why does",
        "why do",
        "tell me",
        "find out",
        "check",
        "inspect",
        "diagnose",
        "document",  # when not paired with "write" — handled by ordering
    }
)

# Verbs that suggest a limited, contained change.
_LIGHT_EDIT_SIGNALS: frozenset[str] = frozenset(
    {
        "fix",
        "rename",
        "update",
        "correct",
        "tweak",
        "adjust",
        "bump",
        "patch",
        "comment",
        "uncomment",
        "format",
        "lint",
        "typo",
        "spelling",
        "docstring",
        "changelog",
        "readme",
        "config",
        "configuration",
        "setting",
        "version",
        "dependency",
        "dependencies",
        "upgrade",
        "downgrade",
    }
)

# Verbs and nouns that signal broad, multi-file, or interface-level work.
_FULL_WORKFLOW_SIGNALS: frozenset[str] = frozenset(
    {
        "implement",
        "add",
        "build",
        "create",
        "introduce",
        "design",
        "architect",
        "refactor",
        "restructure",
        "migrate",
        "port",
        "rewrite",
        "overhaul",
        "replace",
        "integrate",
        "develop",
        "feature",
        "module",
        "service",
        "api",
        "interface",
        "schema",
        "pipeline",
        "system",
        "end-to-end",
        "end to end",
        "multi-file",
        "multi file",
    }
)

# Markers for structure/design deliberation where the user is asking the agent
# to think through direction or workflow shape, not implement code.
_PLANNING_ONLY_SUBJECTS: frozenset[str] = frozenset(
    {
        "architecture",
        "architectural",
        "structure",
        "structural",
        "system design",
        "module boundary",
        "module boundaries",
        "workflow design",
        "technical direction",
        "design approach",
        "runtime structure",
        "execution mode",
        "run mode",
        "daemon mode",
        "pipeline shape",
        "workflow shape",
        "structural concern",
    }
)

_PLANNING_ONLY_INTENT: frozenset[str] = frozenset(
    {
        "consider",
        "think through",
        "discuss",
        "evaluate",
        "review",
        "analyze",
        "analyse",
        "reason about",
        "think deeply",
        "deep thinking",
        "deliberate",
        "weigh options",
        "propose direction",
    }
)

_IMPLEMENTATION_INTENT: frozenset[str] = frozenset(
    {
        "implement",
        "add",
        "build",
        "create",
        "introduce",
        "develop",
        "fix",
        "update",
        "refactor",
        "migrate",
        "rewrite",
    }
)

# High-risk markers that push any ambiguous classification to full_workflow.
_INTERFACE_RISK_MARKERS: frozenset[str] = frozenset(
    {
        "api",
        "interface",
        "schema",
        "contract",
        "protocol",
        "breaking change",
        "backwards compatible",
        "backward compatible",
        "public api",
        "public interface",
    }
)

# Phrases that strongly suggest testing requirements are needed.
_TESTING_MARKERS: frozenset[str] = frozenset(
    {
        "test",
        "tests",
        "unit test",
        "integration test",
        "regression",
        "coverage",
        "test suite",
    }
)


# ── Heuristic scoring ────────────────────────────────────────────────────────


def _tokens(text: str) -> str:
    """Lowercase and collapse whitespace for token matching."""
    return " ".join(text.lower().split())


def _count_matches(normalized: str, signals: frozenset[str]) -> int:
    return sum(1 for sig in signals if sig in normalized)


def _estimate_file_count(text: str) -> int:
    """Rough estimate of how many files the prompt might touch.

    Counts explicit file path references, function/class names, and phrases
    like "across", "multiple", "several", "all", "each".
    """
    normalized = _tokens(text)
    count = 0

    # Explicit file extensions
    count += len(re.findall(r"\b\w+\.\w{1,5}\b", text))

    # Scope-broadening language
    broad_terms = ("across", "multiple", "several", "all files", "each file", "everywhere")
    count += sum(1 for term in broad_terms if term in normalized)

    return count


# ── Public API ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class IntakeClassification:
    """Result of classifying a single incoming prompt.

    Attributes:
        request_class:  One of ``direct_response``, ``planning_only``,
                        ``light_edit``, or ``full_workflow``.
        confidence:     Float in [0, 1] indicating classifier certainty.
                        Values below 0.5 suggest the classification is a
                        best-guess rather than a high-confidence determination.
        rationale:      Human-readable explanation of why this class was
                        chosen.  Exposed in ``DASHBOARD.md`` and logs.
        has_interface_risk:
                        True when the prompt contains interface or API risk
                        markers.  Surfaced in machine state for downstream
                        stages.
        requires_test_strategy:
                        True when the prompt contains explicit testing
                        language, implying a test strategy should be planned
                        before implementation.
        execution_mode:
                        ``deep_thinking`` for structure/design deliberation
                        prompts that stop after refine/plan; otherwise
                        ``standard``.
    """

    request_class: RequestClass
    confidence: float
    rationale: str
    has_interface_risk: bool
    requires_test_strategy: bool
    execution_mode: str = "standard"

    def to_dict(self) -> dict[str, object]:
        return {
            "request_class": self.request_class,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "has_interface_risk": self.has_interface_risk,
            "requires_test_strategy": self.requires_test_strategy,
            "execution_mode": self.execution_mode,
        }


def classify_request(prompt_text: str) -> IntakeClassification:
    """Classify *prompt_text* into an execution class.

    The classifier is deterministic and does not call any LLM.  It scores
    signal matches across three categories, applies interface-risk and
    testing-marker overrides, then selects the class with the highest adjusted
    score.

    Args:
        prompt_text: The raw incoming prompt string.

    Returns:
        An :class:`IntakeClassification` with the selected class and metadata.
    """
    if not prompt_text or not prompt_text.strip():
        return IntakeClassification(
            request_class="direct_response",
            confidence=0.5,
            rationale="Empty or blank prompt; defaulting to direct_response.",
            has_interface_risk=False,
            requires_test_strategy=False,
            execution_mode="standard",
        )

    normalized = _tokens(prompt_text)

    direct_score = _count_matches(normalized, _DIRECT_RESPONSE_SIGNALS)
    planning_score = (
        _count_matches(normalized, _PLANNING_ONLY_SUBJECTS)
        + _count_matches(normalized, _PLANNING_ONLY_INTENT)
    )
    light_score = _count_matches(normalized, _LIGHT_EDIT_SIGNALS)
    full_score = _count_matches(normalized, _FULL_WORKFLOW_SIGNALS)
    implementation_intent = _count_matches(normalized, _IMPLEMENTATION_INTENT) > 0

    has_interface_risk = _count_matches(normalized, _INTERFACE_RISK_MARKERS) > 0
    requires_test_strategy = _count_matches(normalized, _TESTING_MARKERS) > 0

    estimated_file_count = _estimate_file_count(prompt_text)

    planning_only = (
        planning_score >= 2
        and not implementation_intent
        and estimated_file_count < 3
        and not requires_test_strategy
    )

    # Interface risk or broad file scope upgrades to full_workflow unless the
    # prompt is explicitly only asking for structure/design deliberation.
    if has_interface_risk or estimated_file_count >= 3:
        if planning_only:
            planning_score += 2
        else:
            full_score += 2

    # Explicit test requirements mean we need planning and test authoring.
    if requires_test_strategy:
        full_score += 1

    # Resolve ties: full > light > direct unless the dedicated planning-only
    # guard above proves this is structure deliberation without implementation.
    total = direct_score + planning_score + light_score + full_score or 1

    if planning_only and planning_score >= full_score:
        chosen = "planning_only"
        confidence = planning_score / total
        rationale = (
            f"Matched {planning_score} planning-only structure/design signal(s). "
            "No implementation intent detected, so deep_thinking mode will stop "
            "after refine/plan without developer or tester stages."
        )
    elif full_score > light_score and full_score > direct_score:
        chosen: RequestClass = "full_workflow"
        confidence = full_score / total
        rationale = (
            f"Matched {full_score} full-workflow signal(s). "
            + (f"Interface risk detected. " if has_interface_risk else "")
            + (f"Estimated file count {estimated_file_count}. " if estimated_file_count >= 3 else "")
            + (f"Test strategy markers found. " if requires_test_strategy else "")
        ).rstrip()
    elif light_score > direct_score:
        chosen = "light_edit"
        confidence = light_score / total
        rationale = (
            f"Matched {light_score} light-edit signal(s) with no dominant "
            "full-workflow indicator."
        )
    elif direct_score > 0:
        chosen = "direct_response"
        confidence = direct_score / total
        rationale = (
            f"Matched {direct_score} direct-response signal(s). "
            "No edit or implementation intent detected."
        )
    else:
        # No signal matched — treat as direct_response with low confidence.
        chosen = "direct_response"
        confidence = 0.4
        rationale = (
            "No clear signals matched. Defaulting to direct_response with low "
            "confidence. Operator should verify the workflow depth."
        )

    return IntakeClassification(
        request_class=chosen,
        confidence=round(confidence, 3),
        rationale=rationale.strip(),
        has_interface_risk=has_interface_risk,
        requires_test_strategy=requires_test_strategy,
        execution_mode="deep_thinking" if chosen == "planning_only" else "standard",
    )
