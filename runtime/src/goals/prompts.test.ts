import assert from "node:assert/strict";
import test from "node:test";

import {
  analyzerPrompt,
  buildGoalsPrompt,
  designerPrompt,
  goalSourceTag,
  plannerPrompt,
  queuedGoalPromptFilename
} from "./prompts.js";

test("buildGoalsPrompt includes language notice and workflow contract", () => {
  const prompt = buildGoalsPrompt({ goalText: "do something" });
  assert.ok(prompt.includes("Language requirement"));
  assert.ok(prompt.includes("English"));
  assert.ok(prompt.indexOf("Language requirement") < prompt.indexOf("# Goal"));
  assert.ok(prompt.includes("Workflow Contract"));
  assert.ok(prompt.includes("refine -> plan"));
  assert.ok(prompt.includes("# Goal\n\ndo something"));
});

test("buildGoalsPrompt includes optional analysis plan and design sections", () => {
  const prompt = buildGoalsPrompt({
    goalText: "  goal  ",
    analysisText: "  analysis text  ",
    planText: "  plan text  ",
    designText: "  design text  "
  });

  assert.ok(prompt.includes("## Requirements Analysis\n\nanalysis text"));
  assert.ok(prompt.includes("## Plan\n\nplan text"));
  assert.ok(prompt.includes("## Design\n\ndesign text"));
});

test("role prompt builders keep Python-compatible goal context", () => {
  assert.ok(analyzerPrompt("ship it").includes("# Goal\n\nship it"));
  assert.ok(analyzerPrompt("ship it").includes("acceptance criteria"));

  const planner = plannerPrompt("ship it", "analysis");
  assert.ok(planner.includes("refine -> plan"));
  assert.ok(planner.includes("# Requirements Analysis\n\nanalysis"));

  const designer = designerPrompt("ship it", "analysis", "plan");
  assert.ok(designer.includes("# Original Goal\n\nship it"));
  assert.ok(designer.includes("# Requirements Analysis\n\nanalysis"));
  assert.ok(designer.includes("# Plan\n\nplan"));
});

test("goal metadata helpers match queue naming contracts", () => {
  assert.equal(
    goalSourceTag("/repo/goals/alpha.md"),
    "<!-- dormammu:goal_source=/repo/goals/alpha.md -->\n\n"
  );
  assert.equal(queuedGoalPromptFilename("20260412", "alpha"), "20260412_alpha.md");
});
