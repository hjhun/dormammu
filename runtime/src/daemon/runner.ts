import type { RequestClass } from "../workflowPolicy.js";

export type DaemonPendingDecisionAction = "idle" | "wait" | "process";

export type DaemonPendingDecisionInput = {
  processedCount: number;
  readyPromptPaths: readonly string[];
  retryAfterSeconds: number | null;
};

export type DaemonPendingDecision = {
  action: DaemonPendingDecisionAction;
  promptPath: string | null;
  queuedPromptNames: string[];
  retryAfterSeconds: number | null;
  reason: string;
};

export type DaemonPromptRouteAction =
  | "configured_pipeline"
  | "direct_pipeline"
  | "planning_pipeline"
  | "prelude_then_loop";

export type DaemonPromptRouteInput = {
  hasAgentsConfig: boolean;
  requestClass: RequestClass;
  hasGoalFile: boolean;
};

export type DaemonPromptRouteDecision = {
  action: DaemonPromptRouteAction;
  runner: "pipeline" | "loop";
  requiresAgentCli: boolean;
  runRefineAndPlanPrelude: boolean;
  enablePlanEvaluator: boolean;
  useGoalsEvaluatorConfig: boolean;
  reason: string;
};

export type DaemonLoopIterationAction = "continue" | "wait" | "stop";

export type DaemonLoopIterationInput = {
  processedCount: number;
  inProgressCount: number;
  shutdownRequested: boolean;
};

export type DaemonLoopIterationDecision = {
  action: DaemonLoopIterationAction;
  heartbeatStatus: "busy" | "idle";
  waitForChanges: boolean;
  reason: string;
};

export type DaemonStartupDecisionInput = {
  goalsSchedulerConfigured: boolean;
  autonomousSchedulerConfigured: boolean;
};

export type DaemonStartupDecision = {
  action: "start";
  initialHeartbeatStatus: "idle";
  startGoalsScheduler: boolean;
  triggerGoalsScheduler: boolean;
  startAutonomousScheduler: boolean;
  triggerAutonomousScheduler: boolean;
  reason: string;
};

export type DaemonShutdownDecisionInput = {
  goalsSchedulerConfigured: boolean;
  autonomousSchedulerConfigured: boolean;
  progressLogActive: boolean;
};

export type DaemonShutdownDecision = {
  action: "shutdown";
  stopGoalsScheduler: boolean;
  stopAutonomousScheduler: boolean;
  closeWatcher: boolean;
  removeHeartbeat: boolean;
  closeProgressLog: boolean;
  reason: string;
};

export function daemonPendingDecision(
  input: DaemonPendingDecisionInput
): DaemonPendingDecision {
  const readyPromptPaths = input.readyPromptPaths.filter(
    (path) => path.length > 0
  );
  const processedCount = Math.max(0, Math.trunc(input.processedCount));
  if (readyPromptPaths.length === 0) {
    if (processedCount === 0 && input.retryAfterSeconds !== null) {
      return {
        action: "wait",
        promptPath: null,
        queuedPromptNames: [],
        retryAfterSeconds: Math.max(0, input.retryAfterSeconds),
        reason: "settle_window_pending"
      };
    }
    return {
      action: "idle",
      promptPath: null,
      queuedPromptNames: [],
      retryAfterSeconds: null,
      reason: "no_ready_prompts"
    };
  }
  return {
    action: "process",
    promptPath: readyPromptPaths[0],
    queuedPromptNames: readyPromptPaths.slice(1).map((path) => basename(path)),
    retryAfterSeconds: null,
    reason: "ready_prompt_available"
  };
}

export function daemonPromptRouteDecision(
  input: DaemonPromptRouteInput
): DaemonPromptRouteDecision {
  if (input.hasAgentsConfig) {
    return {
      action: "configured_pipeline",
      runner: "pipeline",
      requiresAgentCli: false,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: input.hasGoalFile,
      reason: "agents_config_present"
    };
  }

  if (input.requestClass === "direct_response") {
    return {
      action: "direct_pipeline",
      runner: "pipeline",
      requiresAgentCli: false,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: false,
      reason: "direct_response_fast_path"
    };
  }

  if (input.requestClass === "planning_only") {
    return {
      action: "planning_pipeline",
      runner: "pipeline",
      requiresAgentCli: true,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: false,
      reason: "planning_only_pipeline"
    };
  }

  return {
    action: "prelude_then_loop",
    runner: "loop",
    requiresAgentCli: true,
    runRefineAndPlanPrelude: true,
    enablePlanEvaluator: input.hasGoalFile,
    useGoalsEvaluatorConfig: false,
    reason: `${input.requestClass}_requires_supervised_loop`
  };
}

export function daemonLoopIterationDecision(
  input: DaemonLoopIterationInput
): DaemonLoopIterationDecision {
  const processedCount = Math.max(0, Math.trunc(input.processedCount));
  const inProgressCount = Math.max(0, Math.trunc(input.inProgressCount));
  const heartbeatStatus = inProgressCount > 0 ? "busy" : "idle";

  if (input.shutdownRequested) {
    return {
      action: "stop",
      heartbeatStatus,
      waitForChanges: false,
      reason: "shutdown_requested"
    };
  }

  if (processedCount === 0) {
    return {
      action: "wait",
      heartbeatStatus,
      waitForChanges: true,
      reason: "no_prompt_processed"
    };
  }

  return {
    action: "continue",
    heartbeatStatus,
    waitForChanges: false,
    reason: "prompt_processed"
  };
}

export function daemonStartupDecision(
  input: DaemonStartupDecisionInput
): DaemonStartupDecision {
  return {
    action: "start",
    initialHeartbeatStatus: "idle",
    startGoalsScheduler: input.goalsSchedulerConfigured,
    triggerGoalsScheduler: input.goalsSchedulerConfigured,
    startAutonomousScheduler: input.autonomousSchedulerConfigured,
    triggerAutonomousScheduler: input.autonomousSchedulerConfigured,
    reason: "daemon_startup"
  };
}

export function daemonShutdownDecision(
  input: DaemonShutdownDecisionInput
): DaemonShutdownDecision {
  return {
    action: "shutdown",
    stopGoalsScheduler: input.goalsSchedulerConfigured,
    stopAutonomousScheduler: input.autonomousSchedulerConfigured,
    closeWatcher: true,
    removeHeartbeat: true,
    closeProgressLog: input.progressLogActive,
    reason: "daemon_shutdown"
  };
}

function basename(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const slashIndex = normalized.lastIndexOf("/");
  return slashIndex >= 0 ? normalized.slice(slashIndex + 1) : normalized;
}
