import {
  parseFinalEvaluatorVerdict,
  parsePlanEvaluatorVerdict,
  parseReviewerVerdict,
  parseTesterVerdict,
  type ResultStatus,
  type ResultVerdict,
  type RetryMetadata,
  type StageResult,
  type TimingMetadata
} from "../results.js";

export type PipelineRoleStageKind =
  | "tester"
  | "reviewer"
  | "committer"
  | "plan_evaluator"
  | "final_evaluator";

export type PipelineRoleStageResultInput = {
  kind: PipelineRoleStageKind;
  output?: string | null;
  reportPath?: string | null;
  artifacts?: readonly unknown[];
  attempt?: number | null;
  timing?: TimingMetadata | null;
  metadata?: Readonly<Record<string, unknown>>;
};

function retryFromAttempt(attempt: number | null | undefined): RetryMetadata | null {
  if (attempt == null) {
    return null;
  }
  return { attempt };
}

function baseStage(input: {
  role: string;
  stageName: string;
  status: ResultStatus;
  verdict: ResultVerdict | null;
  output: string;
  summary?: string | null;
  reportPath?: string | null;
  artifacts?: readonly unknown[];
  retry?: RetryMetadata | null;
  timing?: TimingMetadata | null;
  metadata?: Readonly<Record<string, unknown>>;
}): StageResult {
  return {
    role: input.role,
    stageName: input.stageName,
    status: input.status,
    verdict: input.verdict,
    output: input.output,
    summary: input.summary ?? null,
    reportPath: input.reportPath ?? null,
    artifacts: [...(input.artifacts ?? [])],
    retry: input.retry ?? null,
    timing: input.timing ?? null,
    metadata: { ...(input.metadata ?? {}) }
  };
}

function testerStage(input: PipelineRoleStageResultInput): StageResult {
  const output = input.output ?? "";
  const verdict = parseTesterVerdict(output);
  let status: ResultStatus;
  let summary: string | null = null;

  if (verdict === "manual_review_needed") {
    status = "manual_review_needed";
    summary = "Tester could not complete executable validation and requested manual review.";
  } else if (verdict !== null) {
    status = "completed";
  } else {
    status = "failed";
    summary = "Tester output did not include a valid 'OVERALL:' verdict.";
  }

  return baseStage({
    role: "tester",
    stageName: "tester",
    status,
    verdict,
    output,
    summary,
    reportPath: input.reportPath,
    artifacts: input.artifacts,
    retry: retryFromAttempt(input.attempt),
    timing: input.timing,
    metadata: input.metadata
  });
}

function reviewerStage(input: PipelineRoleStageResultInput): StageResult {
  const output = input.output ?? "";
  const verdict = parseReviewerVerdict(output);

  return baseStage({
    role: "reviewer",
    stageName: "reviewer",
    status: verdict !== null ? "completed" : "failed",
    verdict,
    output,
    summary: verdict !== null ? null : "Reviewer output did not include a valid 'VERDICT:' line.",
    reportPath: input.reportPath,
    artifacts: input.artifacts,
    retry: retryFromAttempt(input.attempt),
    timing: input.timing,
    metadata: input.metadata
  });
}

function committerStage(input: PipelineRoleStageResultInput): StageResult {
  return baseStage({
    role: "committer",
    stageName: "committer",
    status: "completed",
    verdict: "committed",
    output: input.output ?? "",
    reportPath: input.reportPath,
    artifacts: input.artifacts,
    timing: input.timing,
    metadata: input.metadata
  });
}

function planEvaluatorStage(input: PipelineRoleStageResultInput): StageResult {
  const output = input.output ?? "";
  return baseStage({
    role: "evaluator",
    stageName: "plan_evaluator",
    status: "completed",
    verdict: parsePlanEvaluatorVerdict(output),
    output,
    reportPath: input.reportPath,
    artifacts: input.artifacts,
    retry: retryFromAttempt(input.attempt),
    timing: input.timing,
    metadata: input.metadata
  });
}

function finalEvaluatorStage(input: PipelineRoleStageResultInput): StageResult {
  if (input.output == null) {
    return baseStage({
      role: "evaluator",
      stageName: "final_evaluator",
      status: "failed",
      verdict: "unknown",
      output: "",
      summary: "Evaluator agent execution failed before a verdict was produced.",
      metadata: { goal_file_updated: false, ...(input.metadata ?? {}) },
      timing: input.timing
    });
  }

  const verdict = parseFinalEvaluatorVerdict(input.output);
  const hasValidVerdict = verdict !== "unknown";
  return baseStage({
    role: "evaluator",
    stageName: "final_evaluator",
    status: hasValidVerdict ? "completed" : "failed",
    verdict,
    output: input.output,
    summary: hasValidVerdict
      ? "Post-commit goal evaluation completed."
      : "Evaluator output did not include a valid 'VERDICT:' line.",
    reportPath: input.reportPath,
    artifacts: input.artifacts,
    timing: input.timing,
    metadata: input.metadata
  });
}

export function buildPipelineRoleStageResult(input: PipelineRoleStageResultInput): StageResult {
  switch (input.kind) {
    case "tester":
      return testerStage(input);
    case "reviewer":
      return reviewerStage(input);
    case "committer":
      return committerStage(input);
    case "plan_evaluator":
      return planEvaluatorStage(input);
    case "final_evaluator":
      return finalEvaluatorStage(input);
  }
}
