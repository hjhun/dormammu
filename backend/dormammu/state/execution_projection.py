from __future__ import annotations

from typing import Any, Mapping

from dormammu.results import RunResult, StageResult, latest_stage_results


def mutable_execution_block(state: Mapping[str, Any]) -> dict[str, Any]:
    block = state.get("execution")
    execution: dict[str, Any] = dict(block) if isinstance(block, Mapping) else {}
    stage_results = execution.get("stage_results")
    if isinstance(stage_results, Mapping):
        execution["stage_results"] = {
            str(key): dict(value)
            for key, value in stage_results.items()
            if isinstance(key, str) and isinstance(value, Mapping)
        }
    else:
        execution["stage_results"] = {}
    return execution


def project_stage_result(
    state: dict[str, Any],
    *,
    stage: StageResult,
    run_id: str | None,
    timestamp: str,
) -> None:
    stage_payload = stage.to_dict(include_output=False)
    stage_payload["recorded_at"] = timestamp
    effective_run_id = (
        run_id
        or stage.metadata.get("run_id")
        or stage.metadata.get("pipeline_run_id")
        or stage.metadata.get("latest_run_id")
    )
    state["updated_at"] = timestamp
    execution = mutable_execution_block(state)
    if effective_run_id is not None:
        execution["latest_run_id"] = effective_run_id
        execution["latest_execution_id"] = effective_run_id
    stage_results = execution.setdefault("stage_results", {})
    stage_results[stage.key] = stage_payload
    execution["latest_stage_result"] = stage_payload
    state["execution"] = execution


def project_run_result(
    state: dict[str, Any],
    *,
    result: RunResult,
    run_id: str | None,
    timestamp: str,
) -> None:
    effective_run_id = run_id or result.latest_run_id
    latest_by_stage = {
        stage.key: stage.to_dict(include_output=False)
        for stage in latest_stage_results(result.stage_results)
    }
    latest_run = result.to_dict(include_output=False)
    latest_run["run_id"] = effective_run_id
    latest_run["execution_run_id"] = effective_run_id
    latest_run["recorded_at"] = timestamp

    state["updated_at"] = timestamp
    execution = mutable_execution_block(state)
    execution["latest_run_id"] = effective_run_id
    execution["latest_execution_id"] = effective_run_id
    execution["current_run"] = None
    execution["latest_run"] = latest_run
    execution["stage_results"] = latest_by_stage
    execution["latest_stage_result"] = (
        latest_by_stage[next(reversed(latest_by_stage))]
        if latest_by_stage
        else None
    )
    state["execution"] = execution


def project_agent_run_fact(
    state: dict[str, Any],
    *,
    status: str,
    run_payload: Mapping[str, Any],
    timestamp: str,
) -> None:
    execution = mutable_execution_block(state)
    runtime_run = {
        "run_id": run_payload.get("run_id"),
        "status": status,
        "prompt_mode": run_payload.get("prompt_mode"),
        "workdir": run_payload.get("workdir"),
        "command": run_payload.get("command"),
        "exit_code": run_payload.get("exit_code"),
        "started_at": run_payload.get("started_at"),
        "completed_at": run_payload.get("completed_at"),
        "artifacts": run_payload.get("artifact_refs", []),
        "updated_at": timestamp,
    }
    execution["latest_run_id"] = run_payload.get("run_id")
    if status == "started":
        execution["current_run"] = runtime_run
    else:
        execution["current_run"] = None
        execution["latest_agent_run"] = runtime_run
    state["execution"] = execution


def project_lifecycle_execution_fact(
    state: dict[str, Any],
    *,
    event_payload: Mapping[str, Any],
    timestamp: str,
) -> None:
    execution = mutable_execution_block(state)
    event_type = str(event_payload.get("event_type") or "")
    payload = event_payload.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}
    run_id = event_payload.get("run_id")
    if run_id is not None:
        execution["latest_run_id"] = run_id
        execution["latest_execution_id"] = run_id

    if event_type == "run.requested":
        execution["current_run"] = {
            "run_id": run_id,
            "status": event_payload.get("status"),
            "source": payload.get("source"),
            "entrypoint": payload.get("entrypoint"),
            "trigger": payload.get("trigger"),
            "prompt_summary": payload.get("prompt_summary"),
            "requested_at": timestamp,
        }
    elif event_type == "run.started":
        current_run = execution.get("current_run")
        next_current = dict(current_run) if isinstance(current_run, Mapping) else {}
        next_current.update(
            {
                "run_id": run_id,
                "status": event_payload.get("status"),
                "source": payload.get("source"),
                "entrypoint": payload.get("entrypoint"),
                "trigger": payload.get("trigger"),
                "started_at": timestamp,
            }
        )
        execution["current_run"] = next_current
    elif event_type == "run.finished":
        current_run = execution.get("current_run")
        latest_run = dict(current_run) if isinstance(current_run, Mapping) else {}
        latest_run.update(
            {
                "run_id": run_id,
                "status": event_payload.get("status"),
                "source": payload.get("source"),
                "entrypoint": payload.get("entrypoint"),
                "attempts_completed": payload.get("attempts_completed"),
                "retries_used": payload.get("retries_used"),
                "supervisor_verdict": payload.get("supervisor_verdict"),
                "outcome": payload.get("outcome"),
                "error": payload.get("error"),
                "artifacts": event_payload.get("artifact_refs", []),
                "completed_at": timestamp,
            }
        )
        execution["current_run"] = None
        execution["latest_run"] = latest_run
    elif event_type in {"stage.completed", "stage.failed"}:
        metadata = event_payload.get("metadata")
        stage_result = metadata.get("stage_result") if isinstance(metadata, Mapping) else None
        if not isinstance(stage_result, Mapping):
            stage_result = {
                "role": event_payload.get("role"),
                "stage_name": event_payload.get("stage") or event_payload.get("role"),
                "status": event_payload.get("status"),
                "verdict": payload.get("verdict"),
                "summary": payload.get("reason"),
                "artifacts": event_payload.get("artifact_refs", []),
            }
        stage_results = execution.setdefault("stage_results", {})
        stage_name = str(stage_result.get("stage_name") or stage_result.get("role") or "stage")
        stage_results[stage_name] = dict(stage_result)
        execution["latest_stage_result"] = dict(stage_result)
    elif event_type == "evaluator.checkpoint_decision":
        execution["latest_checkpoint"] = {
            "run_id": run_id,
            "stage": event_payload.get("stage"),
            "status": event_payload.get("status"),
            "checkpoint_kind": payload.get("checkpoint_kind"),
            "decision": payload.get("decision"),
            "rationale": payload.get("rationale"),
            "artifacts": event_payload.get("artifact_refs", []),
            "updated_at": timestamp,
        }
    elif event_type == "artifact.persisted":
        execution["latest_artifact"] = {
            "run_id": run_id,
            "stage": event_payload.get("stage"),
            "role": event_payload.get("role"),
            "artifact_kind": payload.get("artifact_kind"),
            "operation": payload.get("operation"),
            "summary": payload.get("summary"),
            "artifacts": event_payload.get("artifact_refs", []),
            "updated_at": timestamp,
        }

    state["execution"] = execution
