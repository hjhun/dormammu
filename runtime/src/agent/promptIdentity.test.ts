import assert from "node:assert/strict";
import test from "node:test";

import { prependCliIdentity } from "./promptIdentity.js";

test("prependCliIdentity prefixes prompts with the CLI basename", () => {
  assert.equal(
    prependCliIdentity("Run the task.", "/usr/local/bin/codex"),
    "[codex]\nRun the task."
  );
});

test("prependCliIdentity does not duplicate an existing header", () => {
  assert.equal(
    prependCliIdentity("[codex]\nRun the task.", "/usr/local/bin/codex"),
    "[codex]\nRun the task."
  );
  assert.equal(prependCliIdentity("[codex]", "/usr/local/bin/codex"), "[codex]");
});

test("prependCliIdentity falls back to agent for empty path", () => {
  assert.equal(prependCliIdentity("hello", ""), "[agent]\nhello");
});
