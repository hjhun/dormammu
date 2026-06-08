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

export type DaemonInstanceLockAction = "skip" | "hold" | "reject";

export type DaemonInstanceLockDecisionInput = {
  fcntlAvailable: boolean;
  lockAcquired: boolean;
  promptPath: string;
  existingPid: string | null;
};

export type DaemonInstanceLockDecision = {
  action: DaemonInstanceLockAction;
  writePidFile: boolean;
  errorMessage: string | null;
  reason: string;
};

export type DaemonInstanceUnlockAction = "skip" | "release";

export type DaemonInstanceUnlockDecisionInput = {
  fcntlAvailable: boolean;
  lockHeld: boolean;
};

export type DaemonInstanceUnlockDecision = {
  action: DaemonInstanceUnlockAction;
  unlockFcntl: boolean;
  closeLockFile: boolean;
  clearPidLockFile: boolean;
  removePidFile: boolean;
  reason: string;
};

export type DaemonHeartbeatStatus = "busy" | "idle";

export type DaemonHeartbeatWriteAction = "skip" | "write";

export type DaemonHeartbeatWriteDecisionInput = {
  heartbeatPathConfigured: boolean;
  pid: number;
  status: DaemonHeartbeatStatus;
  timestamp: string;
};

export type DaemonHeartbeatPayload = {
  pid: number;
  status: DaemonHeartbeatStatus;
  ts: string;
};

export type DaemonHeartbeatWriteDecision = {
  action: DaemonHeartbeatWriteAction;
  ensureParent: boolean;
  heartbeatPayload: DaemonHeartbeatPayload | null;
  reason: string;
};

export type DaemonHeartbeatRemoveAction = "skip" | "remove";

export type DaemonHeartbeatRemoveDecisionInput = {
  heartbeatPathConfigured: boolean;
};

export type DaemonHeartbeatRemoveDecision = {
  action: DaemonHeartbeatRemoveAction;
  removeHeartbeat: boolean;
  reason: string;
};

export type DaemonWatcherBackend = "auto" | "inotify" | "polling";

export type DaemonWatcherBackendDecisionAction = "error" | "use";

export type DaemonWatcherBackendDecisionInput = {
  requestedBackend: DaemonWatcherBackend;
  inotifyAvailable: boolean;
};

export type DaemonWatcherBackendDecision = {
  action: DaemonWatcherBackendDecisionAction;
  backend: "inotify" | "polling" | null;
  errorMessage: string | null;
  reason: string;
};

export type DaemonWatcherWaitAction = "skip" | "wait";

export type DaemonWatcherWaitDecisionInput = {
  waitRequested: boolean;
  shutdownRequested: boolean;
  watcherBackend: string;
};

export type DaemonWatcherWaitDecision = {
  action: DaemonWatcherWaitAction;
  waitForChanges: boolean;
  watcherBackend: string;
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

export function daemonInstanceLockDecision(
  input: DaemonInstanceLockDecisionInput
): DaemonInstanceLockDecision {
  if (!input.fcntlAvailable) {
    return {
      action: "skip",
      writePidFile: false,
      errorMessage: null,
      reason: "fcntl_unavailable"
    };
  }

  if (input.lockAcquired) {
    return {
      action: "hold",
      writePidFile: true,
      errorMessage: null,
      reason: "instance_lock_acquired"
    };
  }

  const existingPid = input.existingPid?.trim() ?? "";
  const pidInfo = existingPid.length > 0
    ? ` (existing daemon PID: ${existingPid})`
    : "";
  return {
    action: "reject",
    writePidFile: false,
    errorMessage: [
      `Another dormammu daemon is already running against ${input.promptPath}${pidInfo}.`,
      "Stop it first or use a different prompt_path."
    ].join("\n"),
    reason: "instance_lock_busy"
  };
}

export function daemonInstanceUnlockDecision(
  input: DaemonInstanceUnlockDecisionInput
): DaemonInstanceUnlockDecision {
  if (!input.fcntlAvailable || !input.lockHeld) {
    return {
      action: "skip",
      unlockFcntl: false,
      closeLockFile: false,
      clearPidLockFile: false,
      removePidFile: false,
      reason: !input.fcntlAvailable ? "fcntl_unavailable" : "lock_not_held"
    };
  }

  return {
    action: "release",
    unlockFcntl: true,
    closeLockFile: true,
    clearPidLockFile: true,
    removePidFile: true,
    reason: "instance_lock_release"
  };
}

export function daemonHeartbeatWriteDecision(
  input: DaemonHeartbeatWriteDecisionInput
): DaemonHeartbeatWriteDecision {
  if (!input.heartbeatPathConfigured) {
    return {
      action: "skip",
      ensureParent: false,
      heartbeatPayload: null,
      reason: "heartbeat_path_unconfigured"
    };
  }

  return {
    action: "write",
    ensureParent: true,
    heartbeatPayload: {
      pid: Math.trunc(input.pid),
      status: input.status,
      ts: input.timestamp
    },
    reason: "heartbeat_write"
  };
}

export function daemonHeartbeatRemoveDecision(
  input: DaemonHeartbeatRemoveDecisionInput
): DaemonHeartbeatRemoveDecision {
  if (!input.heartbeatPathConfigured) {
    return {
      action: "skip",
      removeHeartbeat: false,
      reason: "heartbeat_path_unconfigured"
    };
  }

  return {
    action: "remove",
    removeHeartbeat: true,
    reason: "heartbeat_remove"
  };
}

export function daemonWatcherBackendDecision(
  input: DaemonWatcherBackendDecisionInput
): DaemonWatcherBackendDecision {
  if (input.requestedBackend === "polling") {
    return {
      action: "use",
      backend: "polling",
      errorMessage: null,
      reason: "polling_requested"
    };
  }

  if (input.requestedBackend === "inotify") {
    if (!input.inotifyAvailable) {
      return {
        action: "error",
        backend: null,
        errorMessage: "Inotify backend is not available on this platform.",
        reason: "inotify_unavailable"
      };
    }
    return {
      action: "use",
      backend: "inotify",
      errorMessage: null,
      reason: "inotify_requested"
    };
  }

  if (input.inotifyAvailable) {
    return {
      action: "use",
      backend: "inotify",
      errorMessage: null,
      reason: "auto_prefers_inotify"
    };
  }

  return {
    action: "use",
    backend: "polling",
    errorMessage: null,
    reason: "auto_falls_back_to_polling"
  };
}

export function daemonWatcherWaitDecision(
  input: DaemonWatcherWaitDecisionInput
): DaemonWatcherWaitDecision {
  const watcherBackend = input.watcherBackend.trim() || "unknown";

  if (input.shutdownRequested) {
    return {
      action: "skip",
      waitForChanges: false,
      watcherBackend,
      reason: "shutdown_requested"
    };
  }

  if (!input.waitRequested) {
    return {
      action: "skip",
      waitForChanges: false,
      watcherBackend,
      reason: "wait_not_requested"
    };
  }

  return {
    action: "wait",
    waitForChanges: true,
    watcherBackend,
    reason: "wait_requested"
  };
}

function basename(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const slashIndex = normalized.lastIndexOf("/");
  return slashIndex >= 0 ? normalized.slice(slashIndex + 1) : normalized;
}
