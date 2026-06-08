import assert from "node:assert/strict";
import test from "node:test";

import { goalsTimerDecision } from "./scheduler.js";

test("goalsTimerDecision schedules when goals exist without a timer", () => {
  assert.deepEqual(
    goalsTimerDecision({
      hasGoalFiles: true,
      timerActive: false,
      intervalMinutes: 5
    }),
    {
      action: "schedule",
      intervalSeconds: 300,
      reason: "goal_files_present_without_active_timer"
    }
  );
});

test("goalsTimerDecision cancels when no goals remain with a timer", () => {
  assert.deepEqual(
    goalsTimerDecision({
      hasGoalFiles: false,
      timerActive: true,
      intervalMinutes: 5
    }),
    {
      action: "cancel",
      intervalSeconds: null,
      reason: "no_goal_files_with_active_timer"
    }
  );
});

test("goalsTimerDecision keeps active timer state unchanged", () => {
  assert.equal(
    goalsTimerDecision({
      hasGoalFiles: true,
      timerActive: true,
      intervalMinutes: 5
    }).action,
    "none"
  );
  assert.equal(
    goalsTimerDecision({
      hasGoalFiles: false,
      timerActive: false,
      intervalMinutes: 5
    }).action,
    "none"
  );
});

test("goalsTimerDecision clamps negative intervals to zero seconds", () => {
  assert.equal(
    goalsTimerDecision({
      hasGoalFiles: true,
      timerActive: false,
      intervalMinutes: -1
    }).intervalSeconds,
    0
  );
});
