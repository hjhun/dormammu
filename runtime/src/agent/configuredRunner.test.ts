import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import type { AgentRunResult } from "./runArtifacts.js";
import {
  parseAgentRuntimeConfig,
  runConfiguredAgentCommand
} from "./configuredRunner.js";
import { builtInProfileForRole } from "./profiles.js";

test("parseAgentRuntimeConfig normalizes Python-compatible agent runtime fields", () => {
  const configPath = path.join(os.tmpdir(), "dormammu-config", "dormammu.json");
  const configDir = path.dirname(configPath);

  const config = parseAgentRuntimeConfig(
    {
      active_agent_cli: "./bin/primary",
      fallback_agent_clis: [
        "gemini",
        {
          path: "./bin/fallback",
          input_mode: "arg",
          prompt_flag: "--message",
          extra_args: ["--yes"]
        }
      ],
      cli_overrides: {
        "./bin/primary": {
          input_mode: "file",
          prompt_flag: "--prompt-file",
          extra_args: ["--verbose"]
        },
        CLINE: {
          extra_args: ["-y", "--timeout", "1200"]
        }
      },
      token_exhaustion_patterns: ["hard quota"],
      process_timeout_seconds: 3,
      fallback_on_nonzero_exit: true
    },
    { configPath }
  );

  assert.equal(config.activeAgentCli, path.join(configDir, "bin", "primary"));
  assert.deepEqual(config.fallbackAgentClis, [
    { path: "gemini" },
    {
      path: path.join(configDir, "bin", "fallback"),
      inputMode: "arg",
      promptFlag: "--message",
      extraArgs: ["--yes"]
    }
  ]);
  assert.deepEqual(config.cliOverrides[path.join(configDir, "bin", "primary")], {
    inputMode: "file",
    promptFlag: "--prompt-file",
    extraArgs: ["--verbose"]
  });
  assert.deepEqual(config.cliOverrides.cline, {
    inputMode: null,
    promptFlag: null,
    extraArgs: ["-y", "--timeout", "1200"]
  });
  assert.deepEqual(config.tokenExhaustionPatterns, ["hard quota"]);
  assert.equal(config.processTimeoutMs, 3000);
  assert.equal(config.fallbackOnNonzeroExit, true);
});

test("parseAgentRuntimeConfig applies Python default fallback and token settings", () => {
  const config = parseAgentRuntimeConfig({});
  const emptyTokens = parseAgentRuntimeConfig({ token_exhaustion_patterns: [] });
  const nullTokens = parseAgentRuntimeConfig({ token_exhaustion_patterns: null });

  assert.equal(config.activeAgentCli, null);
  assert.deepEqual(
    config.fallbackAgentClis.map((item) => item.path),
    ["codex", "claude", "gemini"]
  );
  assert.ok(config.tokenExhaustionPatterns.includes("quota exceeded"));
  assert.ok(emptyTokens.tokenExhaustionPatterns.includes("quota exceeded"));
  assert.ok(nullTokens.tokenExhaustionPatterns.includes("quota exceeded"));
  assert.equal(config.processTimeoutMs, null);
  assert.equal(config.fallbackOnNonzeroExit, false);
});

test("runConfiguredAgentCommand maps normalized config into runAgentCommand options", async () => {
  const calls: unknown[] = [];
  const config = parseAgentRuntimeConfig({
    active_agent_cli: "codex",
    fallback_agent_clis: ["gemini"],
    cli_overrides: {
      codex: { extra_args: ["--full-auto"] }
    },
    token_exhaustion_patterns: ["quota exceeded"],
    process_timeout_seconds: 5,
    fallback_on_nonzero_exit: true
  });

  const result = await runConfiguredAgentCommand({
    config,
    request: {
      promptText: "Build the next slice.",
      repoRoot: "/repo"
    },
    logsDir: "/repo/.dev/logs",
    runner: async (options) => {
      calls.push(options);
      return {
        runId: "run-1",
        cliPath: options.request.cliPath,
        workdir: "/repo",
        promptMode: "stdin",
        command: [options.request.cliPath],
        startedAt: "2026-04-25T00:00:00.000Z",
        completedAt: "2026-04-25T00:00:01.000Z",
        promptPath: "/repo/.dev/logs/run-1.prompt.txt",
        stdoutPath: "/repo/.dev/logs/run-1.stdout.log",
        stderrPath: "/repo/.dev/logs/run-1.stderr.log",
        metadataPath: "/repo/.dev/logs/run-1.meta.json",
        capabilities: {
          helpFlag: "--help",
          promptFileFlag: null,
          promptArgFlag: null,
          workdirFlag: null,
          helpText: "",
          helpExitCode: 0
        },
        exitCode: 0,
        timedOut: false
      } satisfies AgentRunResult;
    }
  });

  assert.equal(result.cliPath, "codex");
  assert.equal(calls.length, 1);
  const call = calls[0] as {
    request: { cliPath: string };
    fallbackAgentClis: Array<{ path: string }>;
    cliOverrides: Record<string, { extraArgs: string[] }>;
    tokenExhaustionPatterns: string[];
    fallbackOnNonzeroExit: boolean;
    timeoutMs: number;
  };
  assert.equal(call.request.cliPath, "codex");
  assert.deepEqual(call.fallbackAgentClis, [{ path: "gemini" }]);
  assert.deepEqual(call.cliOverrides.codex.extraArgs, ["--full-auto"]);
  assert.deepEqual(call.tokenExhaustionPatterns, ["quota exceeded"]);
  assert.equal(call.fallbackOnNonzeroExit, true);
  assert.equal(call.timeoutMs, 5000);
  assert.equal("config" in call, false);
  assert.equal("runner" in call, false);
});

test("runConfiguredAgentCommand preserves explicit timeout overrides", async () => {
  const calls: unknown[] = [];

  await runConfiguredAgentCommand({
    config: parseAgentRuntimeConfig({
      active_agent_cli: "codex",
      process_timeout_seconds: 5
    }),
    request: {
      promptText: "No timeout.",
      repoRoot: "/repo"
    },
    logsDir: "/repo/.dev/logs",
    timeoutMs: null,
    runner: async (options) => {
      calls.push(options);
      return {
        runId: "run-1",
        cliPath: options.request.cliPath,
        workdir: "/repo",
        promptMode: "stdin",
        command: [options.request.cliPath],
        startedAt: "2026-04-25T00:00:00.000Z",
        completedAt: "2026-04-25T00:00:01.000Z",
        promptPath: "/repo/.dev/logs/run-1.prompt.txt",
        stdoutPath: "/repo/.dev/logs/run-1.stdout.log",
        stderrPath: "/repo/.dev/logs/run-1.stderr.log",
        metadataPath: "/repo/.dev/logs/run-1.meta.json",
        capabilities: {
          helpFlag: "--help",
          promptFileFlag: null,
          promptArgFlag: null,
          workdirFlag: null,
          helpText: "",
          helpExitCode: 0
        },
        exitCode: 0,
        timedOut: false
      } satisfies AgentRunResult;
    }
  });

  assert.equal((calls[0] as { timeoutMs: null }).timeoutMs, null);
});

test("runConfiguredAgentCommand uses profile cli before active config cli", async () => {
  const calls: unknown[] = [];
  const profile = {
    ...builtInProfileForRole("planner"),
    cli_override: "/repo/bin/planner"
  };

  await runConfiguredAgentCommand({
    config: parseAgentRuntimeConfig({ active_agent_cli: "codex" }),
    profile,
    request: {
      promptText: "Use profile CLI.",
      repoRoot: "/repo"
    },
    logsDir: "/repo/.dev/logs",
    runner: async (options) => {
      calls.push(options);
      return {
        runId: "run-1",
        cliPath: options.request.cliPath,
        workdir: "/repo",
        promptMode: "stdin",
        command: [options.request.cliPath],
        startedAt: "2026-04-25T00:00:00.000Z",
        completedAt: "2026-04-25T00:00:01.000Z",
        promptPath: "/repo/.dev/logs/run-1.prompt.txt",
        stdoutPath: "/repo/.dev/logs/run-1.stdout.log",
        stderrPath: "/repo/.dev/logs/run-1.stderr.log",
        metadataPath: "/repo/.dev/logs/run-1.meta.json",
        capabilities: {
          helpFlag: "--help",
          promptFileFlag: null,
          promptArgFlag: null,
          workdirFlag: null,
          helpText: "",
          helpExitCode: 0
        },
        exitCode: 0,
        timedOut: false
      } satisfies AgentRunResult;
    }
  });

  assert.equal((calls[0] as { request: { cliPath: string } }).request.cliPath, "/repo/bin/planner");
});

test("runConfiguredAgentCommand requires a request or config CLI", async () => {
  await assert.rejects(
    runConfiguredAgentCommand({
      config: parseAgentRuntimeConfig({ active_agent_cli: null }),
      request: {
        promptText: "No CLI.",
        repoRoot: "/repo"
      },
      logsDir: "/repo/.dev/logs"
    }),
    /No CLI is configured/
  );
});
