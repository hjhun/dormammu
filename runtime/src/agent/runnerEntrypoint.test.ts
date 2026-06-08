import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import type { AgentRunResult } from "./runArtifacts.js";
import {
  runDaemonArtifactPersistedEventEntrypoint,
  runDaemonArtifactWriterEntrypoint,
  runDaemonAgentCliEntrypoint,
  runDaemonExistingResultEntrypoint,
  runDaemonGoalSourceEntrypoint,
  runDaemonHeartbeatRemoveEntrypoint,
  runDaemonHeartbeatWriteEntrypoint,
  runDaemonInstanceLockEntrypoint,
  runDaemonInstanceUnlockEntrypoint,
  runDaemonLoopIterationEntrypoint,
  runDaemonPlanStateEntrypoint,
  runDaemonPendingDecisionEntrypoint,
  runDaemonPromptLifecycleEntrypoint,
  runDaemonPromptPathEntrypoint,
  runDaemonPromptRouteEntrypoint,
  runDaemonPromptSettleEntrypoint,
  runDaemonQueueFileEntrypoint,
  runDaemonResultArtifactRefEntrypoint,
  runDaemonResultMarkdownEntrypoint,
  runDaemonResultReportAuthoredOutputEntrypoint,
  runDaemonResultReportAuthoringEntrypoint,
  runDaemonResultReportFallbackEntrypoint,
  runDaemonResultReportEntrypoint,
  runDaemonResultStatusEntrypoint,
  runDaemonRoadmapPhaseEntrypoint,
  runDaemonRunFinishedEntrypoint,
  runDaemonShutdownEntrypoint,
  runDaemonStartupBannerEntrypoint,
  runDaemonStartupEntrypoint,
  runDaemonTerminalErrorEntrypoint,
  runDaemonTerminalStatusEntrypoint,
  runDaemonWatcherBackendEntrypoint,
  runDaemonWatcherWaitEntrypoint,
  runAgentRunnerEntrypoint,
  runGoalsProcessDecisionEntrypoint,
  runGoalsPromptProjectionEntrypoint,
  runGoalsQueueEntrypoint,
  runGoalsRoleDocumentProjectionEntrypoint,
  runGoalsRoleSequenceEntrypoint,
  runGoalsSingleGoalDecisionEntrypoint,
  runGoalsTimerDecisionEntrypoint,
  runGoalsTimerFiredDecisionEntrypoint,
  runGoalsTriggerDecisionEntrypoint,
  runGoalsWatcherStartDecisionEntrypoint,
  runGoalsWatcherStopDecisionEntrypoint,
  runGoalsWatchLoopDecisionEntrypoint
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

test("runDaemonPendingDecisionEntrypoint projects daemon queue decisions", () => {
  assert.deepEqual(
    runDaemonPendingDecisionEntrypoint({
      entrypoint: "daemon_pending_decision",
      processed_count: 0,
      ready_prompt_paths: ["/repo/prompts/001-first.md"],
      retry_after_seconds: null
    }),
    {
      entrypoint: "daemon_pending_decision",
      action: "process",
      promptPath: "/repo/prompts/001-first.md",
      queuedPromptNames: [],
      retryAfterSeconds: null,
      reason: "ready_prompt_available"
    }
  );
});

test("runDaemonPromptRouteEntrypoint projects daemon route decisions", () => {
  assert.deepEqual(
    runDaemonPromptRouteEntrypoint({
      entrypoint: "daemon_prompt_route_decision",
      has_agents_config: false,
      request_class: "planning_only",
      has_goal_file: false
    }),
    {
      entrypoint: "daemon_prompt_route_decision",
      action: "planning_pipeline",
      runner: "pipeline",
      requiresAgentCli: true,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: false,
      reason: "planning_only_pipeline"
    }
  );
});

test("runDaemonPromptLifecycleEntrypoint projects prompt lifecycle decisions", () => {
  assert.deepEqual(
    runDaemonPromptLifecycleEntrypoint({
      entrypoint: "daemon_prompt_lifecycle_decision",
      prompt_path: "/repo/prompts/001-first.md",
      result_path: "/repo/results/001-first_RESULT.md",
      prompt_exists: true
    }),
    {
      entrypoint: "daemon_prompt_lifecycle_decision",
      action: "process",
      status: "processing",
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      removeExistingResult: true,
      errorMessage: null,
      reason: "prompt_ready"
    }
  );
});

test("runDaemonPromptPathEntrypoint projects prompt result paths", () => {
  assert.deepEqual(
    runDaemonPromptPathEntrypoint({
      entrypoint: "daemon_prompt_path_decision",
      prompt_path: "/repo/prompts/001-first.md",
      result_path_root: "/repo/results"
    }),
    {
      entrypoint: "daemon_prompt_path_decision",
      promptStem: "001-first",
      resultPath: "/repo/results/001-first_RESULT.md",
      progressLogPath: "/repo/progress/001-first_progress.log",
      reason: "prompt_paths_projected"
    }
  );
});

test("runDaemonPlanStateEntrypoint projects synced PLAN state", () => {
  assert.deepEqual(
    runDaemonPlanStateEntrypoint({
      entrypoint: "daemon_plan_state_decision",
      request_class: "full_workflow",
      task_sync: {
        all_completed: "yes",
        next_pending_task: " Phase 4. Review "
      }
    }),
    {
      entrypoint: "daemon_plan_state_decision",
      planAllCompleted: true,
      nextPendingTask: "Phase 4. Review",
      reason: "task_sync_normalized"
    }
  );
});

test("runDaemonArtifactWriterEntrypoint projects writer bindings", () => {
  assert.deepEqual(
    runDaemonArtifactWriterEntrypoint({
      entrypoint: "daemon_artifact_writer_decision",
      base_dir: "/repo/results",
      logs_dir: "/repo/logs",
      run_id: "daemon:run-1",
      session_id: "session-1"
    }),
    {
      entrypoint: "daemon_artifact_writer_decision",
      baseDir: "/repo/results",
      logsDir: "/repo/logs",
      runId: "daemon:run-1",
      role: "daemon",
      stageName: "daemon",
      sessionId: "session-1",
      reason: "daemon_artifact_writer_bound"
    }
  );
});

test("runDaemonArtifactPersistedEventEntrypoint projects event metadata", () => {
  assert.deepEqual(
    runDaemonArtifactPersistedEventEntrypoint({
      entrypoint: "daemon_artifact_persisted_event_decision",
      artifact_kind: "result_report"
    }),
    {
      entrypoint: "daemon_artifact_persisted_event_decision",
      eventType: "artifact_persisted",
      role: "daemon",
      stage: "daemon",
      status: "persisted",
      artifactKind: "result_report",
      summary: "Persisted the daemon result report.",
      reason: "result_report_artifact_persisted"
    }
  );
});

test("runDaemonResultReportEntrypoint projects report publication decisions", () => {
  assert.deepEqual(
    runDaemonResultReportEntrypoint({
      entrypoint: "daemon_result_report_decision",
      prompt_path: "/repo/prompts/001-first.md",
      result_path: "/repo/results/001-first_RESULT.md",
      prompt_exists: true,
      daemon_run_id: "daemon:run-1",
      latest_run_id: "agent:run-1",
      session_id: "session-1"
    }),
    {
      entrypoint: "daemon_result_report_decision",
      action: "publish",
      writeReport: true,
      removePrompt: true,
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      artifactKind: "result_report",
      artifactLabel: "result_report",
      contentType: "text/markdown",
      runId: "daemon:run-1",
      role: "daemon",
      stageName: "daemon",
      sessionId: "session-1",
      reason: "publish_and_remove_prompt"
    }
  );
});

test("runDaemonResultReportFallbackEntrypoint projects fallback errors", () => {
  assert.deepEqual(
    runDaemonResultReportFallbackEntrypoint({
      entrypoint: "daemon_result_report_fallback_decision",
      prompt_name: "001-first.md",
      existing_error: null,
      cause: "agent unavailable"
    }),
    {
      entrypoint: "daemon_result_report_fallback_decision",
      logMessage: [
        "daemon result report fallback: configured CLI authoring failed for ",
        "001-first.md: agent unavailable"
      ].join(""),
      fallbackNote: [
        "Configured CLI result report authoring failed; ",
        "wrote fallback report instead. Cause: agent unavailable"
      ].join(""),
      combinedError: [
        "Configured CLI result report authoring failed; ",
        "wrote fallback report instead. Cause: agent unavailable"
      ].join(""),
      reason: "result_report_authoring_failed"
    }
  );
});

test("runDaemonResultMarkdownEntrypoint projects fallback markdown", () => {
  assert.deepEqual(
    runDaemonResultMarkdownEntrypoint({
      entrypoint: "daemon_result_markdown_projection",
      generated_at: "2026-06-08T03:00:02+00:00",
      result: {
        prompt_path: "/repo/prompts/001-first.md",
        result_path: "/repo/results/001-first_RESULT.md",
        status: "completed",
        started_at: "2026-06-08T03:00:00+00:00",
        completed_at: null,
        watcher_backend: "polling",
        sort_key: [0, "001-first.md", "001-first.md"],
        session_id: null,
        plan_all_completed: true,
        stage_results: [],
        artifacts: [],
        phase_results: []
      }
    }),
    {
      entrypoint: "daemon_result_markdown_projection",
      markdown: [
        "# Result: 001-first.md",
        "",
        "## Summary",
        "",
        "- Generated at: `2026-06-08T03:00:02+00:00`",
        "- Status: `completed`",
        "- Prompt path: `/repo/prompts/001-first.md`",
        "- Result path: `/repo/results/001-first_RESULT.md`",
        "- Session id: `unknown`",
        "- Watcher backend: `polling`",
        "- Started at: `2026-06-08T03:00:00+00:00`",
        "- Completed at: `not completed`",
        "- Queue sort key: `(0, '001-first.md', '001-first.md')`",
        "- PLAN complete: `yes`"
      ].join("\n") + "\n",
      reason: "result_markdown_projected"
    }
  );
});

test("runDaemonResultReportAuthoringEntrypoint projects CLI requests", () => {
  const result = runDaemonResultReportAuthoringEntrypoint({
    entrypoint: "daemon_result_report_authoring_decision",
    generated_at: "2026-06-08T03:00:02+00:00",
    runtime_paths_text: "Runtime paths summary",
    cli_path: "/usr/bin/codex",
    repo_root: "/repo",
    result: {
      prompt_path: "/repo/prompts/001-first.md",
      result_path: "/repo/results/001-first_RESULT.md",
      status: "completed",
      started_at: "2026-06-08T03:00:00+00:00",
      completed_at: null,
      watcher_backend: "polling",
      sort_key: [0, "001-first.md", "001-first.md"],
      session_id: null
    }
  });

  assert.equal(result.entrypoint, "daemon_result_report_authoring_decision");
  assert.equal(result.action, "run_configured_cli");
  assert.equal(result.cliPath, "/usr/bin/codex");
  assert.equal(result.repoRoot, "/repo");
  assert.equal(result.workdir, "/repo");
  assert.equal(result.runLabel, "result-report-001-first");
  assert.equal(result.generatedAt, "2026-06-08T03:00:02+00:00");
  assert.equal(result.reason, "configured_cli_authoring_requested");
  assert.match(result.promptText ?? "", /# Runtime Paths\n\nRuntime paths summary/);
  assert.match(result.promptText ?? "", /# Structured Facts\n\n# Result: 001-first.md/);
});

test("runDaemonResultReportAuthoredOutputEntrypoint validates output", () => {
  assert.deepEqual(
    runDaemonResultReportAuthoredOutputEntrypoint({
      entrypoint: "daemon_result_report_authored_output_decision",
      stdout_text: [
        "# CLI Authored Result",
        "",
        "- Generated at: `2026-06-08T03:00:02+00:00`"
      ].join("\n"),
      stderr_text: null,
      generated_at: "2026-06-08T03:00:02+00:00",
      prompt_name: "001-first.md"
    }),
    {
      entrypoint: "daemon_result_report_authored_output_decision",
      action: "accept",
      authoredMarkdown: [
        "# CLI Authored Result",
        "",
        "- Generated at: `2026-06-08T03:00:02+00:00`"
      ].join("\n") + "\n",
      errorMessage: null,
      reason: "authored_output_accepted"
    }
  );
});

test("runDaemonResultArtifactRefEntrypoint projects artifact ref decisions", () => {
  assert.deepEqual(
    runDaemonResultArtifactRefEntrypoint({
      entrypoint: "daemon_result_artifact_ref_decision",
      result_path: "/repo/results/001-first_RESULT.md",
      result_exists: true,
      created_at: "2026-06-08T04:00:00+00:00",
      daemon_run_id: "",
      latest_run_id: "agent:run-1",
      session_id: "session-1"
    }),
    {
      entrypoint: "daemon_result_artifact_ref_decision",
      action: "reference",
      artifactRef: {
        kind: "result_report",
        path: "/repo/results/001-first_RESULT.md",
        label: "result_report",
        contentType: "text/markdown",
        createdAt: "2026-06-08T04:00:00+00:00",
        runId: "agent:run-1",
        role: "daemon",
        stageName: "daemon",
        sessionId: "session-1"
      },
      reason: "result_report_referenced"
    }
  );
});

test("runDaemonRunFinishedEntrypoint projects run-finished metadata", () => {
  assert.deepEqual(
    runDaemonRunFinishedEntrypoint({
      entrypoint: "daemon_run_finished_decision",
      attempts_completed: 2,
      retries_used: 1,
      supervisor_verdict: " approved ",
      outcome: "completed",
      error: ""
    }),
    {
      entrypoint: "daemon_run_finished_decision",
      source: "daemon_runner",
      runEntrypoint: "DaemonRunner._process_prompt",
      attemptsCompleted: 2,
      retriesUsed: 1,
      supervisorVerdict: "approved",
      outcome: "completed",
      error: null,
      reason: "daemon_run_finished"
    }
  );
});

test("runDaemonRoadmapPhaseEntrypoint projects phase decisions", () => {
  assert.deepEqual(
    runDaemonRoadmapPhaseEntrypoint({
      entrypoint: "daemon_roadmap_phase_decision",
      active_phase_ids: ["", "phase_6"]
    }),
    {
      entrypoint: "daemon_roadmap_phase_decision",
      expectedRoadmapPhaseId: "phase_6",
      reason: "active_phase_selected"
    }
  );
});

test("runDaemonGoalSourceEntrypoint projects goal-source metadata", () => {
  assert.deepEqual(
    runDaemonGoalSourceEntrypoint({
      entrypoint: "daemon_goal_source_decision",
      prompt_text: [
        "<!-- dormammu:goal_source=/repo/goals/ship-it.md -->",
        "",
        "# Goal"
      ].join("\n")
    }),
    {
      entrypoint: "daemon_goal_source_decision",
      goalSourcePath: "/repo/goals/ship-it.md",
      reason: "goal_source_found"
    }
  );
});

test("runDaemonAgentCliEntrypoint projects active agent CLI decisions", () => {
  assert.deepEqual(
    runDaemonAgentCliEntrypoint({
      entrypoint: "daemon_agent_cli_decision",
      active_agent_cli: "/usr/local/bin/codex"
    }),
    {
      entrypoint: "daemon_agent_cli_decision",
      action: "use",
      agentCli: "/usr/local/bin/codex",
      errorMessage: null,
      reason: "active_agent_cli_configured"
    }
  );
});

test("runDaemonTerminalErrorEntrypoint projects terminal errors", () => {
  assert.deepEqual(
    runDaemonTerminalErrorEntrypoint({
      entrypoint: "daemon_terminal_error_decision",
      status: "failed",
      next_pending_task: "Phase 3. Fix"
    }),
    {
      entrypoint: "daemon_terminal_error_decision",
      status: "failed",
      nextPendingTask: "Phase 3. Fix",
      message: [
        "Loop retry budget was exhausted before PLAN.md completed.",
        " Next pending PLAN task: Phase 3. Fix."
      ].join(""),
      reason: "retry_budget_exhausted"
    }
  );
});

test("runDaemonTerminalStatusEntrypoint projects terminal status reconciliation", () => {
  assert.deepEqual(
    runDaemonTerminalStatusEntrypoint({
      entrypoint: "daemon_terminal_status_decision",
      status: "completed",
      plan_all_completed: false,
      has_clean_terminal_stage_evidence: false,
      next_pending_task: null
    }),
    {
      entrypoint: "daemon_terminal_status_decision",
      status: "failed",
      error: "Loop returned completed but session PLAN.md is not fully complete.",
      preserveCompleted: false,
      reason: "completed_plan_incomplete"
    }
  );
});

test("runDaemonExistingResultEntrypoint projects stale result removal", () => {
  assert.deepEqual(
    runDaemonExistingResultEntrypoint({
      entrypoint: "daemon_existing_result_decision",
      prompt_path: "/repo/prompts/001-first.md",
      result_path: "/repo/results/001-first_RESULT.md",
      result_exists: true,
      existing_result_status: "completed"
    }),
    {
      entrypoint: "daemon_existing_result_decision",
      action: "remove",
      removeExistingResult: true,
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      existingResultStatus: "completed",
      reason: "completed_result_reprocess"
    }
  );
});

test("runDaemonResultStatusEntrypoint projects result status parsing", () => {
  assert.deepEqual(
    runDaemonResultStatusEntrypoint({
      entrypoint: "daemon_result_status_decision",
      result_text: "# Result\n\n- Status: `failed`\n"
    }),
    {
      entrypoint: "daemon_result_status_decision",
      status: "failed",
      reason: "status_line_found"
    }
  );
});

test("runDaemonPromptSettleEntrypoint projects settle-window decisions", () => {
  assert.deepEqual(
    runDaemonPromptSettleEntrypoint({
      entrypoint: "daemon_prompt_settle_decision",
      prompt_path: "/repo/prompts/001-first.md",
      settle_seconds: 3,
      age_seconds: 1.5
    }),
    {
      entrypoint: "daemon_prompt_settle_decision",
      action: "defer",
      promptPath: "/repo/prompts/001-first.md",
      retryAfterSeconds: 1.5,
      reason: "settle_window_pending"
    }
  );
});

test("runDaemonQueueFileEntrypoint projects queue file skip decisions", () => {
  assert.deepEqual(
    runDaemonQueueFileEntrypoint({
      entrypoint: "daemon_queue_file_decision",
      prompt_path: "/repo/prompts/readme.txt",
      in_progress: false,
      prompt_candidate: false
    }),
    {
      entrypoint: "daemon_queue_file_decision",
      action: "skip",
      promptPath: "/repo/prompts/readme.txt",
      reason: "not_prompt_candidate"
    }
  );
});

test("runDaemonLoopIterationEntrypoint projects daemon loop decisions", () => {
  assert.deepEqual(
    runDaemonLoopIterationEntrypoint({
      entrypoint: "daemon_loop_iteration_decision",
      processed_count: 0,
      in_progress_count: 0,
      shutdown_requested: false
    }),
    {
      entrypoint: "daemon_loop_iteration_decision",
      action: "wait",
      heartbeatStatus: "idle",
      waitForChanges: true,
      reason: "no_prompt_processed"
    }
  );
});

test("runDaemonStartupEntrypoint projects daemon startup decisions", () => {
  assert.deepEqual(
    runDaemonStartupEntrypoint({
      entrypoint: "daemon_startup_decision",
      goals_scheduler_configured: true,
      autonomous_scheduler_configured: false
    }),
    {
      entrypoint: "daemon_startup_decision",
      action: "start",
      initialHeartbeatStatus: "idle",
      startGoalsScheduler: true,
      triggerGoalsScheduler: true,
      startAutonomousScheduler: false,
      triggerAutonomousScheduler: false,
      reason: "daemon_startup"
    }
  );
});

test("runDaemonStartupBannerEntrypoint projects startup banner decisions", () => {
  assert.deepEqual(
    runDaemonStartupBannerEntrypoint({
      entrypoint: "daemon_startup_banner_decision",
      repo_root: "/repo",
      config_path: "/repo/daemonize.json",
      prompt_path: "/repo/prompts",
      result_path: "/repo/results",
      watcher_backend: "polling",
      requested_watcher_backend: "polling",
      poll_interval_seconds: 15,
      settle_seconds: 4,
      ignore_hidden_files: false,
      allowed_extensions: [".md"],
      goals_path: null,
      goals_interval_minutes: null,
      autonomous_enabled: false,
      autonomous_interval_minutes: null,
      autonomous_focus: null,
      autonomous_max_queued_tasks: null
    }).lines.at(-2),
    "goals: disabled"
  );
});

test("runDaemonShutdownEntrypoint projects daemon shutdown decisions", () => {
  assert.deepEqual(
    runDaemonShutdownEntrypoint({
      entrypoint: "daemon_shutdown_decision",
      goals_scheduler_configured: false,
      autonomous_scheduler_configured: true,
      progress_log_active: true
    }),
    {
      entrypoint: "daemon_shutdown_decision",
      action: "shutdown",
      stopGoalsScheduler: false,
      stopAutonomousScheduler: true,
      closeWatcher: true,
      removeHeartbeat: true,
      closeProgressLog: true,
      reason: "daemon_shutdown"
    }
  );
});

test("runDaemonInstanceLockEntrypoint projects daemon lock decisions", () => {
  assert.deepEqual(
    runDaemonInstanceLockEntrypoint({
      entrypoint: "daemon_instance_lock_decision",
      fcntl_available: true,
      lock_acquired: false,
      prompt_path: "/repo/prompts",
      existing_pid: "4321"
    }),
    {
      entrypoint: "daemon_instance_lock_decision",
      action: "reject",
      writePidFile: false,
      errorMessage: [
        "Another dormammu daemon is already running against "
          + "/repo/prompts (existing daemon PID: 4321).",
        "Stop it first or use a different prompt_path."
      ].join("\n"),
      reason: "instance_lock_busy"
    }
  );
});

test("runDaemonInstanceUnlockEntrypoint projects daemon unlock decisions", () => {
  assert.deepEqual(
    runDaemonInstanceUnlockEntrypoint({
      entrypoint: "daemon_instance_unlock_decision",
      fcntl_available: true,
      lock_held: true
    }),
    {
      entrypoint: "daemon_instance_unlock_decision",
      action: "release",
      unlockFcntl: true,
      closeLockFile: true,
      clearPidLockFile: true,
      removePidFile: true,
      reason: "instance_lock_release"
    }
  );
});

test("runDaemonHeartbeatWriteEntrypoint projects heartbeat payloads", () => {
  assert.deepEqual(
    runDaemonHeartbeatWriteEntrypoint({
      entrypoint: "daemon_heartbeat_write_decision",
      heartbeat_path_configured: true,
      pid: 42,
      status: "busy",
      timestamp: "2026-06-08T03:10:00+00:00"
    }),
    {
      entrypoint: "daemon_heartbeat_write_decision",
      action: "write",
      ensureParent: true,
      heartbeatPayload: {
        pid: 42,
        status: "busy",
        ts: "2026-06-08T03:10:00+00:00"
      },
      reason: "heartbeat_write"
    }
  );
});

test("runDaemonHeartbeatRemoveEntrypoint projects heartbeat removal", () => {
  assert.deepEqual(
    runDaemonHeartbeatRemoveEntrypoint({
      entrypoint: "daemon_heartbeat_remove_decision",
      heartbeat_path_configured: true
    }),
    {
      entrypoint: "daemon_heartbeat_remove_decision",
      action: "remove",
      removeHeartbeat: true,
      reason: "heartbeat_remove"
    }
  );
});

test("runDaemonWatcherBackendEntrypoint projects watcher backend selection", () => {
  assert.deepEqual(
    runDaemonWatcherBackendEntrypoint({
      entrypoint: "daemon_watcher_backend_decision",
      requested_backend: "auto",
      inotify_available: false
    }),
    {
      entrypoint: "daemon_watcher_backend_decision",
      action: "use",
      backend: "polling",
      errorMessage: null,
      reason: "auto_falls_back_to_polling"
    }
  );
});

test("runDaemonWatcherWaitEntrypoint projects watcher wait decisions", () => {
  assert.deepEqual(
    runDaemonWatcherWaitEntrypoint({
      entrypoint: "daemon_watcher_wait_decision",
      wait_requested: true,
      shutdown_requested: false,
      watcher_backend: "polling"
    }),
    {
      entrypoint: "daemon_watcher_wait_decision",
      action: "wait",
      waitForChanges: true,
      watcherBackend: "polling",
      reason: "wait_requested"
    }
  );
});

test("runGoalsRoleDocumentProjectionEntrypoint projects role documents", () => {
  assert.deepEqual(
    runGoalsRoleDocumentProjectionEntrypoint({
      entrypoint: "goals_role_document_projection",
      logs_dir: "/repo/.dev/logs",
      date_text: "20260412",
      role: "planner",
      stem: "ship-it",
      output: "Plan output"
    }),
    {
      entrypoint: "goals_role_document_projection",
      filename: "20260412_planner_ship-it.md",
      path: "/repo/.dev/logs/20260412_planner_ship-it.md",
      content: "# Planner \u2014 ship-it\n\nPlan output"
    }
  );
});

test("runGoalsRoleSequenceEntrypoint projects the next goals role step", () => {
  const result = runGoalsRoleSequenceEntrypoint({
    entrypoint: "goals_role_sequence",
    goal_text: "Ship it",
    analysis_text: "Analysis output",
    roles: {
      analyzer: { cli: "analyzer-cli" },
      planner: { cli: "planner-cli", model: "careful" },
      designer: { cli: "designer-cli" }
    }
  });

  assert.equal(result.entrypoint, "goals_role_sequence");
  assert.equal(result.next_step?.role, "planner");
  assert.equal(result.next_step?.cli, "planner-cli");
  assert.equal(result.next_step?.model, "careful");
  assert.ok(
    result.next_step?.prompt.includes(
      "# Requirements Analysis\n\nAnalysis output"
    )
  );
});

test("runGoalsTimerDecisionEntrypoint projects timer decisions", () => {
  assert.deepEqual(
    runGoalsTimerDecisionEntrypoint({
      entrypoint: "goals_timer_decision",
      has_goal_files: true,
      timer_active: false,
      interval_minutes: 3
    }),
    {
      entrypoint: "goals_timer_decision",
      action: "schedule",
      intervalSeconds: 180,
      reason: "goal_files_present_without_active_timer"
    }
  );
});

test("runGoalsTriggerDecisionEntrypoint projects immediate run decisions", () => {
  assert.deepEqual(
    runGoalsTriggerDecisionEntrypoint({
      entrypoint: "goals_trigger_decision",
      stop_requested: false,
      has_goal_files: true
    }),
    {
      entrypoint: "goals_trigger_decision",
      action: "process",
      cancelTimerBeforeProcess: true,
      syncTimerAfterProcess: true,
      reason: "goal_files_present"
    }
  );
});

test("runGoalsProcessDecisionEntrypoint projects batch decisions", () => {
  assert.deepEqual(
    runGoalsProcessDecisionEntrypoint({
      entrypoint: "goals_process_decision",
      stop_requested: false,
      goal_file_count: 2
    }),
    {
      entrypoint: "goals_process_decision",
      action: "process",
      goalFileCount: 2,
      reason: "goal_files_present"
    }
  );
});

test("runGoalsTimerFiredDecisionEntrypoint projects callback decisions", () => {
  assert.deepEqual(
    runGoalsTimerFiredDecisionEntrypoint({
      entrypoint: "goals_timer_fired_decision",
      stop_requested: false
    }),
    {
      entrypoint: "goals_timer_fired_decision",
      action: "process",
      clearTimerBeforeProcess: true,
      syncTimerAfterProcess: true,
      reason: "timer_fired"
    }
  );
});

test("runGoalsSingleGoalDecisionEntrypoint projects prompt write decisions", () => {
  assert.deepEqual(
    runGoalsSingleGoalDecisionEntrypoint({
      entrypoint: "goals_single_goal_decision",
      prompt_exists: true
    }),
    {
      entrypoint: "goals_single_goal_decision",
      action: "skip",
      reason: "queued_prompt_exists"
    }
  );
});

test("runGoalsWatcherStartDecisionEntrypoint projects start decisions", () => {
  assert.deepEqual(
    runGoalsWatcherStartDecisionEntrypoint({
      entrypoint: "goals_watcher_start_decision",
      watcher_active: false
    }),
    {
      entrypoint: "goals_watcher_start_decision",
      action: "start",
      threadName: "dormammu-goals-watcher",
      daemon: true,
      reason: "watcher_start_requested"
    }
  );
});

test("runGoalsWatcherStopDecisionEntrypoint projects stop decisions", () => {
  assert.deepEqual(
    runGoalsWatcherStopDecisionEntrypoint({
      entrypoint: "goals_watcher_stop_decision",
      timer_active: false
    }),
    {
      entrypoint: "goals_watcher_stop_decision",
      action: "stop",
      setStopEvent: true,
      cancelTimer: true,
      reason: "stop_requested_without_active_timer"
    }
  );
});

test("runGoalsWatchLoopDecisionEntrypoint projects loop decisions", () => {
  assert.deepEqual(
    runGoalsWatchLoopDecisionEntrypoint({
      entrypoint: "goals_watch_loop_decision",
      stop_requested: false,
      poll_seconds: 30
    }),
    {
      entrypoint: "goals_watch_loop_decision",
      action: "sync",
      waitSeconds: 30,
      reason: "watcher_poll"
    }
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
