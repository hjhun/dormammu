import assert from "node:assert/strict";
import test from "node:test";

import type { StageResult } from "../results.js";
import { runPipelineRoleLoop } from "./roleLoopExecutor.js";

test("runPipelineRoleLoop retries until a role stage proceeds", async () => {
  const stages: Array<StageResult | null> = [
    { role: "tester", stageName: "tester", verdict: "fail", output: "OVERALL: FAIL" },
    { role: "tester", stageName: "tester", verdict: "pass", output: "OVERALL: PASS" }
  ];
  const attempts: number[] = [];
  const retryAttempts: number[] = [];

  const result = await runPipelineRoleLoop({
    role: "tester",
    maxIterations: 3,
    runStage: ({ attempt }) => {
      attempts.push(attempt);
      return stages.shift() ?? null;
    },
    onRetry: ({ transition }) => {
      retryAttempts.push(transition.nextAttempt);
    }
  });

  assert.equal(result.action, "proceed");
  assert.equal(result.iterations, 2);
  assert.deepEqual(attempts, [1, 2]);
  assert.deepEqual(retryAttempts, [2]);
  assert.equal(result.stage?.verdict, "pass");
});

test("runPipelineRoleLoop treats a missing role stage as proceed", async () => {
  const result = await runPipelineRoleLoop({
    role: "reviewer",
    maxIterations: 3,
    runStage: () => null
  });

  assert.deepEqual(result, {
    action: "proceed",
    iterations: 1,
    stage: null,
    transition: { action: "proceed" }
  });
});

test("runPipelineRoleLoop returns fail for non-retryable stage failures", async () => {
  const stage = {
    role: "tester",
    stageName: "tester",
    status: "failed",
    verdict: null,
    output: "missing verdict"
  } satisfies StageResult;

  const result = await runPipelineRoleLoop({
    role: "tester",
    maxIterations: 3,
    runStage: () => stage
  });

  assert.equal(result.action, "fail");
  assert.equal(result.stage, stage);
  assert.deepEqual(result.transition, { action: "fail" });
});

test("runPipelineRoleLoop returns exhausted manual-review stage", async () => {
  const stage = {
    role: "reviewer",
    stageName: "reviewer",
    verdict: "needs_work",
    output: "VERDICT: NEEDS_WORK"
  } satisfies StageResult;
  const retries: number[] = [];

  const result = await runPipelineRoleLoop({
    role: "reviewer",
    maxIterations: 2,
    runStage: () => stage,
    onRetry: ({ attempt }) => {
      retries.push(attempt);
    }
  });

  assert.equal(result.action, "manual_review_needed");
  assert.deepEqual(retries, [1]);
  assert.equal(result.sourceStage, stage);
  assert.equal(result.stage.status, "manual_review_needed");
  assert.equal(result.stage.verdict, "manual_review_needed");
  assert.equal(
    result.stage.summary,
    "Reviewer still reported NEEDS_WORK after 2 attempts. Manual review is required before the pipeline can continue safely."
  );
  assert.equal(result.transition.action, "manual_review_needed");
});

test("runPipelineRoleLoop validates maxIterations", async () => {
  await assert.rejects(
    runPipelineRoleLoop({
      role: "tester",
      maxIterations: 0,
      runStage: () => null
    }),
    /maxIterations must be a positive integer/
  );
});
