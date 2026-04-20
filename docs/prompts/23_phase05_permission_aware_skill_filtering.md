# Phase 05 Prompt: Permission-Aware Skill Filtering

## Objective

Implement permission-aware skill filtering for Phase 5 from `docs/PLAN.md`.

## Background

Earlier phases establish:

- typed agent profiles
- permission rulesets
- manifest-backed extensibility
- a runtime skill model and discovery path

The next step is to make loaded skills visible per agent profile without widening permissions globally.

## Problem

Even if skills can be discovered, they are not safe or useful unless the runtime can decide which skills are available to which agent profiles.

That requires a permission-aware filtering layer instead of one global undifferentiated skill list.

## Task

Implement permission-aware skill filtering for runtime skills.

The implementation should:

- evaluate which skills are visible to a given agent profile
- support default behavior when no skill-specific rules are configured
- support preloaded, allowed, or denied skills per profile
- keep filtering deterministic and inspectable

## Design Requirements

- Filtering must build on the Phase 1 permission model rather than inventing a separate policy system.
- Skill visibility should be computed centrally.
- The result should be reusable in future prompt assembly, runtime logging, and inspect commands.

## Constraints

- Do not redesign the whole permission system here.
- Do not yet rework every runtime path to consume filtered skills.
- Avoid embedding skill policy logic into unrelated modules.

## Acceptance Criteria

- The runtime can compute the effective visible skill set for an agent profile.
- Profile-level allow/deny or preload behavior is explicit and testable.
- Default behavior is safe and deterministic.
- The filtering contract is reusable by later runtime integrations.

## Validation

Add or update tests for:

- default skill visibility
- profile-specific deny behavior
- profile-specific preload behavior if introduced here
- duplicate-name behavior after precedence resolution
- filtering behavior for built-in versus project/user skills

## Deliverable

Submit a focused patch that adds permission-aware skill filtering and tests.
