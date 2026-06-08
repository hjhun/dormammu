import assert from "node:assert/strict";
import test from "node:test";

import {
  goalsProcessDecision,
  goalsTimerDecision,
  goalsTriggerDecision
} from "./scheduler.js";

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

test("goalsTriggerDecision processes immediate runs when goals exist", () => {
  assert.deepEqual(
    goalsTriggerDecision({
      stopRequested: false,
      hasGoalFiles: true
    }),
    {
      action: "process",
      cancelTimerBeforeProcess: true,
      syncTimerAfterProcess: true,
      reason: "goal_files_present"
    }
  );
});

test("goalsTriggerDecision skips stopped or empty immediate runs", () => {
  assert.equal(
    goalsTriggerDecision({
      stopRequested: true,
      hasGoalFiles: true
    }).reason,
    "stop_requested"
  );
  assert.equal(
    goalsTriggerDecision({
      stopRequested: false,
      hasGoalFiles: false
    }).reason,
    "no_goal_files"
  );
});

test("goalsProcessDecision processes non-empty batches", () => {
  assert.deepEqual(
    goalsProcessDecision({
      stopRequested: false,
      goalFileCount: 2
    }),
    {
      action: "process",
      goalFileCount: 2,
      reason: "goal_files_present"
    }
  );
});

test("goalsProcessDecision skips stopped or empty batches", () => {
  assert.deepEqual(
    goalsProcessDecision({
      stopRequested: true,
      goalFileCount: 3
    }),
    {
      action: "skip",
      goalFileCount: 3,
      reason: "stop_requested"
    }
  );
  assert.deepEqual(
    goalsProcessDecision({
      stopRequested: false,
      goalFileCount: 0
    }),
    {
      action: "skip",
      goalFileCount: 0,
      reason: "no_goal_files"
    }
  );
});

test("goalsProcessDecision clamps negative goal file counts", () => {
  assert.deepEqual(
    goalsProcessDecision({
      stopRequested: false,
      goalFileCount: -4
    }),
    {
      action: "skip",
      goalFileCount: 0,
      reason: "no_goal_files"
    }
  );
});
