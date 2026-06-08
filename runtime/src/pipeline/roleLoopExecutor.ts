import type { StageResult } from "../results.js";
import {
  pipelineRoleLoopTransition,
  type PipelineRetryRole,
  type PipelineRoleLoopTransition
} from "./roleLoops.js";

export type PipelineRoleLoopExecutorContext = {
  attempt: number;
  iteration: number;
  maxIterations: number;
};

export type PipelineRoleLoopRetryContext = PipelineRoleLoopExecutorContext & {
  stage: StageResult;
  transition: Extract<PipelineRoleLoopTransition, { action: "retry_developer" }>;
};

export type PipelineRoleLoopExecutorInput = {
  role: PipelineRetryRole;
  maxIterations: number;
  runStage: (
    context: PipelineRoleLoopExecutorContext
  ) => StageResult | null | Promise<StageResult | null>;
  onRetry?: (context: PipelineRoleLoopRetryContext) => void | Promise<void>;
};

export type PipelineRoleLoopExecutorResult =
  | {
      action: "proceed";
      iterations: number;
      stage: StageResult | null;
      transition: PipelineRoleLoopTransition;
    }
  | {
      action: "fail";
      iterations: number;
      stage: StageResult;
      transition: PipelineRoleLoopTransition;
    }
  | {
      action: "manual_review_needed";
      iterations: number;
      stage: StageResult;
      sourceStage: StageResult;
      transition: PipelineRoleLoopTransition;
    };

export async function runPipelineRoleLoop(
  input: PipelineRoleLoopExecutorInput
): Promise<PipelineRoleLoopExecutorResult> {
  if (!Number.isInteger(input.maxIterations) || input.maxIterations <= 0) {
    throw new Error("maxIterations must be a positive integer");
  }

  for (let iteration = 0; iteration < input.maxIterations; iteration += 1) {
    const context = {
      attempt: iteration + 1,
      iteration,
      maxIterations: input.maxIterations
    };
    const stage = await input.runStage(context);
    const transition = pipelineRoleLoopTransition({
      role: input.role,
      stage,
      iteration,
      maxIterations: input.maxIterations
    });

    if (transition.action === "proceed") {
      return {
        action: "proceed",
        iterations: iteration + 1,
        stage,
        transition
      };
    }
    if (stage === null) {
      return {
        action: "proceed",
        iterations: iteration + 1,
        stage,
        transition: { action: "proceed" }
      };
    }
    if (transition.action === "fail") {
      return {
        action: "fail",
        iterations: iteration + 1,
        stage,
        transition
      };
    }
    if (transition.action === "manual_review_needed") {
      return {
        action: "manual_review_needed",
        iterations: iteration + 1,
        stage: transition.exhaustedStage ?? stage,
        sourceStage: stage,
        transition
      };
    }

    await input.onRetry?.({
      ...context,
      stage,
      transition
    });
  }

  throw new Error("Pipeline role loop exhausted without a terminal transition");
}
