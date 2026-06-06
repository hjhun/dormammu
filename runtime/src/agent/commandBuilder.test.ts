import assert from "node:assert/strict";
import test from "node:test";

import { AgentRunRequest, buildCommandPlan, CliCapabilities } from "./commandBuilder.js";

const baseRequest: AgentRunRequest = {
  cliPath: "/bin/fake-agent",
  promptText: "Implement feature",
  repoRoot: "/repo",
  extraArgs: ["--verbose"]
};

const baseCapabilities: CliCapabilities = {
  helpFlag: "--help",
  promptFileFlag: "--prompt-file",
  promptArgFlag: "--prompt",
  workdirFlag: "--cwd",
  helpText: "help",
  helpExitCode: 0
};

test("buildCommandPlan prefers file mode when a prompt file flag exists", () => {
  const plan = buildCommandPlan(
    { ...baseRequest, workdir: "/repo/pkg" },
    { ...baseCapabilities, commandPrefix: ["run"] },
    "/tmp/prompt.txt"
  );
  assert.deepEqual(plan, {
    argv: [
      "/bin/fake-agent",
      "run",
      "--cwd",
      "/repo/pkg",
      "--prompt-file",
      "/tmp/prompt.txt",
      "--verbose"
    ],
    promptMode: "file",
    stdinInput: null
  });
});

test("buildCommandPlan supports explicit arg, stdin, and positional modes", () => {
  assert.deepEqual(
    buildCommandPlan({ ...baseRequest, inputMode: "arg" }, baseCapabilities, "/tmp/prompt.txt"),
    {
      argv: ["/bin/fake-agent", "--prompt", "Implement feature", "--verbose"],
      promptMode: "arg",
      stdinInput: null
    }
  );
  assert.deepEqual(
    buildCommandPlan({ ...baseRequest, inputMode: "stdin" }, baseCapabilities, "/tmp/prompt.txt"),
    {
      argv: ["/bin/fake-agent", "--verbose"],
      promptMode: "stdin",
      stdinInput: "Implement feature"
    }
  );
  assert.deepEqual(
    buildCommandPlan(
      { ...baseRequest, inputMode: "positional" },
      baseCapabilities,
      "/tmp/prompt.txt"
    ),
    {
      argv: ["/bin/fake-agent", "--verbose", "Implement feature"],
      promptMode: "positional",
      stdinInput: null
    }
  );
});

test("buildCommandPlan errors when requested mode has no supported flag", () => {
  assert.throws(
    () =>
      buildCommandPlan(
        { ...baseRequest, inputMode: "file" },
        { ...baseCapabilities, promptFileFlag: null },
        "/tmp/prompt.txt"
      ),
    /No prompt file flag/
  );
  assert.throws(
    () =>
      buildCommandPlan(
        { ...baseRequest, inputMode: "arg" },
        { ...baseCapabilities, promptArgFlag: null },
        "/tmp/prompt.txt"
      ),
    /No prompt argument flag/
  );
});
