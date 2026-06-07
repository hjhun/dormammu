import assert from "node:assert/strict";
import test from "node:test";

import type { AgentRunRequest, CliCapabilities } from "./commandBuilder.js";
import { applyDefaultPresetExtraArgs } from "./presetArgs.js";

const baseCapabilities: CliCapabilities = {
  helpFlag: "--help",
  promptFileFlag: null,
  promptArgFlag: null,
  workdirFlag: null,
  helpText: "usage",
  helpExitCode: 0
};

const baseRequest: AgentRunRequest = {
  cliPath: "/bin/fake-agent",
  promptText: "prompt",
  repoRoot: "/repo",
  extraArgs: []
};

test("applyDefaultPresetExtraArgs prepends codex defaults when absent", () => {
  const request = applyDefaultPresetExtraArgs(
    { ...baseRequest, cliPath: "/usr/local/bin/codex" },
    {
      ...baseCapabilities,
      helpText: "usage: codex exec --skip-git-repo-check"
    }
  );

  assert.deepEqual(request.extraArgs, [
    "--dangerously-bypass-approvals-and-sandbox",
    "--skip-git-repo-check"
  ]);
});

test("applyDefaultPresetExtraArgs respects explicit codex approval and skip flags", () => {
  const request = applyDefaultPresetExtraArgs(
    {
      ...baseRequest,
      cliPath: "codex",
      extraArgs: ["--full-auto", "--skip-git-repo-check"]
    },
    {
      ...baseCapabilities,
      helpText: "usage: codex exec --skip-git-repo-check"
    }
  );

  assert.deepEqual(request.extraArgs, ["--full-auto", "--skip-git-repo-check"]);
});

test("applyDefaultPresetExtraArgs prepends gemini defaults and keeps explicit args", () => {
  const request = applyDefaultPresetExtraArgs(
    {
      ...baseRequest,
      cliPath: "gemini",
      extraArgs: ["--model", "pro"]
    },
    baseCapabilities
  );

  assert.deepEqual(request.extraArgs, [
    "--approval-mode",
    "yolo",
    "--include-directories",
    "/",
    "--model",
    "pro"
  ]);
});

test("applyDefaultPresetExtraArgs sanitizes duplicate gemini approval and include args", () => {
  const request = applyDefaultPresetExtraArgs(
    {
      ...baseRequest,
      cliPath: "gemini",
      extraArgs: [
        "--approval-mode",
        "auto_edit",
        "--include-directories",
        "/tmp",
        "--approval-mode",
        "manual",
        "--include-directories",
        "/repo"
      ]
    },
    baseCapabilities
  );

  assert.deepEqual(request.extraArgs, [
    "--approval-mode",
    "manual",
    "--include-directories",
    "/repo"
  ]);
});

test("applyDefaultPresetExtraArgs prepends claude and cline defaults", () => {
  assert.deepEqual(
    applyDefaultPresetExtraArgs(
      { ...baseRequest, cliPath: "claude", extraArgs: [] },
      baseCapabilities
    ).extraArgs,
    ["--dangerously-skip-permissions"]
  );
  assert.deepEqual(
    applyDefaultPresetExtraArgs(
      { ...baseRequest, cliPath: "cline", extraArgs: [] },
      baseCapabilities
    ).extraArgs,
    ["--timeout", "1200"]
  );
});
