import assert from "node:assert/strict";
import test from "node:test";

import { stageResultToDict } from "../results.js";
import { buildPipelineRoleStageResult } from "./roleStages.js";

test("tester role stage maps overall verdicts to Python-compatible results", () => {
  const passed = buildPipelineRoleStageResult({
    kind: "tester",
    output: "unit tests passed\nOVERALL: PASS",
    reportPath: "/tmp/tester.md",
    artifacts: [{ kind: "stage_report", path: "/tmp/tester.md" }],
    attempt: 2
  });

  assert.deepEqual(stageResultToDict(passed, { includeOutput: true }), {
    role: "tester",
    stage_name: "tester",
    status: "completed",
    verdict: "pass",
    summary: null,
    report_path: "/tmp/tester.md",
    artifacts: [{ kind: "stage_report", path: "/tmp/tester.md" }],
    retry: {
      attempt: 2,
      next_attempt: null,
      retries_used: null,
      max_retries: null,
      max_iterations: null
    },
    timing: null,
    metadata: {},
    output: "unit tests passed\nOVERALL: PASS"
  });

  const missing = buildPipelineRoleStageResult({
    kind: "tester",
    output: "no verdict line"
  });
  assert.equal(missing.status, "failed");
  assert.equal(missing.verdict, null);
  assert.equal(missing.summary, "Tester output did not include a valid 'OVERALL:' verdict.");

  const manualReview = buildPipelineRoleStageResult({
    kind: "tester",
    output: "browser unavailable\nOVERALL: MANUAL_REVIEW_NEEDED"
  });
  assert.equal(manualReview.status, "manual_review_needed");
  assert.equal(manualReview.verdict, "manual_review_needed");
  assert.match(manualReview.summary ?? "", /requested manual review/);
});

test("reviewer and committer stages preserve role-specific verdict contracts", () => {
  const reviewer = buildPipelineRoleStageResult({
    kind: "reviewer",
    output: "Issues remain.\nVERDICT: NEEDS_WORK",
    attempt: 1
  });
  assert.equal(reviewer.role, "reviewer");
  assert.equal(reviewer.stageName, "reviewer");
  assert.equal(reviewer.status, "completed");
  assert.equal(reviewer.verdict, "needs_work");
  assert.equal(reviewer.retry?.attempt, 1);

  const malformedReviewer = buildPipelineRoleStageResult({
    kind: "reviewer",
    output: "Looks fine, but no machine verdict."
  });
  assert.equal(malformedReviewer.status, "failed");
  assert.equal(malformedReviewer.verdict, null);
  assert.equal(
    malformedReviewer.summary,
    "Reviewer output did not include a valid 'VERDICT:' line."
  );

  const committer = buildPipelineRoleStageResult({
    kind: "committer",
    output: "commit ok"
  });
  assert.equal(committer.role, "committer");
  assert.equal(committer.stageName, "committer");
  assert.equal(committer.status, "completed");
  assert.equal(committer.verdict, "committed");
  assert.equal(committer.retry, null);
});

test("evaluator stages map checkpoint and final verdict contracts", () => {
  const checkpoint = buildPipelineRoleStageResult({
    kind: "plan_evaluator",
    output: "DECISION: REWORK",
    attempt: 3
  });
  assert.equal(checkpoint.role, "evaluator");
  assert.equal(checkpoint.stageName, "plan_evaluator");
  assert.equal(checkpoint.status, "completed");
  assert.equal(checkpoint.verdict, "rework");
  assert.equal(checkpoint.retry?.attempt, 3);

  const final = buildPipelineRoleStageResult({
    kind: "final_evaluator",
    output: "The goal is done.\nVERDICT: goal_achieved",
    metadata: { goal_file_updated: true }
  });
  assert.equal(final.role, "evaluator");
  assert.equal(final.stageName, "final_evaluator");
  assert.equal(final.status, "completed");
  assert.equal(final.verdict, "goal_achieved");
  assert.equal(final.summary, "Post-commit goal evaluation completed.");
  assert.deepEqual(final.metadata, { goal_file_updated: true });

  const missingFinalVerdict = buildPipelineRoleStageResult({
    kind: "final_evaluator",
    output: "no final verdict"
  });
  assert.equal(missingFinalVerdict.status, "failed");
  assert.equal(missingFinalVerdict.verdict, "unknown");
  assert.equal(
    missingFinalVerdict.summary,
    "Evaluator output did not include a valid 'VERDICT:' line."
  );

  const failedCall = buildPipelineRoleStageResult({
    kind: "final_evaluator",
    output: null
  });
  assert.equal(failedCall.status, "failed");
  assert.equal(failedCall.verdict, "unknown");
  assert.equal(
    failedCall.summary,
    "Evaluator agent execution failed before a verdict was produced."
  );
  assert.deepEqual(failedCall.metadata, { goal_file_updated: false });
});
