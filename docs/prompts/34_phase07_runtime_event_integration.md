# Phase 7 Prompt 04: Runtime Event Integration

## Objective

Integrate the new lifecycle event, stage result, and artifact models into the active runtime flows so execution state is emitted consistently across loop, pipeline, supervisor, and daemon paths.

## Background

Phase 7 is not only about introducing new types. It also requires the runtime to actually use them across the main execution surfaces:

- loop-based execution
- pipeline-based execution
- supervisor orchestration
- daemon scheduling and run tracking

The project already records state and outputs in each of these paths, but the behavior is not yet unified around one event-driven machine-truth model.

## Problem

A schema that is not integrated into the runtime has little value. The system still needs a clear operational path for:

- emitting events at the correct lifecycle boundaries
- attaching stage results and artifacts as work progresses
- updating `.dev` state from explicit runtime facts rather than inferred strings
- preserving resumability and observability without duplicating logic everywhere

## Task

Integrate the Phase 7 event and artifact infrastructure into the runtime.

Focus on practical integration points where execution already transitions state:

- run start and finish
- stage handoff and completion
- supervisor validation checkpoints
- evaluator checkpoint decisions
- persistence of reports and outputs

## Design Requirements

- Update the relevant runtime modules to emit or record shared lifecycle events
- Ensure stage result generation uses the unified result contract
- Attach artifact references for persisted outputs where appropriate
- Review how `.dev` state files are updated and reduce avoidable status inference
- Keep the integration incremental and understandable

## Runtime Surfaces To Cover

At minimum, evaluate and integrate where appropriate in:

- `backend/dormammu/loop_runner.py`
- `backend/dormammu/daemon/pipeline_runner.py`
- `backend/dormammu/supervisor.py`
- `backend/dormammu/daemon/evaluator.py`
- state repository or run-tracking modules that store current/latest run data

## Integration Guidance

- Prefer emitting explicit events close to the actual lifecycle transition
- Avoid creating an event layer that is only populated after the fact from logs
- Keep event creation centralized enough that tests can assert sequence and payloads
- If `.dev` markdown projections remain operator-facing outputs, make them derived from explicit runtime state rather than ad hoc strings whenever practical

## Constraints

- Preserve current execution semantics unless a change is needed for correctness
- Do not break resumability or daemon run tracking
- Avoid rewriting the entire state system in one pass
- Keep the implementation compatible with future projection of dashboards and reports from machine-truth runtime data

## Acceptance Criteria

- Loop and pipeline execution paths both use the new event/result/artifact model
- Key runtime lifecycle transitions emit explicit, typed information
- `.dev` state updates are better aligned with actual runtime facts
- The implementation reduces duplicated result and artifact handling logic

## Validation

- Add integration coverage for loop and pipeline flows
- Verify that stage completion, failure, and checkpoint decisions produce expected events and results
- Verify that persisted artifacts are referenced from runtime outputs where applicable

## Deliverable

Produce the runtime integration changes and accompanying tests, with concise documentation explaining where lifecycle events are emitted and how downstream state derives from them.
