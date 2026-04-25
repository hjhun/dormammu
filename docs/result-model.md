# Result Model

`backend/dormammu/results.py` is the canonical runtime result contract for Dormammu.

It defines two layers:

- `StageResult`: one terminal stage attempt
- `RunResult`: one aggregated loop or pipeline execution

## Stage Semantics

Each `StageResult` separates operational status from domain verdict:

- `status` answers whether the stage itself completed cleanly: `completed`, `failed`, `blocked`, `skipped`, or `manual_review_needed`
- `verdict` answers what the stage concluded in domain terms: `pass`, `fail`, `approved`, `needs_work`, `proceed`, `rework`, `goal_achieved`, and related normalized values

This distinction matters because a stage can complete operationally while still returning a non-success verdict. Examples:

- tester: `status=completed`, `verdict=fail`
- reviewer: `status=completed`, `verdict=needs_work`
- evaluator checkpoint: `status=completed`, `verdict=rework`

If a stage fails before a valid verdict exists, the result uses a non-completed `status` and `verdict=None` or `verdict=unknown`.
Malformed tester, reviewer, and final-evaluator output is treated this way instead of being silently upgraded to a success verdict.

## Attached Data

The shared model keeps stage payloads lightweight and serializable:

- `summary`: short human-readable explanation
- `output`: optional raw text output when callers need it
- `artifacts`: durable `ArtifactRef` records for reports, logs, prompts, or transcripts
- `retry`: attempt counters and retry budget metadata
- `timing`: start/end timestamps and optional duration

`report_path` is still available for compatibility, but `artifacts` is the canonical attachment surface.

## Artifact References

`backend/dormammu/artifacts.py` is the canonical artifact contract.

Each `ArtifactRef` includes:

- `kind`: logical artifact type such as `stage_report`, `supervisor_report`, or `metadata`
- `path`: filesystem path kept visible for operators and resume logic
- `created_at`: persistence timestamp when the writer created the artifact
- `run_id`: execution association when the artifact belongs to a specific run
- `role` and `stage_name`: stage association when the artifact belongs to a runtime stage
- `session_id`: session association when the writer has that context
- `label`, `content_type`, and optional additive `metadata`

`ArtifactWriter` preserves the current operator-visible `.dev` layout instead of
inventing a new storage tree. Existing paths such as `.dev/logs/<date>_<role>_<stem>.md`,
`.dev/supervisor_report.md`, and `.dev/continuation_prompt.txt` remain valid;
the difference is that runtime code now resolves and writes them through one
shared API.

## Run Aggregation

`RunResult` preserves the existing loop-facing fields used by the daemon and recovery paths:

- `status`
- `attempts_completed`
- `retries_used`
- `max_retries`
- `max_iterations`
- `latest_run_id`
- `supervisor_verdict`
- `report_path`
- `continuation_prompt_path`

It also adds:

- `stage_results`
- `artifacts`
- `retry`
- `timing`
- `summary`

Run-level aggregation uses the latest result per stage key instead of every historical attempt. That allows retries to behave sensibly: an earlier tester `fail` does not force the final run status once a later tester attempt returns `pass`.

When a pipeline or loop run is finalized, run-level `artifacts` are aggregated
from both explicit run attachments and the latest `StageResult.artifacts`. That
keeps persisted reports visible from the top-level runtime result without
duplicating artifact-writing logic in each runner.

The shared helpers now aggregate more than operational status:

- `aggregate_run_status()` reports whether the run completed, failed, blocked, or needs manual review
- `aggregate_run_verdict()` derives the operator-facing verdict from the latest stage results instead of preserving a stale developer-loop verdict
- `aggregate_run_summary()` prefers the latest failing-stage summary and synthesizes a short failure summary when a retry-exhausted stage has no explicit summary text
- `stage_results_have_clean_terminal_evidence()` and
  `run_result_has_clean_terminal_stage_evidence()` provide the shared clean
  terminal-stage check used by supervisor and daemon result publication

This means a pipeline can remain operationally `completed` while still surfacing a reviewer `needs_work` or tester `fail` verdict at the run level.

At the daemon boundary, `DaemonPromptResult` keeps prompt-queue metadata but carries the canonical `RunResult` as its execution payload. Result reports and hooks can therefore inspect `stage_results`, `summary`, `artifacts`, `retry`, and `timing` without reconstructing them from legacy flat fields.

## Consumer Guidance

The runtime should be consumed in this order:

- use `RunResult`, `StageResult`, and `ArtifactRef` as the canonical in-memory contracts
- use the `.dev` `execution` block as the latest persisted snapshot
- use `lifecycle.history` when exact chronology matters

Consumers should not derive status by scraping raw `output`, `DASHBOARD.md`,
or free-form report text when a structured field already exists. In
particular:

- `status` answers whether execution completed cleanly
- `verdict` answers what the stage concluded
- `artifacts` and event `artifact_refs` answer where durable evidence lives
- supervisor reports include `decision_basis`, which records whether the
  verdict came from current structured stage results or from legacy
  operator-state fallback evidence

That distinction is what prevents ad hoc status handling from re-entering loop,
pipeline, daemon, or dashboard code.

## Parsing And Normalization

Role-specific verdict parsing is centralized in `backend/dormammu/results.py`:

- `parse_tester_verdict()`
- `parse_reviewer_verdict()`
- `parse_plan_evaluator_verdict()`
- `parse_final_evaluator_verdict()`

Callers should use these helpers instead of open-coding regex-to-string parsing in loop, pipeline, or evaluator modules.

For stages that require an explicit terminal marker, the helpers fail closed:

- tester requires `OVERALL: PASS` or `OVERALL: FAIL`
- reviewer requires `VERDICT: APPROVED` or `VERDICT: NEEDS_WORK`
- final evaluator requires `VERDICT: goal_achieved | partial | not_achieved`

If those markers are missing or malformed, the parser does not invent a success verdict. The caller must surface a non-completed stage result.
