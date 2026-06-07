import assert from "node:assert/strict";
import test from "node:test";

import type { AgentRunResult } from "./runArtifacts.js";
import { runAgentRunnerEntrypoint } from "./runnerEntrypoint.js";

test("runAgentRunnerEntrypoint runs configured agent payloads and returns dicts", async () => {
  const calls: unknown[] = [];

  const payload = await runAgentRunnerEntrypoint(
    {
      config: {
        active_agent_cli: "codex",
        fallback_agent_clis: ["gemini"],
        token_exhaustion_patterns: ["quota exceeded"],
        process_timeout_seconds: 7,
        fallback_on_nonzero_exit: true
      },
      request: {
        prompt_text: "Build the configured entrypoint.",
        repo_root: "/repo",
        input_mode: "stdin",
        extra_args: ["--dry-run"],
        run_label: "configured-entrypoint"
      },
      logs_dir: "/repo/.dev/logs",
      include_help_text: false
    },
    {
      runner: async (options) => {
        calls.push(options);
        return {
          runId: "run-1",
          cliPath: options.request.cliPath,
          workdir: options.request.workdir ?? "/repo",
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
            helpText: "usage: codex",
            helpExitCode: 0
          },
          exitCode: 0,
          timedOut: false,
          requestedCliPath: "codex",
          attemptedCliPaths: ["codex"],
          fallbackTrigger: null
        } satisfies AgentRunResult;
      }
    }
  );

  assert.equal(payload.run_id, "run-1");
  assert.equal(payload.cli_path, "codex");
  assert.equal(payload.exit_code, 0);
  assert.equal(payload.capabilities.help_text, undefined);

  const call = calls[0] as {
    request: {
      cliPath: string;
      promptText: string;
      inputMode: string;
      extraArgs: string[];
    };
    fallbackAgentClis: Array<{ path: string }>;
    tokenExhaustionPatterns: string[];
    fallbackOnNonzeroExit: boolean;
    timeoutMs: number;
  };
  assert.equal(call.request.cliPath, "codex");
  assert.equal(call.request.promptText, "Build the configured entrypoint.");
  assert.equal(call.request.inputMode, "stdin");
  assert.deepEqual(call.request.extraArgs, ["--dry-run"]);
  assert.deepEqual(call.fallbackAgentClis, [{ path: "gemini" }]);
  assert.deepEqual(call.tokenExhaustionPatterns, ["quota exceeded"]);
  assert.equal(call.fallbackOnNonzeroExit, true);
  assert.equal(call.timeoutMs, 7000);
});

test("runAgentRunnerEntrypoint validates request payloads", async () => {
  await assert.rejects(
    runAgentRunnerEntrypoint({
      config: {},
      request: {
        prompt_text: "",
        repo_root: "/repo"
      },
      logs_dir: "/repo/.dev/logs"
    }),
    /request.prompt_text must be a non-empty string/
  );

  await assert.rejects(
    runAgentRunnerEntrypoint({
      config: {},
      request: {
        prompt_text: "Prompt.",
        repo_root: "/repo",
        input_mode: "bad" as "stdin"
      },
      logs_dir: "/repo/.dev/logs"
    }),
    /Unsupported request.input_mode/
  );
});
