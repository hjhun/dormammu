# Phase 05 Prompt: Runtime Skill Integration and Visibility

## Objective

Integrate the skill subsystem into runtime visibility paths for Phase 5 from `docs/PLAN.md`.

## Background

The plan calls for loaded skills to be visible in:

- logs
- operator-facing status
- role-aware runtime behavior

The codebase already has several adjacent surfaces:

- guidance prompt assembly
- continuation prompt composition
- Telegram skill-tail output
- `.dev` bootstrap metadata

## Problem

Skills are currently implied by packaged guidance and prompt composition, not exposed through a first-class runtime subsystem.

Without integration, operators cannot reliably tell:

- which skills were discovered
- which skills were available to a given profile
- which skills were actually loaded or preloaded

## Task

Integrate the runtime skill subsystem into selected visibility and status paths.

Good initial targets include:

- bootstrap or operator-facing state metadata
- logs emitted during loop or pipeline execution
- continuation or downstream prompt assembly where skill identity matters

## Design Guidance

- Keep integration centralized.
- Preserve current behavior when no extra skills are discovered.
- Distinguish skill visibility from general guidance-file visibility.
- Expose enough metadata for future `inspect-skill` support.

## Constraints

- Do not turn this into a broad prompt-system rewrite.
- Do not conflate skills with `AGENTS.md` guidance files.
- Avoid touching unrelated Telegram or operator UX behavior unless needed for a clean integration point.

## Acceptance Criteria

- The runtime exposes discovered and filtered skills through at least one operator-visible path.
- Skill metadata is visible in a structured enough form for later inspection commands.
- Existing behavior is preserved when no additional skill configuration is present.
- Integration does not duplicate discovery or filtering logic.

## Validation

Add or update tests for:

- runtime behavior with no extra skills
- runtime behavior with discovered project or user skills
- operator-visible output or metadata containing resolved skill information
- compatibility with existing guidance behavior

## Deliverable

Produce a focused patch that integrates the skill subsystem into selected runtime visibility paths while preserving current behavior.
