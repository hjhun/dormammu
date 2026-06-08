import assert from "node:assert/strict";
import test from "node:test";

import { nextGoalsRoleStep } from "./roleSequence.js";

test("nextGoalsRoleStep starts with analyzer when configured", () => {
  const step = nextGoalsRoleStep({
    goalText: "Ship it",
    roles: {
      analyzer: { cli: "analyzer-cli", model: "fast" },
      planner: { cli: "planner-cli" }
    }
  });

  assert.equal(step?.role, "analyzer");
  assert.equal(step?.cli, "analyzer-cli");
  assert.equal(step?.model, "fast");
  assert.ok(step?.prompt.includes("# Goal\n\nShip it"));
});

test("nextGoalsRoleStep plans after analyzer output exists", () => {
  const step = nextGoalsRoleStep({
    goalText: "Ship it",
    analysisText: "Analysis output",
    roles: {
      analyzer: { cli: "analyzer-cli" },
      planner: { cli: "planner-cli", model: "careful" }
    }
  });

  assert.equal(step?.role, "planner");
  assert.equal(step?.cli, "planner-cli");
  assert.equal(step?.model, "careful");
  assert.ok(step?.prompt.includes("# Requirements Analysis\n\nAnalysis output"));
});

test("nextGoalsRoleStep designs only after plan output exists", () => {
  assert.equal(
    nextGoalsRoleStep({
      goalText: "Ship it",
      roles: { designer: { cli: "designer-cli" } }
    }),
    null
  );

  const step = nextGoalsRoleStep({
    goalText: "Ship it",
    planText: "Plan output",
    roles: { designer: { cli: "designer-cli" } }
  });

  assert.equal(step?.role, "designer");
  assert.equal(step?.cli, "designer-cli");
  assert.ok(step?.prompt.includes("# Plan\n\nPlan output"));
});

test("nextGoalsRoleStep skips missing and blank cli roles", () => {
  const step = nextGoalsRoleStep({
    goalText: "Ship it",
    roles: {
      analyzer: { cli: "   " },
      planner: { cli: "planner-cli", model: "   " }
    }
  });

  assert.equal(step?.role, "planner");
  assert.equal(step?.model, null);
});

test("nextGoalsRoleStep returns null after all outputs exist", () => {
  assert.equal(
    nextGoalsRoleStep({
      goalText: "Ship it",
      analysisText: "Analysis output",
      planText: "Plan output",
      designText: "Design output",
      roles: {
        analyzer: { cli: "analyzer-cli" },
        planner: { cli: "planner-cli" },
        designer: { cli: "designer-cli" }
      }
    }),
    null
  );
});
