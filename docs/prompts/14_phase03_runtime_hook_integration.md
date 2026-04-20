# Phase 03 Prompt: Runtime Hook Integration

## Objective

Integrate hooks into the runtime lifecycle for Phase 3 from `docs/PLAN.md`.

## Background

The codebase already has visible lifecycle boundaries:

- pipeline stage start points in `backend/dormammu/daemon/pipeline_runner.py`
- loop execution flow in `backend/dormammu/loop_runner.py`
- evaluator stage execution in `backend/dormammu/daemon/evaluator.py`

This slice should connect the hook runner to those lifecycle points without scattering hook logic everywhere.

## Problem

Hook execution is only useful once it is attached to real runtime boundaries. If integration is done poorly, it will create duplicated logic and unclear semantics around:

- stage start
- stage completion
- prompt intake
- final verification
- session end

## Task

Integrate the hook system into the runtime at the highest-value lifecycle points.

Start with the recommended initial hook points from `docs/PLAN.md` where they already map cleanly to current code paths:

- prompt intake
- plan start
- stage start
- stage completion
- final verification
- session end

If tool execution is already easy to isolate, include it. If not, document the gap and keep the patch narrow.

## Design Guidance

- Centralize hook invocation through the hook runner.
- Avoid custom hook behavior embedded directly in each stage implementation.
- Preserve current behavior when no hooks are configured.
- Ensure blocking outcomes are translated into clear runtime behavior.

## Constraints

- Do not redesign the full pipeline state machine in this slice.
- Do not implement unrelated feature work such as worktrees or MCP.
- Keep interactive and goals-scheduler paths compatible.

## Acceptance Criteria

- Hooks are invoked at real runtime lifecycle points.
- The runtime behaves exactly as before when hooks are absent.
- Blocking and annotation behavior is explicit and testable.
- Integration remains centralized enough that future hook points can be added consistently.

## Validation

Add or update tests for:

- no hooks configured
- stage-start hooks
- stage-completion hooks
- blocking behavior at one or more lifecycle points
- non-blocking annotation or warning behavior
- session-end behavior if integrated in this slice

## Deliverable

Produce a focused patch that wires the hook runner into key runtime lifecycle points while preserving existing behavior when hooks are not configured.
