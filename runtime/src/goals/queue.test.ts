import assert from "node:assert/strict";
import test from "node:test";

import {
  goalFileStem,
  goalPromptAlreadyQueued,
  projectQueuedGoalPrompt,
  queuedGoalPromptName
} from "./queue.js";

test("goal queue helpers derive Python-compatible prompt names", () => {
  assert.equal(goalFileStem("/repo/goals/my-feature.md"), "my-feature");
  assert.equal(
    queuedGoalPromptName("/repo/goals/my-feature.md", "20260412"),
    "20260412_my-feature.md"
  );
});

test("goalPromptAlreadyQueued detects date and stem matches", () => {
  assert.equal(
    goalPromptAlreadyQueued("/repo/goals/my-feature.md", "20260412", [
      "20260412_my-feature.md"
    ]),
    true
  );
  assert.equal(
    goalPromptAlreadyQueued("/repo/goals/my-feature.md", "20260412", [
      "20260411_my-feature.md",
      "20260412_other.md"
    ]),
    false
  );
});

test("projectQueuedGoalPrompt prepends goal source metadata", () => {
  assert.deepEqual(
    projectQueuedGoalPrompt({
      goalFilePath: "/repo/goals/my-feature.md",
      generatedPrompt: "# Goal\n\nShip it",
      dateText: "20260412"
    }),
    {
      stem: "my-feature",
      filename: "20260412_my-feature.md",
      content: "<!-- dormammu:goal_source=/repo/goals/my-feature.md -->\n\n# Goal\n\nShip it"
    }
  );
});
