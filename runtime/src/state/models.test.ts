import assert from "node:assert/strict";
import test from "node:test";

import {
  defaultDashboardContext,
  defaultPlanContext,
  discoverRepoGuidanceFromFiles,
  inferPrimaryRoadmapPhaseId,
  normalizePromptText,
  promptFingerprint,
  renderDashboardValues,
  renderPlanValues,
  repoGuidanceToDict,
  summarizePromptGoal
} from "./models.js";

test("discoverRepoGuidanceFromFiles finds rules and workflow files", () => {
  const guidance = discoverRepoGuidanceFromFiles("/repo", [
    "AGENTS.md",
    ".agents/AGENTS.md",
    ".dev/PROJECT.md",
    ".github/workflows/test.yml",
    ".github/workflows/deploy.yaml",
    ".github/workflows/notes.txt"
  ]);
  assert.deepEqual(repoGuidanceToDict(guidance), {
    rule_files: ["AGENTS.md", ".agents/AGENTS.md", ".dev/PROJECT.md"],
    workflow_files: [".github/workflows/deploy.yaml", ".github/workflows/test.yml"]
  });
});

test("summarizePromptGoal normalizes markdown-like prompt lines", () => {
  assert.equal(summarizePromptGoal(null, "fallback"), "fallback");
  assert.equal(summarizePromptGoal("\n# Build the feature\nmore", "fallback"), "Build the feature");
  assert.equal(summarizePromptGoal("- Fix the bug", "fallback"), "Fix the bug");
  assert.equal(summarizePromptGoal("1. Validate the result", "fallback"), "Validate the result");
});

test("inferPrimaryRoadmapPhaseId checks goal and wrapped prompt sections", () => {
  assert.equal(inferPrimaryRoadmapPhaseId({ goal: "Phase 04 continuation" }), "phase_4");
  assert.equal(
    inferPrimaryRoadmapPhaseId({
      promptText: "Wrapper\n\nTask prompt:\nPhase 7 hardening"
    }),
    "phase_7"
  );
  assert.equal(inferPrimaryRoadmapPhaseId({ goal: "No phase here" }), null);
});

test("normalizePromptText and promptFingerprint match stable text semantics", () => {
  assert.equal(normalizePromptText("  hello  \nworld   \n"), "hello\nworld");
  assert.equal(promptFingerprint(""), null);
  assert.equal(
    promptFingerprint("hello"),
    "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
  );
});

test("defaultDashboardContext renders Python-compatible template keys", () => {
  const context = defaultDashboardContext({
    goal: "Implement state model",
    roadmapPhaseIds: ["phase_2"],
    promptText: "# Phase 2 state model",
    repoGuidance: {
      ruleFiles: ["AGENTS.md"],
      workflowFiles: [".github/workflows/test.yml"]
    }
  });
  const values = renderDashboardValues(context);
  assert.equal(values.goal, "Implement state model");
  assert.match(values.active_delivery_slice, /Phase 2/);
  assert.match(values.next_action, /Review repository guidance from AGENTS.md/);
  assert.match(values.notes, /Repository rules to follow: AGENTS.md/);
});

test("defaultPlanContext extracts prompt requirements and appends validation", () => {
  const context = defaultPlanContext({
    goal: "State model",
    promptText: "- Write state helpers\n- Preserve JSON compatibility"
  });
  assert.deepEqual(context.taskItems, [
    "Phase 1. Write state helpers",
    "Phase 2. Preserve JSON compatibility",
    "Phase 3. Validate the slice and keep `.dev` state synchronized before completion"
  ]);
  assert.match(renderPlanValues(context).task_items, /- \[ \] Phase 1/);
});

test("defaultPlanContext uses fallback guidance task when prompt has no requirements", () => {
  const context = defaultPlanContext({
    goal: "State model",
    repoGuidance: { ruleFiles: ["AGENTS.md"], workflowFiles: [] }
  });
  assert.deepEqual(context.taskItems, [
    "Phase 1. Confirm the goal and success criteria for State model",
    "Phase 2. Review repository guidance from AGENTS.md",
    "Phase 3. Plan the smallest resumable slice for State model"
  ]);
});
