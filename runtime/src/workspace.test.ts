import assert from "node:assert/strict";
import test from "node:test";

import { runtimePathPromptDecision } from "./workspace.js";

test("runtimePathPromptDecision renders Python-compatible runtime guidance", () => {
  assert.deepEqual(
    runtimePathPromptDecision({
      repoRoot: "/repo",
      repoDevDir: "/repo/.dev",
      baseDevDir: "/home/user/.dormammu/workspace/repo/.dev",
      tmpDir: "/home/user/.dormammu/workspace/repo/.tmp",
      resultsDir: "/home/user/.dormammu/results"
    }),
    {
      runtimePathsText: [
        "- Real project root: `/repo`",
        "- Repository-local project docs root: `/repo/.dev`",
        (
          "- Operational state directory (`.dev` in workflow docs): " +
          "`/home/user/.dormammu/workspace/repo/.dev`"
        ),
        (
          "- Managed temporary directory (`.tmp`): " +
          "`/home/user/.dormammu/workspace/repo/.tmp`"
        ),
        "- Result reports directory: `/home/user/.dormammu/results`",
        (
          "Interpret any `.dev/...` reference in prompts and workflow guidance " +
          "as relative to the operational state directory above, not to the " +
          "real project root."
        )
      ].join("\n"),
      reason: "runtime_path_prompt_projected"
    }
  );
});
