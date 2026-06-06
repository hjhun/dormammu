import assert from "node:assert/strict";
import test from "node:test";

import {
  aggregateRunStatus,
  aggregateRunVerdict,
  latestStageResults,
  parseFinalEvaluatorVerdict,
  parsePlanEvaluatorVerdict,
  parseReviewerVerdict,
  parseTesterVerdict,
  stageResultIsFailure,
  stageResultRequestsRetry,
  stageResultsHaveCleanTerminalEvidence
} from "./results.js";

test("verdict parsers use the final matching verdict", () => {
  assert.equal(parseTesterVerdict("OVERALL: FAIL\nOVERALL: PASS"), "pass");
  assert.equal(parseTesterVerdict("OVERALL: MANUAL REVIEW NEEDED"), "manual_review_needed");
  assert.equal(parseReviewerVerdict("VERDICT: NEEDS_WORK"), "needs_work");
  assert.equal(parseReviewerVerdict("VERDICT: APPROVED"), "approved");
  assert.equal(parsePlanEvaluatorVerdict("DECISION: PROCEED"), "proceed");
  assert.equal(parsePlanEvaluatorVerdict("DECISION: REWORK"), "rework");
  assert.equal(parseFinalEvaluatorVerdict("VERDICT: partial"), "partial");
  assert.equal(parseFinalEvaluatorVerdict("no verdict"), "unknown");
});

test("latestStageResults keeps the newest result per stage key", () => {
  assert.deepEqual(
    latestStageResults([
      { role: "developer", verdict: "fail" },
      { role: "reviewer", verdict: "approved" },
      { role: "developer", verdict: "pass" }
    ]),
    [
      { role: "reviewer", verdict: "approved" },
      { role: "developer", verdict: "pass" }
    ]
  );
});

test("stage failure and retry helpers match Python semantics", () => {
  assert.equal(stageResultIsFailure({ role: "tester", verdict: "needs_work" }), true);
  assert.equal(stageResultRequestsRetry({ role: "tester", verdict: "needs_work" }), true);
  assert.equal(stageResultIsFailure({ role: "tester", status: "blocked" }), true);
  assert.equal(stageResultRequestsRetry({ role: "tester", status: "blocked" }), false);
});

test("aggregate helpers compute terminal status and verdict from latest stages", () => {
  const stages = [
    { role: "developer", verdict: "fail" },
    { role: "developer", verdict: "pass" },
    { role: "reviewer", verdict: "approved" }
  ];
  assert.equal(stageResultsHaveCleanTerminalEvidence(stages), true);
  assert.equal(aggregateRunStatus(stages), "completed");
  assert.equal(aggregateRunVerdict(stages), "approved");

  const failed = [...stages, { role: "reviewer", verdict: "needs_work" }];
  assert.equal(stageResultsHaveCleanTerminalEvidence(failed), false);
  assert.equal(aggregateRunVerdict(failed), "needs_work");
});
