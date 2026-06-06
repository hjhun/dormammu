import assert from "node:assert/strict";
import test from "node:test";

import {
  defaultWorkflowPolicyState,
  MINIMAL_WORKFLOWS,
  resolveWorkflowPolicy
} from "./workflowPolicy.js";

test("resolveWorkflowPolicy returns required phases for full workflow", () => {
  const policy = resolveWorkflowPolicy("full_workflow");
  assert.deepEqual(policy.requiredPhases, MINIMAL_WORKFLOWS.full_workflow);
  assert.deepEqual(policy.skippedPhases, ["evaluate"]);
  assert.equal(policy.isPhaseRequired("develop"), true);
  assert.equal(policy.isPhaseSkipped("evaluate"), true);
});

test("resolveWorkflowPolicy keeps direct responses phase-free", () => {
  const policy = resolveWorkflowPolicy("direct_response");
  assert.deepEqual(policy.requiredPhases, []);
  assert.equal(policy.skippedPhases.length, 10);
  assert.match(policy.dashboardSummary(), /Required phases \(0\): none/);
});

test("defaultWorkflowPolicyState serializes Python-compatible keys", () => {
  assert.deepEqual(defaultWorkflowPolicyState("planning_only"), {
    request_class: "planning_only",
    required_phases: ["refine", "plan"],
    skipped_phases: [
      "evaluator_check",
      "design",
      "develop",
      "test_author",
      "test_and_review",
      "final_verify",
      "commit",
      "evaluate"
    ],
    skip_rationale: resolveWorkflowPolicy("planning_only").skipRationale
  });
});
