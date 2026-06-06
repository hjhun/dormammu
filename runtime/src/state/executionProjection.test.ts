import assert from "node:assert/strict";
import test from "node:test";

import {
  mutableExecutionBlock,
  projectLifecycleExecutionFact,
  projectRunResult,
  projectStageResult
} from "./executionProjection.js";

test("mutableExecutionBlock normalizes stage_results mappings", () => {
  const state = {
    execution: {
      stage_results: {
        tester: { role: "tester", verdict: "pass" },
        bad: "not-a-mapping"
      }
    }
  };

  assert.deepEqual(mutableExecutionBlock(state).stage_results, {
    tester: { role: "tester", verdict: "pass" }
  });
});

test("projectStageResult updates latest stage without touching other blocks", () => {
  const state: Record<string, unknown> = { bootstrap: { goal: "keep" } };

  projectStageResult(state, {
    stage: { role: "tester", stageName: "tester", verdict: "pass" },
    runId: "run-1",
    timestamp: "2026-04-25T00:00:00+00:00"
  });

  assert.deepEqual(state.bootstrap, { goal: "keep" });
  assert.equal(state.updated_at, "2026-04-25T00:00:00+00:00");
  const execution = state.execution as Record<string, unknown>;
  const latestStage = execution.latest_stage_result as Record<string, unknown>;
  const stageResults = execution.stage_results as Record<string, Record<string, unknown>>;
  assert.equal(execution.latest_run_id, "run-1");
  assert.equal(latestStage.stage_name, "tester");
  assert.equal(stageResults.tester.verdict, "pass");
});

test("projectRunResult keeps only the latest stage result per key", () => {
  const state: Record<string, unknown> = {};

  projectRunResult(state, {
    result: {
      status: "completed",
      attemptsCompleted: 2,
      retriesUsed: 1,
      maxRetries: 3,
      maxIterations: 4,
      latestRunId: "agent-run-1",
      supervisorVerdict: "approved",
      reportPath: null,
      continuationPromptPath: null,
      stageResults: [
        { role: "tester", stageName: "tester", verdict: "fail" },
        { role: "tester", stageName: "tester", verdict: "pass" }
      ]
    },
    runId: "pipeline-run-1",
    timestamp: "2026-04-25T00:00:00+00:00"
  });

  const execution = state.execution as Record<string, unknown>;
  const latestRun = execution.latest_run as Record<string, unknown>;
  const stageResults = execution.stage_results as Record<string, Record<string, unknown>>;
  assert.equal(execution.current_run, null);
  assert.equal(latestRun.run_id, "pipeline-run-1");
  assert.equal(latestRun.latest_run_id, "agent-run-1");
  assert.equal(stageResults.tester.verdict, "pass");
});

test("projectLifecycleExecutionFact projects stage events", () => {
  const state: Record<string, unknown> = {};

  projectLifecycleExecutionFact(state, {
    eventPayload: {
      event_type: "stage.failed",
      run_id: "run-1",
      role: "reviewer",
      stage: "reviewer",
      status: "completed",
      payload: { verdict: "needs_work", reason: "review failed" },
      artifact_refs: [{ kind: "stage_report", path: "/tmp/review.md" }]
    },
    timestamp: "2026-04-25T00:00:00+00:00"
  });

  const execution = state.execution as Record<string, unknown>;
  const latestStage = execution.latest_stage_result as Record<string, unknown>;
  assert.equal(execution.latest_run_id, "run-1");
  assert.equal(latestStage.stage_name, "reviewer");
  assert.equal(latestStage.verdict, "needs_work");
});
