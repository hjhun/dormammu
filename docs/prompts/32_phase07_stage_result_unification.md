# Phase 7 Prompt 02: Stage Result Unification

## Objective

Unify stage and execution result modeling so that loop runs, pipeline stages, supervisor outputs, and evaluator outcomes share one consistent result vocabulary.

## Background

The codebase already contains partial execution result concepts:

- `StageResult` in `backend/dormammu/daemon/models.py`
- pipeline and daemon result containers
- supervisor-generated reports
- evaluator verdict files and report paths
- state repository updates that infer current and latest run status

These pieces are useful, but they do not yet form one coherent result model.

## Problem

Result handling is currently spread across multiple abstractions with overlapping responsibilities. That creates ambiguity around:

- what counts as a stage result versus a report artifact
- how verdicts should be normalized across roles
- how retry, partial completion, and blocked states should be represented
- how higher-level run summaries should be assembled from stage-level outcomes

This inconsistency makes downstream state persistence, dashboards, and tests more brittle.

## Task

Design and implement a unified stage result model that all execution paths can use.

The model should define:

- the canonical representation of a stage outcome
- how artifacts attach to a stage result
- how a run-level result aggregates stage results
- how verdicts and statuses are normalized across role-specific workflows

## Design Requirements

- Review current result objects in:
  - `backend/dormammu/daemon/models.py`
  - loop and pipeline runner modules
  - supervisor and evaluator report generation paths
- Introduce or refactor toward a shared result module with explicit contracts
- Distinguish clearly between:
  - stage status
  - verdict
  - textual output
  - artifact references
  - retry metadata
  - timing metadata
- Ensure the result model works for:
  - developer stages
  - tester verdicts
  - reviewer verdicts
  - evaluator checkpoint decisions
  - loop-only runs without named pipeline stages

## Result Modeling Guidance

The design should support at least these ideas:

- a stage may succeed operationally while producing a domain verdict like `NEEDS_WORK`
- a stage may fail before producing a valid verdict
- a stage may emit one or more artifacts such as reports, logs, or transcripts
- run-level success should not depend on ad hoc string parsing spread across modules

Favor explicit enums or normalized constants over free-form status strings where practical.

## Constraints

- Do not remove useful existing information from results
- Preserve compatibility with current reporting behavior where feasible
- Avoid designs that force every stage to materialize the same heavy payload
- Keep the model serializable for state persistence and test fixtures

## Acceptance Criteria

- The runtime has one canonical stage result contract
- Existing execution flows use the shared result shape instead of divergent local structures
- Reviewer and tester verdicts can be represented without special-case string parsing in multiple places
- Run-level aggregation becomes easier to reason about and test

## Validation

- Add unit tests for result normalization and aggregation
- Add integration-oriented tests covering at least one loop run and one pipeline run
- Verify artifact attachment, verdict handling, and failure cases

## Deliverable

Produce the unified result model, migrate the relevant runtime code to use it, and add tests and documentation that explain the final result semantics.
