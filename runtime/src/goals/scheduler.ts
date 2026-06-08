export type GoalsTimerDecisionAction = "schedule" | "cancel" | "none";
export type GoalsTriggerDecisionAction = "process" | "skip";
export type GoalsProcessDecisionAction = "process" | "skip";
export type GoalsTimerFiredDecisionAction = "process" | "skip";
export type GoalsSingleGoalDecisionAction = "write" | "skip";

export type GoalsTimerDecisionInput = {
  hasGoalFiles: boolean;
  timerActive: boolean;
  intervalMinutes: number;
};

export type GoalsTriggerDecisionInput = {
  stopRequested: boolean;
  hasGoalFiles: boolean;
};

export type GoalsProcessDecisionInput = {
  stopRequested: boolean;
  goalFileCount: number;
};

export type GoalsTimerFiredDecisionInput = {
  stopRequested: boolean;
};

export type GoalsSingleGoalDecisionInput = {
  promptExists: boolean;
};

export type GoalsTimerDecision = {
  action: GoalsTimerDecisionAction;
  intervalSeconds: number | null;
  reason: string;
};

export type GoalsTriggerDecision = {
  action: GoalsTriggerDecisionAction;
  cancelTimerBeforeProcess: boolean;
  syncTimerAfterProcess: boolean;
  reason: string;
};

export type GoalsProcessDecision = {
  action: GoalsProcessDecisionAction;
  goalFileCount: number;
  reason: string;
};

export type GoalsTimerFiredDecision = {
  action: GoalsTimerFiredDecisionAction;
  clearTimerBeforeProcess: boolean;
  syncTimerAfterProcess: boolean;
  reason: string;
};

export type GoalsSingleGoalDecision = {
  action: GoalsSingleGoalDecisionAction;
  reason: string;
};

export function goalsTimerDecision(
  input: GoalsTimerDecisionInput
): GoalsTimerDecision {
  const intervalSeconds = Math.max(0, input.intervalMinutes * 60);
  if (input.hasGoalFiles && !input.timerActive) {
    return {
      action: "schedule",
      intervalSeconds,
      reason: "goal_files_present_without_active_timer"
    };
  }
  if (!input.hasGoalFiles && input.timerActive) {
    return {
      action: "cancel",
      intervalSeconds: null,
      reason: "no_goal_files_with_active_timer"
    };
  }
  return {
    action: "none",
    intervalSeconds: null,
    reason: input.hasGoalFiles
      ? "goal_files_present_with_active_timer"
      : "no_goal_files_without_active_timer"
  };
}

export function goalsTriggerDecision(
  input: GoalsTriggerDecisionInput
): GoalsTriggerDecision {
  if (input.stopRequested) {
    return {
      action: "skip",
      cancelTimerBeforeProcess: false,
      syncTimerAfterProcess: false,
      reason: "stop_requested"
    };
  }
  if (!input.hasGoalFiles) {
    return {
      action: "skip",
      cancelTimerBeforeProcess: false,
      syncTimerAfterProcess: false,
      reason: "no_goal_files"
    };
  }
  return {
    action: "process",
    cancelTimerBeforeProcess: true,
    syncTimerAfterProcess: true,
    reason: "goal_files_present"
  };
}

export function goalsProcessDecision(
  input: GoalsProcessDecisionInput
): GoalsProcessDecision {
  const goalFileCount = Math.max(0, Math.trunc(input.goalFileCount));
  if (input.stopRequested) {
    return {
      action: "skip",
      goalFileCount,
      reason: "stop_requested"
    };
  }
  if (goalFileCount === 0) {
    return {
      action: "skip",
      goalFileCount,
      reason: "no_goal_files"
    };
  }
  return {
    action: "process",
    goalFileCount,
    reason: "goal_files_present"
  };
}

export function goalsTimerFiredDecision(
  input: GoalsTimerFiredDecisionInput
): GoalsTimerFiredDecision {
  if (input.stopRequested) {
    return {
      action: "skip",
      clearTimerBeforeProcess: true,
      syncTimerAfterProcess: false,
      reason: "stop_requested"
    };
  }
  return {
    action: "process",
    clearTimerBeforeProcess: true,
    syncTimerAfterProcess: true,
    reason: "timer_fired"
  };
}

export function goalsSingleGoalDecision(
  input: GoalsSingleGoalDecisionInput
): GoalsSingleGoalDecision {
  if (input.promptExists) {
    return {
      action: "skip",
      reason: "queued_prompt_exists"
    };
  }
  return {
    action: "write",
    reason: "queued_prompt_missing"
  };
}
