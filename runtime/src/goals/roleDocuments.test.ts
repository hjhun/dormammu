import assert from "node:assert/strict";
import test from "node:test";

import {
  goalsRoleDocumentContent,
  goalsRoleDocumentFilename,
  projectGoalsRoleDocument
} from "./roleDocuments.js";

test("goals role document helpers derive Python-compatible names", () => {
  assert.equal(
    goalsRoleDocumentFilename("20260412", "planner", "ship-it"),
    "20260412_planner_ship-it.md"
  );
});

test("goalsRoleDocumentContent matches the Python Markdown projection", () => {
  assert.equal(
    goalsRoleDocumentContent("planner", "ship-it", "Plan output\n"),
    "# Planner \u2014 ship-it\n\nPlan output\n"
  );
});

test("goalsRoleDocumentContent uses Python capitalize semantics", () => {
  assert.equal(
    goalsRoleDocumentContent("PLAN_EVALUATOR", "ship-it", ""),
    "# Plan_evaluator \u2014 ship-it\n\n"
  );
});

test("projectGoalsRoleDocument projects filename, path, and content", () => {
  assert.deepEqual(
    projectGoalsRoleDocument({
      logsDir: "/repo/.dev/logs",
      dateText: "20260412",
      role: "designer",
      stem: "ship-it",
      output: "Design output"
    }),
    {
      filename: "20260412_designer_ship-it.md",
      path: "/repo/.dev/logs/20260412_designer_ship-it.md",
      content: "# Designer \u2014 ship-it\n\nDesign output"
    }
  );
});
