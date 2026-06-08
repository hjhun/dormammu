import assert from "node:assert/strict";
import test from "node:test";

import { daemonPendingDecision, daemonPromptRouteDecision } from "./runner.js";

test("daemonPendingDecision processes the first ready prompt", () => {
  assert.deepEqual(
    daemonPendingDecision({
      processedCount: 0,
      readyPromptPaths: [
        "/repo/prompts/001-first.md",
        "/repo/prompts/002-second.md"
      ],
      retryAfterSeconds: null
    }),
    {
      action: "process",
      promptPath: "/repo/prompts/001-first.md",
      queuedPromptNames: ["002-second.md"],
      retryAfterSeconds: null,
      reason: "ready_prompt_available"
    }
  );
});

test("daemonPendingDecision waits for the settle window before first work", () => {
  assert.deepEqual(
    daemonPendingDecision({
      processedCount: 0,
      readyPromptPaths: [],
      retryAfterSeconds: 1.5
    }),
    {
      action: "wait",
      promptPath: null,
      queuedPromptNames: [],
      retryAfterSeconds: 1.5,
      reason: "settle_window_pending"
    }
  );
});

test("daemonPendingDecision idles when no prompt is ready after work", () => {
  assert.deepEqual(
    daemonPendingDecision({
      processedCount: 1,
      readyPromptPaths: [],
      retryAfterSeconds: 1.5
    }),
    {
      action: "idle",
      promptPath: null,
      queuedPromptNames: [],
      retryAfterSeconds: null,
      reason: "no_ready_prompts"
    }
  );
});

test("daemonPromptRouteDecision uses configured pipeline when agents exist", () => {
  assert.deepEqual(
    daemonPromptRouteDecision({
      hasAgentsConfig: true,
      requestClass: "full_workflow",
      hasGoalFile: true
    }),
    {
      action: "configured_pipeline",
      runner: "pipeline",
      requiresAgentCli: false,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: true,
      reason: "agents_config_present"
    }
  );
});

test("daemonPromptRouteDecision maps direct and planning requests to pipeline", () => {
  assert.deepEqual(
    daemonPromptRouteDecision({
      hasAgentsConfig: false,
      requestClass: "direct_response",
      hasGoalFile: false
    }).action,
    "direct_pipeline"
  );
  assert.deepEqual(
    daemonPromptRouteDecision({
      hasAgentsConfig: false,
      requestClass: "planning_only",
      hasGoalFile: false
    }).action,
    "planning_pipeline"
  );
});

test("daemonPromptRouteDecision maps implementation requests to prelude loop", () => {
  assert.deepEqual(
    daemonPromptRouteDecision({
      hasAgentsConfig: false,
      requestClass: "full_workflow",
      hasGoalFile: true
    }),
    {
      action: "prelude_then_loop",
      runner: "loop",
      requiresAgentCli: true,
      runRefineAndPlanPrelude: true,
      enablePlanEvaluator: true,
      useGoalsEvaluatorConfig: false,
      reason: "full_workflow_requires_supervised_loop"
    }
  );
});
