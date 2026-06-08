import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import type { AgentRunResult } from "./runArtifacts.js";
import {
  runAgentRunnerEntrypoint,
  runGoalsPromptProjectionEntrypoint,
  runGoalsQueueEntrypoint
} from "./runnerEntrypoint.js";

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

test("runAgentRunnerEntrypoint resolves manifest profiles and runtime skills", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runner-entrypoint-"));
  const manifestRoot = path.join(root, "repo", ".dormammu", "agent-manifests");
  const skillRoot = path.join(root, "repo", ".agents", "skills");
  await mkdir(manifestRoot, { recursive: true });
  await mkdir(path.join(skillRoot, "planning-agent"), { recursive: true });
  const manifestPath = path.join(manifestRoot, "planner.agent.json");
  await writeFile(
    manifestPath,
    JSON.stringify({
      schema_version: 1,
      name: "planner-custom",
      description: "Project planner",
      prompt: "Plan from the project manifest.",
      source: "project",
      cli: "./bin/project-planner",
      skills: ["planning-agent"]
    }),
    "utf8"
  );
  await writeFile(
    path.join(skillRoot, "planning-agent", "SKILL.md"),
    [
      "---",
      "schema_version: 1",
      "name: planning-agent",
      "description: Planning skill",
      "---",
      "Plan the active slice."
    ].join("\n"),
    "utf8"
  );
  const calls: unknown[] = [];

  const payload = await runAgentRunnerEntrypoint(
    {
      config: {
        active_agent_cli: "codex"
      },
      role: "planner",
      agents: {
        planner: {
          profile: "planner-custom"
        }
      },
      agent_manifest_search_roots: [{ scope: "project", path: manifestRoot }],
      skill_search_roots: [{ scope: "project", path: skillRoot }],
      request: {
        prompt_text: "Build with the manifest profile.",
        repo_root: path.join(root, "repo")
      },
      logs_dir: path.join(root, "repo", ".dev", "logs"),
      include_help_text: false
    },
    {
      runner: async (options) => {
        calls.push(options);
        return {
          runId: "run-1",
          cliPath: options.request.cliPath,
          workdir: options.request.workdir ?? path.join(root, "repo"),
          promptMode: "stdin",
          command: [options.request.cliPath],
          startedAt: "2026-04-25T00:00:00.000Z",
          completedAt: "2026-04-25T00:00:01.000Z",
          promptPath: path.join(root, "repo", ".dev", "logs", "run-1.prompt.txt"),
          stdoutPath: path.join(root, "repo", ".dev", "logs", "run-1.stdout.log"),
          stderrPath: path.join(root, "repo", ".dev", "logs", "run-1.stderr.log"),
          metadataPath: path.join(root, "repo", ".dev", "logs", "run-1.meta.json"),
          capabilities: {
            helpFlag: "--help",
            promptFileFlag: null,
            promptArgFlag: null,
            workdirFlag: null,
            helpText: "usage: project-planner",
            helpExitCode: 0
          },
          exitCode: 0,
          timedOut: false,
          requestedCliPath: path.join(manifestRoot, "bin", "project-planner"),
          attemptedCliPaths: [path.join(manifestRoot, "bin", "project-planner")],
          fallbackTrigger: null
        } satisfies AgentRunResult;
      }
    }
  );

  const call = calls[0] as {
    request: { cliPath: string };
  };
  assert.equal(call.request.cliPath, path.join(manifestRoot, "bin", "project-planner"));
  assert.equal(payload.runtime_skills?.profile.name, "planner-custom");
  assert.equal(payload.runtime_skills?.profile.runtime_metadata.manifest_scope, "project");
  assert.equal(payload.runtime_skills?.profile.runtime_metadata.manifest_path, manifestPath);
  assert.equal(payload.runtime_skills?.summary.preloaded_count, 1);
  assert.deepEqual(payload.runtime_skills?.prompt_lines, [
    "Runtime skills for planner / planner-custom (project profile):",
    "Visible project/user skills: planning-agent [project]",
    "Preloaded skills: planning-agent"
  ]);
});

test("runAgentRunnerEntrypoint can project pipeline stage results from stdout", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runner-stage-entrypoint-"));
  const logsDir = path.join(root, ".dev", "logs");
  await mkdir(logsDir, { recursive: true });
  const stdoutPath = path.join(logsDir, "run-1.stdout.log");
  await writeFile(stdoutPath, "pytest failed\nOVERALL: FAIL", "utf8");

  const payload = await runAgentRunnerEntrypoint(
    {
      config: {
        active_agent_cli: "codex"
      },
      role: "tester",
      pipeline_stage: {
        kind: "tester",
        attempt: 2,
        max_iterations: 4,
        report_path: path.join(logsDir, "tester-report.md")
      },
      request: {
        prompt_text: "Validate the completed slice.",
        repo_root: root
      },
      logs_dir: logsDir,
      include_help_text: false
    },
    {
      runner: async (options) => {
        return {
          runId: "run-1",
          cliPath: options.request.cliPath,
          workdir: options.request.workdir ?? root,
          promptMode: "stdin",
          command: [options.request.cliPath],
          startedAt: "2026-04-25T00:00:00.000Z",
          completedAt: "2026-04-25T00:00:01.000Z",
          promptPath: path.join(logsDir, "run-1.prompt.txt"),
          stdoutPath,
          stderrPath: path.join(logsDir, "run-1.stderr.log"),
          metadataPath: path.join(logsDir, "run-1.meta.json"),
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

  assert.deepEqual(payload.stage_result, {
    role: "tester",
    stage_name: "tester",
    status: "completed",
    verdict: "fail",
    summary: null,
    report_path: path.join(logsDir, "tester-report.md"),
    artifacts: [],
    retry: {
      attempt: 2,
      next_attempt: null,
      retries_used: null,
      max_retries: null,
      max_iterations: null
    },
    timing: null,
    metadata: {}
  });
  assert.deepEqual(payload.loop_decision, {
    action: "retry_developer",
    sourceStage: "tester",
    targetStage: "developer",
    attempt: 2,
    nextAttempt: 3,
    reason: "Tester requested another developer pass."
  });
  assert.deepEqual(payload.loop_transition, {
    action: "retry_developer",
    sourceStage: "tester",
    targetStage: "developer",
    attempt: 2,
    nextAttempt: 3,
    reason: "Tester requested another developer pass.",
    retryEvent: {
      eventType: "stage.retried",
      role: "developer",
      stage: "developer",
      status: "retried",
      payload: {
        attempt: 2,
        nextAttempt: 3,
        sourceStage: "tester",
        targetStage: "developer",
        reason: "Tester requested another developer pass."
      }
    },
    handoffEvent: {
      eventType: "supervisor.handoff",
      role: "tester",
      stage: "developer",
      status: "handoff",
      payload: {
        fromRole: "tester",
        toRole: "developer",
        reason: "Tester reported FAIL and handed the slice back to developer.",
        attempt: 3
      }
    }
  });
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

  await assert.rejects(
    runAgentRunnerEntrypoint({
      config: {},
      pipeline_stage: {
        kind: "unsupported" as "tester"
      },
      request: {
        prompt_text: "Prompt.",
        repo_root: "/repo"
      },
      logs_dir: "/repo/.dev/logs"
    }),
    /Unsupported pipeline_stage.kind/
  );
});

test("runGoalsQueueEntrypoint projects discovery and queue candidates", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-goals-entrypoint-"));
  const goalsPath = path.join(root, "goals");
  const promptPath = path.join(root, "prompts");
  await mkdir(goalsPath);
  await mkdir(promptPath);
  await writeFile(path.join(goalsPath, "b.md"), "b", "utf8");
  await writeFile(path.join(goalsPath, "a.md"), "a", "utf8");
  await writeFile(path.join(goalsPath, "ignore.txt"), "ignore", "utf8");
  await writeFile(path.join(promptPath, "20260412_a.md"), "queued", "utf8");

  const payload = await runGoalsQueueEntrypoint({
    entrypoint: "goals_queue",
    goals_path: goalsPath,
    prompt_path: promptPath,
    date_text: "20260412"
  });

  assert.deepEqual(payload.goal_files.map((file) => file.name), ["a.md", "b.md"]);
  assert.deepEqual(
    payload.candidates?.map((candidate) => ({
      name: candidate.name,
      queuedPromptName: candidate.queuedPromptName,
      alreadyQueued: candidate.alreadyQueued
    })),
    [
      {
        name: "a.md",
        queuedPromptName: "20260412_a.md",
        alreadyQueued: true
      },
      {
        name: "b.md",
        queuedPromptName: "20260412_b.md",
        alreadyQueued: false
      }
    ]
  );
});

test("runGoalsPromptProjectionEntrypoint projects queued prompt content", () => {
  assert.deepEqual(
    runGoalsPromptProjectionEntrypoint({
      entrypoint: "goals_prompt_projection",
      goal_file_path: "/repo/goals/ship-it.md",
      generated_prompt: "# Goal\n\nShip it",
      date_text: "20260412"
    }),
    {
      entrypoint: "goals_prompt_projection",
      stem: "ship-it",
      filename: "20260412_ship-it.md",
      content: "<!-- dormammu:goal_source=/repo/goals/ship-it.md -->\n\n# Goal\n\nShip it"
    }
  );
});
