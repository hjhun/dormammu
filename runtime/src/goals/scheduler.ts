export type GoalsTimerDecisionAction = "schedule" | "cancel" | "none";

export type GoalsTimerDecisionInput = {
  hasGoalFiles: boolean;
  timerActive: boolean;
  intervalMinutes: number;
};

export type GoalsTimerDecision = {
  action: GoalsTimerDecisionAction;
  intervalSeconds: number | null;
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
