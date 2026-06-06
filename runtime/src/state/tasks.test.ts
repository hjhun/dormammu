import assert from "node:assert/strict";
import test from "node:test";

import { operatorTaskSyncToDict, parseTasksDocument } from "./tasks.js";

test("parseTasksDocument collects checkbox summary", () => {
  const parsed = parseTasksDocument(
    [
      "# PLAN",
      "",
      "## Prompt-Derived Implementation Plan",
      "",
      "- [O] Phase 1. First task",
      "- [x] Phase 2. Second task",
      "- [ ] Phase 3. Third task",
      "",
      "## Resume Checkpoint",
      "",
      "Resume from the third task.",
      ""
    ].join("\n")
  );

  const payload = operatorTaskSyncToDict(parsed.currentWorkflow, {
    syncedAt: "2026-04-25T00:00:00+00:00"
  });
  assert.equal(payload.total_tasks, 3);
  assert.equal(payload.completed_tasks, 2);
  assert.equal(payload.pending_tasks, 1);
  assert.equal(payload.all_completed, false);
  assert.equal(payload.next_pending_task, "Phase 3. Third task");
  assert.equal(payload.resume_checkpoint, "Resume from the third task.");
});
