import {
  stageResultIsFailure,
  stageResultRequestsRetry,
  type StageResult
} from "../results.js";

export type PipelineRetryRole = "tester" | "reviewer";

export type PipelineRoleLoopDecision =
  | { action: "proceed" }
  | { action: "fail" }
  | { action: "manual_review_needed"; exhausted?: boolean }
  | {
      action: "retry_developer";
      sourceStage: PipelineRetryRole;
      targetStage: "developer";
      attempt: number;
      nextAttempt: number;
      reason: string;
    };

export type PipelineRoleLoopDecisionInput = {
  role: PipelineRetryRole;
  stage: StageResult | null;
  iteration: number;
  maxIterations: number;
};

export type PipelineRoleLoopExhaustedStageInput = {
  role: PipelineRetryRole;
  stage: StageResult;
  maxIterations: number;
};

export function pipelineRoleLoopDecision(
  input: PipelineRoleLoopDecisionInput
): PipelineRoleLoopDecision {
  const stage = input.stage;
  if (stage === null) {
    return { action: "proceed" };
  }
  if (stage.status === "manual_review_needed" || stage.verdict === "manual_review_needed") {
    return { action: "manual_review_needed" };
  }
  if (stageResultIsFailure(stage) && !stageResultRequestsRetry(stage)) {
    return { action: "fail" };
  }
  if (!stageResultRequestsRetry(stage)) {
    return { action: "proceed" };
  }
  if (input.iteration < input.maxIterations - 1) {
    return {
      action: "retry_developer",
      sourceStage: input.role,
      targetStage: "developer",
      attempt: input.iteration + 1,
      nextAttempt: input.iteration + 2,
      reason: retryReason(input.role)
    };
  }
  return { action: "manual_review_needed", exhausted: true };
}

export function pipelineRoleLoopExhaustedStage(
  input: PipelineRoleLoopExhaustedStageInput
): StageResult {
  return {
    role: input.role,
    stageName: input.stage.stageName ?? input.stage.role,
    status: "manual_review_needed",
    verdict: "manual_review_needed",
    output: input.stage.output,
    summary: exhaustedSummary(input.role, input.maxIterations),
    reportPath: input.stage.reportPath ?? null,
    artifacts: input.stage.artifacts ?? [],
    retry: input.stage.retry ?? null,
    timing: input.stage.timing ?? null,
    metadata: input.stage.metadata ?? {}
  };
}

function retryReason(role: PipelineRetryRole): string {
  return role === "tester"
    ? "Tester requested another developer pass."
    : "Reviewer requested another developer pass.";
}

function exhaustedSummary(role: PipelineRetryRole, maxIterations: number): string {
  if (role === "tester") {
    return [
      `Tester requested another developer pass after ${maxIterations} attempts.`,
      "Manual review is required before the pipeline can continue safely."
    ].join(" ");
  }
  return [
    `Reviewer still reported NEEDS_WORK after ${maxIterations} attempts.`,
    "Manual review is required before the pipeline can continue safely."
  ].join(" ");
}
