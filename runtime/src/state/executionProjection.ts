import {
  latestStageResults,
  runResultToDict,
  stageResultKey,
  stageResultToDict,
  type RunResult,
  type StageResult
} from "../results.js";

export type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function firstTruthyString(...values: readonly unknown[]): string | null {
  for (const value of values) {
    if (value) {
      return String(value);
    }
  }
  return null;
}

export function mutableExecutionBlock(state: Readonly<JsonRecord>): JsonRecord {
  const block = state.execution;
  const execution: JsonRecord = isRecord(block) ? { ...block } : {};
  const stageResults = execution.stage_results;
  if (isRecord(stageResults)) {
    const normalized: JsonRecord = {};
    for (const [key, value] of Object.entries(stageResults)) {
      if (isRecord(value)) {
        normalized[key] = { ...value };
      }
    }
    execution.stage_results = normalized;
  } else {
    execution.stage_results = {};
  }
  return execution;
}

export function projectStageResult(
  state: JsonRecord,
  options: { stage: StageResult; runId?: string | null; timestamp: string }
): void {
  const stagePayload = stageResultToDict(options.stage, { includeOutput: false });
  stagePayload.recorded_at = options.timestamp;
  const metadata = options.stage.metadata ?? {};
  const effectiveRunId = firstTruthyString(
    options.runId,
    metadata.run_id,
    metadata.pipeline_run_id,
    metadata.latest_run_id
  );

  state.updated_at = options.timestamp;
  const execution = mutableExecutionBlock(state);
  if (effectiveRunId !== null) {
    execution.latest_run_id = effectiveRunId;
    execution.latest_execution_id = effectiveRunId;
  }
  const stageResults = execution.stage_results;
  if (isRecord(stageResults)) {
    stageResults[stageResultKey(options.stage)] = stagePayload;
  }
  execution.latest_stage_result = stagePayload;
  state.execution = execution;
}

export function projectRunResult(
  state: JsonRecord,
  options: { result: RunResult; runId?: string | null; timestamp: string }
): void {
  const effectiveRunId = firstTruthyString(
    options.runId,
    options.result.latestRunId,
    options.result.latest_run_id
  );
  const stageResults = options.result.stageResults ?? options.result.stage_results ?? [];
  const latestByStage: JsonRecord = {};
  for (const stage of latestStageResults(stageResults)) {
    latestByStage[stageResultKey(stage)] = stageResultToDict(stage, { includeOutput: false });
  }

  const latestRun = runResultToDict(options.result, { includeOutput: false });
  latestRun.run_id = effectiveRunId;
  latestRun.execution_run_id = effectiveRunId;
  latestRun.recorded_at = options.timestamp;

  state.updated_at = options.timestamp;
  const execution = mutableExecutionBlock(state);
  execution.latest_run_id = effectiveRunId;
  execution.latest_execution_id = effectiveRunId;
  execution.current_run = null;
  execution.latest_run = latestRun;
  execution.stage_results = latestByStage;
  const latestStagePayloads = Object.values(latestByStage);
  execution.latest_stage_result = latestStagePayloads.length
    ? latestStagePayloads[latestStagePayloads.length - 1]
    : null;
  state.execution = execution;
}

export function projectAgentRunFact(
  state: JsonRecord,
  options: { status: string; runPayload: Readonly<JsonRecord>; timestamp: string }
): void {
  const execution = mutableExecutionBlock(state);
  const runtimeRun = {
    run_id: options.runPayload.run_id,
    status: options.status,
    prompt_mode: options.runPayload.prompt_mode,
    workdir: options.runPayload.workdir,
    command: options.runPayload.command,
    exit_code: options.runPayload.exit_code,
    started_at: options.runPayload.started_at,
    completed_at: options.runPayload.completed_at,
    artifacts: options.runPayload.artifact_refs ?? [],
    updated_at: options.timestamp
  };
  execution.latest_run_id = options.runPayload.run_id;
  if (options.status === "started") {
    execution.current_run = runtimeRun;
  } else {
    execution.current_run = null;
    execution.latest_agent_run = runtimeRun;
  }
  state.execution = execution;
}

export function projectLifecycleExecutionFact(
  state: JsonRecord,
  options: { eventPayload: Readonly<JsonRecord>; timestamp: string }
): void {
  const execution = mutableExecutionBlock(state);
  const eventType = String(options.eventPayload.event_type ?? "");
  const payload = isRecord(options.eventPayload.payload) ? options.eventPayload.payload : {};
  const runId = options.eventPayload.run_id;
  if (runId != null) {
    execution.latest_run_id = runId;
    execution.latest_execution_id = runId;
  }

  if (eventType === "run.requested") {
    execution.current_run = {
      run_id: runId,
      status: options.eventPayload.status,
      source: payload.source,
      entrypoint: payload.entrypoint,
      trigger: payload.trigger,
      prompt_summary: payload.prompt_summary,
      requested_at: options.timestamp
    };
  } else if (eventType === "run.started") {
    const currentRun = isRecord(execution.current_run) ? execution.current_run : {};
    execution.current_run = {
      ...currentRun,
      run_id: runId,
      status: options.eventPayload.status,
      source: payload.source,
      entrypoint: payload.entrypoint,
      trigger: payload.trigger,
      started_at: options.timestamp
    };
  } else if (eventType === "run.finished") {
    const currentRun = isRecord(execution.current_run) ? execution.current_run : {};
    execution.current_run = null;
    execution.latest_run = {
      ...currentRun,
      run_id: runId,
      status: options.eventPayload.status,
      source: payload.source,
      entrypoint: payload.entrypoint,
      attempts_completed: payload.attempts_completed,
      retries_used: payload.retries_used,
      supervisor_verdict: payload.supervisor_verdict,
      outcome: payload.outcome,
      error: payload.error,
      artifacts: options.eventPayload.artifact_refs ?? [],
      completed_at: options.timestamp
    };
  } else if (eventType === "stage.completed" || eventType === "stage.failed") {
    const metadata = isRecord(options.eventPayload.metadata) ? options.eventPayload.metadata : {};
    const metadataStageResult = metadata.stage_result;
    const stageResult = isRecord(metadataStageResult)
      ? { ...metadataStageResult }
      : {
          role: options.eventPayload.role,
          stage_name: options.eventPayload.stage ?? options.eventPayload.role,
          status: options.eventPayload.status,
          verdict: payload.verdict,
          summary: payload.reason,
          artifacts: options.eventPayload.artifact_refs ?? []
        };
    const stageResults = isRecord(execution.stage_results) ? execution.stage_results : {};
    const stageName = String(stageResult.stage_name ?? stageResult.role ?? "stage");
    stageResults[stageName] = { ...stageResult };
    execution.stage_results = stageResults;
    execution.latest_stage_result = { ...stageResult };
  } else if (eventType === "evaluator.checkpoint_decision") {
    execution.latest_checkpoint = {
      run_id: runId,
      stage: options.eventPayload.stage,
      status: options.eventPayload.status,
      checkpoint_kind: payload.checkpoint_kind,
      decision: payload.decision,
      rationale: payload.rationale,
      artifacts: options.eventPayload.artifact_refs ?? [],
      updated_at: options.timestamp
    };
  } else if (eventType === "artifact.persisted") {
    execution.latest_artifact = {
      run_id: runId,
      stage: options.eventPayload.stage,
      role: options.eventPayload.role,
      artifact_kind: payload.artifact_kind,
      operation: payload.operation,
      summary: payload.summary,
      artifacts: options.eventPayload.artifact_refs ?? [],
      updated_at: options.timestamp
    };
  }

  state.execution = execution;
}
