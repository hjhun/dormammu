import assert from "node:assert/strict";
import test from "node:test";

import { stageResultToDict } from "../results.js";
import {
  pipelineRoleLoopDecision,
  pipelineRoleLoopExhaustedStage
} from "./roleLoops.js";

test("tester loop decisions match Python retry semantics", () => {
  assert.deepEqual(
    pipelineRoleLoopDecision({
      role: "tester",
      stage: { role: "tester", stageName: "tester", status: "completed", verdict: "pass" },
      iteration: 0,
      maxIterations: 3
    }),
    { action: "proceed" }
  );

  assert.deepEqual(
    pipelineRoleLoopDecision({
      role: "tester",
      stage: { role: "tester", stageName: "tester", status: "completed", verdict: "fail" },
      iteration: 0,
      maxIterations: 3
    }),
    {
      action: "retry_developer",
      sourceStage: "tester",
      targetStage: "developer",
      attempt: 1,
      nextAttempt: 2,
      reason: "Tester requested another developer pass."
    }
  );

  assert.deepEqual(
    pipelineRoleLoopDecision({
      role: "tester",
      stage: {
        role: "tester",
        stageName: "tester",
        status: "manual_review_needed",
        verdict: "manual_review_needed"
      },
      iteration: 0,
      maxIterations: 3
    }),
    { action: "manual_review_needed" }
  );

  assert.deepEqual(
    pipelineRoleLoopDecision({
      role: "tester",
      stage: { role: "tester", stageName: "tester", status: "failed", verdict: null },
      iteration: 0,
      maxIterations: 3
    }),
    { action: "fail" }
  );
});

test("reviewer loop decisions use reviewer-specific handoff metadata", () => {
  assert.deepEqual(
    pipelineRoleLoopDecision({
      role: "reviewer",
      stage: {
        role: "reviewer",
        stageName: "reviewer",
        status: "completed",
        verdict: "approved"
      },
      iteration: 0,
      maxIterations: 3
    }),
    { action: "proceed" }
  );

  assert.deepEqual(
    pipelineRoleLoopDecision({
      role: "reviewer",
      stage: {
        role: "reviewer",
        stageName: "reviewer",
        status: "completed",
        verdict: "needs_work"
      },
      iteration: 1,
      maxIterations: 3
    }),
    {
      action: "retry_developer",
      sourceStage: "reviewer",
      targetStage: "developer",
      attempt: 2,
      nextAttempt: 3,
      reason: "Reviewer requested another developer pass."
    }
  );
});

test("retry exhaustion produces manual-review stage payloads", () => {
  const testerStage = { role: "tester", stageName: "tester", verdict: "fail", output: "OVERALL: FAIL" };
  assert.deepEqual(
    pipelineRoleLoopDecision({
      role: "tester",
      stage: testerStage,
      iteration: 2,
      maxIterations: 3
    }),
    { action: "manual_review_needed", exhausted: true }
  );
  assert.deepEqual(
    stageResultToDict(
      pipelineRoleLoopExhaustedStage({
        role: "tester",
        stage: testerStage,
        maxIterations: 3
      }),
      { includeOutput: true }
    ),
    {
      role: "tester",
      stage_name: "tester",
      status: "manual_review_needed",
      verdict: "manual_review_needed",
      summary:
        "Tester requested another developer pass after 3 attempts. Manual review is required before the pipeline can continue safely.",
      report_path: null,
      artifacts: [],
      retry: null,
      timing: null,
      metadata: {},
      output: "OVERALL: FAIL"
    }
  );

  const reviewerStage = {
    role: "reviewer",
    stageName: "reviewer",
    verdict: "needs_work",
    output: "VERDICT: NEEDS_WORK"
  };
  assert.equal(
    pipelineRoleLoopExhaustedStage({
      role: "reviewer",
      stage: reviewerStage,
      maxIterations: 2
    }).summary,
    "Reviewer still reported NEEDS_WORK after 2 attempts. Manual review is required before the pipeline can continue safely."
  );
});
