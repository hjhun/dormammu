import assert from "node:assert/strict";
import test from "node:test";

import {
  daemonArtifactPersistedEventDecision,
  daemonArtifactWriterDecision,
  daemonAgentCliDecision,
  daemonExistingResultDecision,
  daemonGoalSourceDecision,
  daemonHeartbeatRemoveDecision,
  daemonHeartbeatWriteDecision,
  daemonInstanceLockDecision,
  daemonInstanceUnlockDecision,
  daemonLoopIterationDecision,
  daemonPlanStateDecision,
  daemonPendingDecision,
  daemonPromptCompletionLineDecision,
  daemonPromptInterruptionDecision,
  daemonPromptLifecycleDecision,
  daemonPromptPathDecision,
  daemonPromptProcessingMetadataDecision,
  daemonRequestClassDecision,
  daemonPromptRouteDecision,
  daemonPromptSessionDecision,
  daemonPromptSettleDecision,
  daemonPromptSummaryDecision,
  daemonQueueFileDecision,
  daemonResultArtifactRefDecision,
  daemonResultMarkdownProjection,
  daemonResultReportAuthoredOutputDecision,
  daemonResultReportAuthoringDecision,
  daemonResultReportFallbackDecision,
  daemonResultReportDecision,
  daemonResultStatusDecision,
  daemonRoadmapPhaseDecision,
  daemonRunLifecycleEventDecision,
  daemonRunFinishedDecision,
  daemonShutdownDecision,
  daemonStartupBannerDecision,
  daemonStartupDecision,
  daemonSupervisorHandoffDecision,
  daemonTerminalErrorDecision,
  daemonTerminalStatusDecision,
  daemonWatcherBackendDecision,
  daemonWatcherWaitDecision
} from "./runner.js";

test("daemonPendingDecision processes the first ready prompt", () => {
  assert.deepEqual(
    daemonPendingDecision({
      processedCount: 0,
      readyPromptPaths: [
        "/repo/prompts/001-first.md",
        "/repo/prompts/002-second.md"
      ],
      retryAfterSeconds: null
    }),
    {
      action: "process",
      promptPath: "/repo/prompts/001-first.md",
      queuedPromptNames: ["002-second.md"],
      retryAfterSeconds: null,
      reason: "ready_prompt_available"
    }
  );
});

test("daemonPendingDecision waits for the settle window before first work", () => {
  assert.deepEqual(
    daemonPendingDecision({
      processedCount: 0,
      readyPromptPaths: [],
      retryAfterSeconds: 1.5
    }),
    {
      action: "wait",
      promptPath: null,
      queuedPromptNames: [],
      retryAfterSeconds: 1.5,
      reason: "settle_window_pending"
    }
  );
});

test("daemonPendingDecision idles when no prompt is ready after work", () => {
  assert.deepEqual(
    daemonPendingDecision({
      processedCount: 1,
      readyPromptPaths: [],
      retryAfterSeconds: 1.5
    }),
    {
      action: "idle",
      promptPath: null,
      queuedPromptNames: [],
      retryAfterSeconds: null,
      reason: "no_ready_prompts"
    }
  );
});

test("daemonRequestClassDecision prefers workflow state intake", () => {
  assert.deepEqual(
    daemonRequestClassDecision({
      promptText: "implement a feature",
      workflowState: {
        intake: {
          request_class: "planning_only",
          confidence: 0.9
        }
      }
    }),
    {
      requestClass: "planning_only",
      confidence: 0.9,
      source: "workflow_state",
      reason: "workflow_state_intake_request_class"
    }
  );
});

test("daemonRequestClassDecision promotes low-confidence direct responses", () => {
  assert.deepEqual(
    daemonRequestClassDecision({
      promptText: "ambiguous task",
      workflowState: {
        intake: {
          request_class: "direct_response",
          confidence: 0.4
        }
      }
    }),
    {
      requestClass: "full_workflow",
      confidence: 0.4,
      source: "workflow_state",
      reason: "workflow_state_direct_response_low_confidence_promoted"
    }
  );

  assert.deepEqual(
    daemonRequestClassDecision({
      promptText: "no obvious signal",
      workflowState: null
    }),
    {
      requestClass: "full_workflow",
      confidence: 0.4,
      source: "classifier",
      reason: "classifier_direct_response_low_confidence_promoted"
    }
  );
});

test("daemonRequestClassDecision classifies directives and broad edits", () => {
  assert.deepEqual(
    daemonRequestClassDecision({
      promptText: "DORMAMMU_REQUEST_CLASS: light_edit\n\nUpdate README.md",
      workflowState: null
    }),
    {
      requestClass: "light_edit",
      confidence: 1,
      source: "classifier",
      reason: "classifier_request_class"
    }
  );

  assert.deepEqual(
    daemonRequestClassDecision({
      promptText: "Implement API tests across service.py model.py cli.py",
      workflowState: null
    }),
    {
      requestClass: "full_workflow",
      confidence: 1,
      source: "classifier",
      reason: "classifier_request_class"
    }
  );
});

test("daemonPromptRouteDecision uses configured pipeline when agents exist", () => {
  assert.deepEqual(
    daemonPromptRouteDecision({
      hasAgentsConfig: true,
      requestClass: "full_workflow",
      hasGoalFile: true
    }),
    {
      action: "configured_pipeline",
      runner: "pipeline",
      requiresAgentCli: false,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: true,
      reason: "agents_config_present"
    }
  );
});

test("daemonPromptRouteDecision maps direct and planning requests to pipeline", () => {
  assert.deepEqual(
    daemonPromptRouteDecision({
      hasAgentsConfig: false,
      requestClass: "direct_response",
      hasGoalFile: false
    }).action,
    "direct_pipeline"
  );
  assert.deepEqual(
    daemonPromptRouteDecision({
      hasAgentsConfig: false,
      requestClass: "planning_only",
      hasGoalFile: false
    }).action,
    "planning_pipeline"
  );
});

test("daemonPromptRouteDecision maps implementation requests to prelude loop", () => {
  assert.deepEqual(
    daemonPromptRouteDecision({
      hasAgentsConfig: false,
      requestClass: "full_workflow",
      hasGoalFile: true
    }),
    {
      action: "prelude_then_loop",
      runner: "loop",
      requiresAgentCli: true,
      runRefineAndPlanPrelude: true,
      enablePlanEvaluator: true,
      useGoalsEvaluatorConfig: false,
      reason: "full_workflow_requires_supervised_loop"
    }
  );
});

test("daemonPromptLifecycleDecision processes existing prompt files", () => {
  assert.deepEqual(
    daemonPromptLifecycleDecision({
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      promptExists: true
    }),
    {
      action: "process",
      status: "processing",
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      removeExistingResult: true,
      errorMessage: null,
      logMessage: null,
      reason: "prompt_ready"
    }
  );
});

test("daemonPromptLifecycleDecision skips missing prompt files", () => {
  assert.deepEqual(
    daemonPromptLifecycleDecision({
      promptPath: "/repo/prompts/001-missing.md",
      resultPath: "/repo/results/001-missing_RESULT.md",
      promptExists: false
    }),
    {
      action: "skip",
      status: "skipped",
      promptPath: "/repo/prompts/001-missing.md",
      resultPath: "/repo/results/001-missing_RESULT.md",
      removeExistingResult: false,
      errorMessage: "Prompt file was deleted before processing.",
      logMessage: "daemon prompt 001-missing.md: prompt file was deleted before processing; skipping",
      reason: "prompt_missing"
    }
  );
});

test("daemonPromptPathDecision projects result and progress paths", () => {
  assert.deepEqual(
    daemonPromptPathDecision({
      promptPath: "/repo/prompts/001-first.prompt.md",
      resultPathRoot: "/repo/results"
    }),
    {
      promptStem: "001-first.prompt",
      resultPath: "/repo/results/001-first.prompt_RESULT.md",
      progressLogPath: "/repo/progress/001-first.prompt_progress.log",
      reason: "prompt_paths_projected"
    }
  );
});

test("daemonPromptSessionDecision projects goal and roadmap phase", () => {
  assert.deepEqual(
    daemonPromptSessionDecision({
      promptName: "001-phase-6.md",
      promptText: "# Phase 6 release alignment\n\nShip packaging checks."
    }),
    {
      goal: "Phase 6 release alignment",
      activeRoadmapPhaseIds: ["phase_6"],
      reason: "daemon_prompt_session_projected"
    }
  );
});

test("daemonPromptProcessingMetadataDecision projects sort key and logs", () => {
  assert.deepEqual(
    daemonPromptProcessingMetadataDecision({
      promptName: "001-first.md",
      promptText: "# Ship the feature\n\nBody.",
      watcherBackend: "polling",
      resultPath: "/repo/results/001-first_RESULT.md"
    }),
    {
      sortKey: [0, 1, "001-first.md"],
      promptSummary: "Ship the feature",
      detectedLogMessage:
        "daemon prompt detected: 001-first.md " +
        "(sort_key=(0, 1, '001-first.md'), watcher=polling, result=001-first_RESULT.md)",
      summaryLogMessage: "daemon prompt summary: Ship the feature",
      reason: "daemon_prompt_processing_metadata_projected"
    }
  );
});

test("daemonPlanStateDecision normalizes direct responses and task sync", () => {
  assert.deepEqual(
    daemonPlanStateDecision({
      requestClass: "direct_response",
      taskSync: null
    }),
    {
      planAllCompleted: true,
      nextPendingTask: null,
      reason: "direct_response_plan_complete"
    }
  );
  assert.deepEqual(
    daemonPlanStateDecision({
      requestClass: "full_workflow",
      taskSync: {
        all_completed: 0,
        next_pending_task: " Phase 2. Validate "
      }
    }),
    {
      planAllCompleted: false,
      nextPendingTask: "Phase 2. Validate",
      reason: "task_sync_normalized"
    }
  );
  assert.deepEqual(
    daemonPlanStateDecision({
      requestClass: "full_workflow",
      taskSync: null
    }),
    {
      planAllCompleted: null,
      nextPendingTask: null,
      reason: "task_sync_missing"
    }
  );
});

test("daemonArtifactWriterDecision preserves daemon writer bindings", () => {
  assert.deepEqual(
    daemonArtifactWriterDecision({
      baseDir: "/repo/results",
      logsDir: "/repo/logs",
      runId: "daemon:run-1",
      sessionId: "session-1"
    }),
    {
      baseDir: "/repo/results",
      logsDir: "/repo/logs",
      runId: "daemon:run-1",
      role: "daemon",
      stageName: "daemon",
      sessionId: "session-1",
      reason: "daemon_artifact_writer_bound"
    }
  );
  assert.deepEqual(
    daemonArtifactWriterDecision({
      baseDir: "/repo/results",
      logsDir: null,
      runId: null,
      sessionId: null
    }),
    {
      baseDir: "/repo/results",
      logsDir: null,
      runId: null,
      role: "daemon",
      stageName: "daemon",
      sessionId: null,
      reason: "daemon_artifact_writer_bound"
    }
  );
});

test("daemonArtifactPersistedEventDecision projects lifecycle event metadata", () => {
  assert.deepEqual(
    daemonArtifactPersistedEventDecision({
      artifactKind: "input_prompt"
    }),
    {
      eventType: "artifact_persisted",
      role: "daemon",
      stage: "daemon",
      status: "persisted",
      artifactKind: "input_prompt",
      summary: "Persisted the daemon prompt into the active session workspace.",
      reason: "input_prompt_artifact_persisted"
    }
  );
  assert.deepEqual(
    daemonArtifactPersistedEventDecision({
      artifactKind: "result_report"
    }),
    {
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

test("daemonSupervisorHandoffDecision projects prelude handoff metadata", () => {
  assert.deepEqual(
    daemonSupervisorHandoffDecision({
      fromRole: "planner",
      toRole: "developer",
      attempt: 1
    }),
    {
      eventType: "supervisor.handoff",
      role: "planner",
      stage: "developer",
      status: "handoff",
      payload: {
        fromRole: "planner",
        toRole: "developer",
        reason:
          "Mandatory refine/plan prelude completed; handing off to the supervised developer loop.",
        attempt: 1
      },
      reason: "daemon_supervisor_prelude_handoff"
    }
  );
});

test("daemonRunLifecycleEventDecision projects requested and started metadata", () => {
  assert.deepEqual(
    daemonRunLifecycleEventDecision({
      eventKind: "requested",
      promptSummary: "Build the daemon bridge"
    }),
    {
      eventType: "run.requested",
      role: "daemon",
      stage: "daemon",
      status: "requested",
      payload: {
        source: "daemon_runner",
        entrypoint: "DaemonRunner._process_prompt",
        trigger: "daemon_queue",
        promptSummary: "Build the daemon bridge"
      },
      reason: "daemon_run_requested"
    }
  );
  assert.deepEqual(
    daemonRunLifecycleEventDecision({
      eventKind: "started",
      promptSummary: "  "
    }),
    {
      eventType: "run.started",
      role: "daemon",
      stage: "daemon",
      status: "started",
      payload: {
        source: "daemon_runner",
        entrypoint: "DaemonRunner._process_prompt",
        trigger: "daemon_queue",
        promptSummary: null
      },
      reason: "daemon_run_started"
    }
  );
});

test("daemonPromptSummaryDecision projects first-line prompt summaries", () => {
  assert.deepEqual(
    daemonPromptSummaryDecision({
      promptText: "  Build the daemon bridge  \n\nDetails"
    }),
    {
      promptSummary: "Build the daemon bridge",
      reason: "daemon_prompt_summary_projected"
    }
  );
  assert.deepEqual(
    daemonPromptSummaryDecision({
      promptText: "\n\nDetails"
    }),
    {
      promptSummary: null,
      reason: "daemon_prompt_summary_projected"
    }
  );
});

test("daemonResultReportDecision publishes report metadata", () => {
  assert.deepEqual(
    daemonResultReportDecision({
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      promptExists: true,
      daemonRunId: "daemon:run-1",
      latestRunId: "agent:run-1",
      sessionId: "session-1"
    }),
    {
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

test("daemonResultReportDecision falls back to latest run metadata", () => {
  assert.deepEqual(
    daemonResultReportDecision({
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      promptExists: false,
      daemonRunId: "",
      latestRunId: "agent:run-1",
      sessionId: ""
    }).runId,
    "agent:run-1"
  );
});

test("daemonResultReportFallbackDecision projects fallback errors", () => {
  assert.deepEqual(
    daemonResultReportFallbackDecision({
      promptName: "001-first.md",
      existingError: "Loop failed",
      cause: "agent unavailable"
    }),
    {
      logMessage: [
        "daemon result report fallback: configured CLI authoring failed for ",
        "001-first.md: agent unavailable"
      ].join(""),
      fallbackNote: [
        "Configured CLI result report authoring failed; ",
        "wrote fallback report instead. Cause: agent unavailable"
      ].join(""),
      combinedError: [
        "Loop failed",
        "",
        [
          "Configured CLI result report authoring failed; ",
          "wrote fallback report instead. Cause: agent unavailable"
        ].join("")
      ].join("\n"),
      reason: "result_report_authoring_failed"
    }
  );
});

test("daemonResultMarkdownProjection renders deterministic fallback reports", () => {
  assert.deepEqual(
    daemonResultMarkdownProjection({
      generatedAt: "2026-06-08T03:00:02+00:00",
      result: {
        prompt_path: "/repo/prompts/001-first.md",
        result_path: "/repo/results/001-first_RESULT.md",
        status: "failed",
        started_at: "2026-06-08T03:00:00+00:00",
        completed_at: "2026-06-08T03:00:01+00:00",
        watcher_backend: "polling",
        sort_key: [0, "001-first.md", "001-first.md"],
        session_id: "session-123",
        plan_all_completed: false,
        next_pending_task: "Phase 4",
        attempts_completed: 2,
        latest_run_id: "agent:run-1",
        supervisor_verdict: "needs_work",
        summary: "Loop stopped after reviewer feedback.",
        supervisor_report_path: "/repo/.dev/supervisor_report.md",
        continuation_prompt_path: "/repo/.dev/continuation_prompt.txt",
        error: "Loop failed",
        stage_results: [
          {
            role: "reviewer",
            stage_name: "review",
            status: "failed",
            verdict: "needs_work",
            report_path: "/repo/.dev/logs/reviewer.md",
            summary: "Needs follow-up.",
            retry: {
              attempt: 2,
              retries_used: 1,
              max_retries: 3,
              max_iterations: null
            },
            timing: {
              started_at: "2026-06-08T03:00:00+00:00",
              completed_at: "2026-06-08T03:00:01+00:00",
              duration_seconds: 1.5
            }
          }
        ],
        artifacts: [
          {
            kind: "supervisor_report",
            path: "/repo/.dev/supervisor_report.md",
            label: "supervisor_report"
          }
        ],
        phase_results: [
          {
            phase_name: "Develop",
            exit_code: 1,
            cli_path: "/usr/bin/codex",
            run_id: "agent:run-1",
            prompt_path: "/repo/.dev/logs/run.prompt.txt",
            stdout_path: "/repo/.dev/logs/run.stdout.log",
            stderr_path: "/repo/.dev/logs/run.stderr.log",
            metadata_path: "/repo/.dev/logs/run.meta.json",
            error: "agent failed"
          }
        ]
      }
    }),
    {
      markdown: [
        "# Result: 001-first.md",
        "",
        "## Summary",
        "",
        "- Generated at: `2026-06-08T03:00:02+00:00`",
        "- Status: `failed`",
        "- Prompt path: `/repo/prompts/001-first.md`",
        "- Result path: `/repo/results/001-first_RESULT.md`",
        "- Session id: `session-123`",
        "- Watcher backend: `polling`",
        "- Started at: `2026-06-08T03:00:00+00:00`",
        "- Completed at: `2026-06-08T03:00:01+00:00`",
        "- Queue sort key: `(0, '001-first.md', '001-first.md')`",
        "- PLAN complete: `no`",
        "- Next pending PLAN task: `Phase 4`",
        "- Attempts completed: `2`",
        "- Latest run id: `agent:run-1`",
        "- Supervisor verdict: `needs_work`",
        "- Run summary: Loop stopped after reviewer feedback.",
        "- Supervisor report: `/repo/.dev/supervisor_report.md`",
        "- Continuation prompt: `/repo/.dev/continuation_prompt.txt`",
        "",
        "## Error",
        "",
        "Loop failed",
        "",
        "## Stage Results",
        "",
        "### review",
        "",
        "- Role: `reviewer`",
        "- Status: `failed`",
        "- Verdict: `needs_work`",
        "- Report: `/repo/.dev/logs/reviewer.md`",
        "- Summary: Needs follow-up.",
        "- Retry: `attempt=2, retries_used=1, max_retries=3, max_iterations=None`",
        [
          "- Timing: `started_at=2026-06-08T03:00:00+00:00, ",
          "completed_at=2026-06-08T03:00:01+00:00, ",
          "duration_seconds=1.5`"
        ].join(""),
        "",
        "",
        "## Artifacts",
        "",
        "- `supervisor_report`: `/repo/.dev/supervisor_report.md` (supervisor_report)",
        "",
        "## Phases",
        "",
        "### Develop",
        "",
        "- Exit code: `1`",
        "- CLI: `/usr/bin/codex`",
        "- Run id: `agent:run-1`",
        "- Prompt artifact: `/repo/.dev/logs/run.prompt.txt`",
        "- Stdout artifact: `/repo/.dev/logs/run.stdout.log`",
        "- Stderr artifact: `/repo/.dev/logs/run.stderr.log`",
        "- Metadata artifact: `/repo/.dev/logs/run.meta.json`",
        "- Error: agent failed"
      ].join("\n") + "\n",
      reason: "result_markdown_projected"
    }
  );
});

test("daemonResultReportAuthoringDecision projects configured CLI requests", () => {
  const decision = daemonResultReportAuthoringDecision({
    generatedAt: "2026-06-08T03:00:02+00:00",
    runtimePathsText: "Runtime paths summary",
    cliPath: "/usr/bin/codex",
    repoRoot: "/repo",
    result: {
      prompt_path: "/repo/prompts/001-first.md",
      result_path: "/repo/results/001-first_RESULT.md",
      status: "completed",
      started_at: "2026-06-08T03:00:00+00:00",
      completed_at: "2026-06-08T03:00:01+00:00",
      watcher_backend: "polling",
      sort_key: [0, "001-first.md", "001-first.md"],
      session_id: "session-123",
      stage_results: [],
      artifacts: [],
      phase_results: []
    }
  });

  assert.equal(decision.action, "run_configured_cli");
  assert.equal(decision.cliPath, "/usr/bin/codex");
  assert.equal(decision.repoRoot, "/repo");
  assert.equal(decision.workdir, "/repo");
  assert.equal(decision.runLabel, "result-report-001-first");
  assert.equal(decision.generatedAt, "2026-06-08T03:00:02+00:00");
  assert.equal(decision.reason, "configured_cli_authoring_requested");
  assert.equal(
    decision.promptText,
    [
      "Write a deterministic operator-facing Markdown result report.",
      "",
      "Requirements:",
      "- Preserve the exact factual content provided below.",
      "- Include the explicit generation date and time exactly as given.",
      "- Keep the output concise and structured with headings and bullet points.",
      "- Do not invent facts that are not present in the supplied data.",
      "",
      "# Runtime Paths",
      "",
      "Runtime paths summary",
      "",
      "# Structured Facts",
      "",
      "# Result: 001-first.md",
      "",
      "## Summary",
      "",
      "- Generated at: `2026-06-08T03:00:02+00:00`",
      "- Status: `completed`",
      "- Prompt path: `/repo/prompts/001-first.md`",
      "- Result path: `/repo/results/001-first_RESULT.md`",
      "- Session id: `session-123`",
      "- Watcher backend: `polling`",
      "- Started at: `2026-06-08T03:00:00+00:00`",
      "- Completed at: `2026-06-08T03:00:01+00:00`",
      "- Queue sort key: `(0, '001-first.md', '001-first.md')`"
    ].join("\n") + "\n"
  );
});

test("daemonResultReportAuthoringDecision falls back without a CLI", () => {
  assert.deepEqual(
    daemonResultReportAuthoringDecision({
      generatedAt: "2026-06-08T03:00:02+00:00",
      runtimePathsText: "Runtime paths summary",
      cliPath: null,
      repoRoot: "/repo",
      result: {
        prompt_path: "/repo/prompts/001-first.md",
        result_path: "/repo/results/001-first_RESULT.md",
        status: "completed",
        started_at: "2026-06-08T03:00:00+00:00",
        completed_at: "2026-06-08T03:00:01+00:00",
        watcher_backend: "polling",
        sort_key: [0, "001-first.md", "001-first.md"],
        session_id: "session-123"
      }
    }),
    {
      action: "fallback_markdown",
      promptText: null,
      cliPath: null,
      repoRoot: "/repo",
      workdir: "/repo",
      runLabel: null,
      generatedAt: "2026-06-08T03:00:02+00:00",
      reason: "active_agent_cli_missing"
    }
  );
});

test("daemonResultReportAuthoredOutputDecision validates authored markdown", () => {
  assert.deepEqual(
    daemonResultReportAuthoredOutputDecision({
      stdoutText: [
        "# CLI Authored Result",
        "",
        "- Generated at: `2026-06-08T03:00:02+00:00`"
      ].join("\n"),
      stderrText: "ignored",
      generatedAt: "2026-06-08T03:00:02+00:00",
      promptName: "001-first.md"
    }),
    {
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
  assert.deepEqual(
    daemonResultReportAuthoredOutputDecision({
      stdoutText: "   ",
      stderrText: "",
      generatedAt: "2026-06-08T03:00:02+00:00",
      promptName: "001-first.md"
    }),
    {
      action: "error",
      authoredMarkdown: null,
      errorMessage:
        "Configured CLI returned no result report content for 001-first.md.",
      reason: "authored_output_empty"
    }
  );
  assert.deepEqual(
    daemonResultReportAuthoredOutputDecision({
      stdoutText: "# Invalid Result",
      stderrText: null,
      generatedAt: "2026-06-08T03:00:02+00:00",
      promptName: "001-first.md"
    }),
    {
      action: "error",
      authoredMarkdown: null,
      errorMessage:
        "Configured CLI result report did not preserve the required generated-at timestamp.",
      reason: "authored_output_missing_generated_at"
    }
  );
});

test("daemonResultArtifactRefDecision projects existing report refs", () => {
  assert.deepEqual(
    daemonResultArtifactRefDecision({
      resultPath: "/repo/results/001-first_RESULT.md",
      resultExists: true,
      createdAt: "2026-06-08T04:00:00+00:00",
      daemonRunId: "daemon:run-1",
      latestRunId: "agent:run-1",
      sessionId: "session-1"
    }),
    {
      action: "reference",
      artifactRef: {
        kind: "result_report",
        path: "/repo/results/001-first_RESULT.md",
        label: "result_report",
        contentType: "text/markdown",
        createdAt: "2026-06-08T04:00:00+00:00",
        runId: "daemon:run-1",
        role: "daemon",
        stageName: "daemon",
        sessionId: "session-1"
      },
      reason: "result_report_referenced"
    }
  );
});

test("daemonResultArtifactRefDecision skips missing report refs", () => {
  assert.deepEqual(
    daemonResultArtifactRefDecision({
      resultPath: "/repo/results/001-first_RESULT.md",
      resultExists: false,
      createdAt: null,
      daemonRunId: null,
      latestRunId: "agent:run-1",
      sessionId: null
    }),
    {
      action: "skip",
      artifactRef: null,
      reason: "result_report_missing"
    }
  );
});

test("daemonRunFinishedDecision projects run finished metadata", () => {
  assert.deepEqual(
    daemonRunFinishedDecision({
      attemptsCompleted: 2.8,
      retriesUsed: 1,
      supervisorVerdict: " approved ",
      outcome: "completed",
      error: ""
    }),
    {
      eventType: "run.finished",
      role: "daemon",
      stage: "daemon",
      status: "completed",
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

test("daemonPromptCompletionLineDecision projects final progress output", () => {
  assert.deepEqual(
    daemonPromptCompletionLineDecision({
      promptName: " 001-first.md ",
      status: " completed ",
      resultPath: " /repo/results/001-first_RESULT.md "
    }),
    {
      line: "daemon prompt 001-first.md: completed -> /repo/results/001-first_RESULT.md",
      promptName: "001-first.md",
      status: "completed",
      resultPath: "/repo/results/001-first_RESULT.md",
      reason: "daemon_prompt_completion_line_projected"
    }
  );
});

test("daemonPromptInterruptionDecision projects interruption recovery output", () => {
  assert.deepEqual(
    daemonPromptInterruptionDecision({
      promptName: " 001-interrupt.md "
    }),
    {
      status: "interrupted",
      errorMessage: "Interrupted by user.",
      logMessage: "daemon prompt 001-interrupt.md: interrupted by user; preserving source prompt file",
      preservePrompt: true,
      reason: "daemon_prompt_interrupted"
    }
  );
});

test("daemonRoadmapPhaseDecision selects the first active phase", () => {
  assert.deepEqual(
    daemonRoadmapPhaseDecision({
      activePhaseIds: ["", 42, "phase_5", "phase_6"]
    }),
    {
      expectedRoadmapPhaseId: "phase_5",
      reason: "active_phase_selected"
    }
  );
});

test("daemonRoadmapPhaseDecision falls back to phase 4", () => {
  assert.deepEqual(
    daemonRoadmapPhaseDecision({
      activePhaseIds: [null, "", "   "]
    }),
    {
      expectedRoadmapPhaseId: "phase_4",
      reason: "default_phase_selected"
    }
  );
});

test("daemonGoalSourceDecision extracts scheduler metadata", () => {
  assert.deepEqual(
    daemonGoalSourceDecision({
      promptText: [
        "<!-- dormammu:goal_source=/repo/goals/ship-it.md -->",
        "",
        "# Goal",
        "",
        "Ship it"
      ].join("\n")
    }),
    {
      goalSourcePath: "/repo/goals/ship-it.md",
      reason: "goal_source_found"
    }
  );
});

test("daemonGoalSourceDecision reports missing scheduler metadata", () => {
  assert.deepEqual(
    daemonGoalSourceDecision({
      promptText: "# Goal\n\nShip it"
    }),
    {
      goalSourcePath: null,
      reason: "goal_source_missing"
    }
  );
});

test("daemonAgentCliDecision uses configured active agent CLI", () => {
  assert.deepEqual(
    daemonAgentCliDecision({
      activeAgentCli: "/usr/local/bin/codex"
    }),
    {
      action: "use",
      agentCli: "/usr/local/bin/codex",
      errorMessage: null,
      reason: "active_agent_cli_configured"
    }
  );
});

test("daemonAgentCliDecision reports missing active agent CLI", () => {
  assert.deepEqual(
    daemonAgentCliDecision({
      activeAgentCli: null
    }),
    {
      action: "error",
      agentCli: null,
      errorMessage: [
        "daemonize requires active_agent_cli in dormammu.json or ~/.dormammu/config. ",
        "It now reuses the normal dormammu run loop instead of per-phase daemon CLI settings."
      ].join(""),
      reason: "active_agent_cli_missing"
    }
  );
});

test("daemonTerminalErrorDecision projects retry exhaustion details", () => {
  assert.deepEqual(
    daemonTerminalErrorDecision({
      status: "failed",
      nextPendingTask: " Phase 2. Validate "
    }),
    {
      status: "failed",
      nextPendingTask: "Phase 2. Validate",
      message: [
        "Loop retry budget was exhausted before PLAN.md completed.",
        " Next pending PLAN task: Phase 2. Validate."
      ].join(""),
      reason: "retry_budget_exhausted"
    }
  );
});

test("daemonTerminalErrorDecision projects blocked and fallback statuses", () => {
  assert.deepEqual(
    daemonTerminalErrorDecision({
      status: "blocked",
      nextPendingTask: null
    }).message,
    "Loop stopped because the configured coding-agent CLIs were blocked."
  );
  assert.deepEqual(
    daemonTerminalErrorDecision({
      status: "interrupted",
      nextPendingTask: ""
    }),
    {
      status: "interrupted",
      nextPendingTask: null,
      message: "Loop finished with terminal status: interrupted.",
      reason: "terminal_status_fallback"
    }
  );
});

test("daemonResultStatusDecision extracts rendered result statuses", () => {
  assert.deepEqual(
    daemonResultStatusDecision({
      resultText: "# Result\n\n- Status: ` completed `\n"
    }),
    {
      status: "completed",
      reason: "status_line_found"
    }
  );
});

test("daemonResultStatusDecision returns null when status is missing", () => {
  assert.deepEqual(
    daemonResultStatusDecision({
      resultText: "# Result\n\nNo status yet.\n"
    }),
    {
      status: null,
      reason: "status_line_missing"
    }
  );
});

test("daemonTerminalStatusDecision preserves clean completed evidence", () => {
  assert.deepEqual(
    daemonTerminalStatusDecision({
      status: "completed",
      planAllCompleted: false,
      hasCleanTerminalStageEvidence: true,
      nextPendingTask: "Phase 1"
    }),
    {
      status: "completed",
      error: null,
      preserveCompleted: true,
      reason: "clean_terminal_stage_evidence"
    }
  );
});

test("daemonTerminalStatusDecision fails stale completed plan syncs", () => {
  assert.deepEqual(
    daemonTerminalStatusDecision({
      status: "completed",
      planAllCompleted: null,
      hasCleanTerminalStageEvidence: false,
      nextPendingTask: null
    }),
    {
      status: "failed",
      error: "Loop returned completed but session PLAN.md is not fully complete.",
      preserveCompleted: false,
      reason: "completed_plan_incomplete"
    }
  );
});

test("daemonTerminalStatusDecision projects terminal errors", () => {
  assert.deepEqual(
    daemonTerminalStatusDecision({
      status: "failed",
      planAllCompleted: false,
      hasCleanTerminalStageEvidence: false,
      nextPendingTask: "Phase 2"
    }),
    {
      status: "failed",
      error: [
        "Loop retry budget was exhausted before PLAN.md completed.",
        " Next pending PLAN task: Phase 2."
      ].join(""),
      preserveCompleted: false,
      reason: "terminal_error_status"
    }
  );
});

test("daemonExistingResultDecision removes completed stale result files", () => {
  assert.deepEqual(
    daemonExistingResultDecision({
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      resultExists: true,
      existingResultStatus: " completed "
    }),
    {
      action: "remove",
      removeExistingResult: true,
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      existingResultStatus: "completed",
      reason: "completed_result_reprocess"
    }
  );
});

test("daemonExistingResultDecision keeps non-completed result files", () => {
  assert.deepEqual(
    daemonExistingResultDecision({
      promptPath: "/repo/prompts/001-first.md",
      resultPath: "/repo/results/001-first_RESULT.md",
      resultExists: true,
      existingResultStatus: "failed"
    }).removeExistingResult,
    false
  );
});

test("daemonPromptSettleDecision defers prompts still in the settle window", () => {
  assert.deepEqual(
    daemonPromptSettleDecision({
      promptPath: "/repo/prompts/001-first.md",
      settleSeconds: 5,
      ageSeconds: 2.25
    }),
    {
      action: "defer",
      promptPath: "/repo/prompts/001-first.md",
      retryAfterSeconds: 2.75,
      reason: "settle_window_pending"
    }
  );
});

test("daemonPromptSettleDecision marks old prompts ready", () => {
  assert.deepEqual(
    daemonPromptSettleDecision({
      promptPath: "/repo/prompts/001-first.md",
      settleSeconds: 5,
      ageSeconds: 5
    }),
    {
      action: "ready",
      promptPath: "/repo/prompts/001-first.md",
      retryAfterSeconds: null,
      reason: "settle_window_elapsed"
    }
  );
});

test("daemonQueueFileDecision skips in-progress prompts first", () => {
  assert.deepEqual(
    daemonQueueFileDecision({
      promptPath: "/repo/prompts/001-first.md",
      inProgress: true,
      promptCandidate: true
    }),
    {
      action: "skip",
      promptPath: "/repo/prompts/001-first.md",
      reason: "prompt_in_progress"
    }
  );
});

test("daemonQueueFileDecision skips non-candidate files", () => {
  assert.deepEqual(
    daemonQueueFileDecision({
      promptPath: "/repo/prompts/readme.txt",
      inProgress: false,
      promptCandidate: false
    }),
    {
      action: "skip",
      promptPath: "/repo/prompts/readme.txt",
      reason: "not_prompt_candidate"
    }
  );
});

test("daemonQueueFileDecision inspects ready prompt candidates", () => {
  assert.deepEqual(
    daemonQueueFileDecision({
      promptPath: "/repo/prompts/001-first.md",
      inProgress: false,
      promptCandidate: true
    }),
    {
      action: "inspect",
      promptPath: "/repo/prompts/001-first.md",
      reason: "prompt_ready_for_inspection"
    }
  );
});

test("daemonLoopIterationDecision waits after an idle scan", () => {
  assert.deepEqual(
    daemonLoopIterationDecision({
      processedCount: 0,
      inProgressCount: 0,
      shutdownRequested: false
    }),
    {
      action: "wait",
      heartbeatStatus: "idle",
      waitForChanges: true,
      reason: "no_prompt_processed"
    }
  );
});

test("daemonLoopIterationDecision continues after processed work", () => {
  assert.deepEqual(
    daemonLoopIterationDecision({
      processedCount: 1,
      inProgressCount: 1,
      shutdownRequested: false
    }),
    {
      action: "continue",
      heartbeatStatus: "busy",
      waitForChanges: false,
      reason: "prompt_processed"
    }
  );
});

test("daemonLoopIterationDecision stops when shutdown is requested", () => {
  assert.deepEqual(
    daemonLoopIterationDecision({
      processedCount: 0,
      inProgressCount: 0,
      shutdownRequested: true
    }).action,
    "stop"
  );
});

test("daemonStartupDecision starts configured schedulers", () => {
  assert.deepEqual(
    daemonStartupDecision({
      goalsSchedulerConfigured: true,
      autonomousSchedulerConfigured: false
    }),
    {
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

test("daemonStartupBannerDecision projects startup lines", () => {
  assert.deepEqual(
    daemonStartupBannerDecision({
      repoRoot: "/repo",
      configPath: "/repo/daemonize.json",
      promptPath: "/repo/prompts",
      resultPath: "/repo/results",
      watcherBackend: "polling",
      requestedWatcherBackend: "auto",
      pollIntervalSeconds: 30,
      settleSeconds: 2,
      ignoreHiddenFiles: true,
      allowedExtensions: [".md", ".txt"],
      goalsPath: "/repo/goals",
      goalsIntervalMinutes: 10,
      autonomousEnabled: true,
      autonomousIntervalMinutes: 60,
      autonomousFocus: "tests",
      autonomousMaxQueuedTasks: 2
    }),
    {
      allowedExtensionsDescription: ".md,.txt",
      lines: [
        "=== dormammu daemonize ===",
        "repo root: /repo",
        "daemon config: /repo/daemonize.json",
        "prompt path: /repo/prompts",
        "result path: /repo/results",
        "watcher: polling (requested=auto, poll_interval=30s, settle=2s)",
        [
          "prompt detection: hidden_files=ignore, extensions=.md,.txt, ",
          "replace_completed_result_on_requeued_prompt=yes, ",
          "order=numeric-prefix -> alpha-prefix -> remaining-name"
        ].join(""),
        [
          "prompt lifecycle: each accepted prompt reuses the dormammu run loop ",
          "and writes its result only after the loop reaches a terminal outcome"
        ].join(""),
        "goals: /repo/goals (interval=10m, watching for .md files)",
        "autonomous: enabled (interval=60m, focus=tests, max_queued=2)"
      ],
      reason: "startup_banner_projected"
    }
  );
});

test("daemonStartupBannerDecision projects disabled optional services", () => {
  const decision = daemonStartupBannerDecision({
    repoRoot: "/repo",
    configPath: "/repo/daemonize.json",
    promptPath: "/repo/prompts",
    resultPath: "/repo/results",
    watcherBackend: "inotify",
    requestedWatcherBackend: "inotify",
    pollIntervalSeconds: 60,
    settleSeconds: 3,
    ignoreHiddenFiles: false,
    allowedExtensions: [],
    goalsPath: null,
    goalsIntervalMinutes: null,
    autonomousEnabled: false,
    autonomousIntervalMinutes: null,
    autonomousFocus: null,
    autonomousMaxQueuedTasks: null
  });

  assert.equal(decision.allowedExtensionsDescription, "any");
  assert.equal(decision.lines.at(-2), "goals: disabled");
  assert.equal(decision.lines.at(-1), "autonomous: disabled");
});

test("daemonShutdownDecision projects cleanup actions", () => {
  assert.deepEqual(
    daemonShutdownDecision({
      goalsSchedulerConfigured: true,
      autonomousSchedulerConfigured: true,
      progressLogActive: true
    }),
    {
      action: "shutdown",
      stopGoalsScheduler: true,
      stopAutonomousScheduler: true,
      closeWatcher: true,
      removeHeartbeat: true,
      closeProgressLog: true,
      reason: "daemon_shutdown"
    }
  );
});

test("daemonInstanceLockDecision skips on platforms without fcntl", () => {
  assert.deepEqual(
    daemonInstanceLockDecision({
      fcntlAvailable: false,
      lockAcquired: false,
      promptPath: "/repo/prompts",
      existingPid: null
    }),
    {
      action: "skip",
      writePidFile: false,
      errorMessage: null,
      reason: "fcntl_unavailable"
    }
  );
});

test("daemonInstanceLockDecision holds acquired locks", () => {
  assert.deepEqual(
    daemonInstanceLockDecision({
      fcntlAvailable: true,
      lockAcquired: true,
      promptPath: "/repo/prompts",
      existingPid: null
    }),
    {
      action: "hold",
      writePidFile: true,
      errorMessage: null,
      reason: "instance_lock_acquired"
    }
  );
});

test("daemonInstanceLockDecision rejects busy locks with pid context", () => {
  assert.deepEqual(
    daemonInstanceLockDecision({
      fcntlAvailable: true,
      lockAcquired: false,
      promptPath: "/repo/prompts",
      existingPid: "1234"
    }),
    {
      action: "reject",
      writePidFile: false,
      errorMessage: [
        "Another dormammu daemon is already running against "
          + "/repo/prompts (existing daemon PID: 1234).",
        "Stop it first or use a different prompt_path."
      ].join("\n"),
      reason: "instance_lock_busy"
    }
  );
});

test("daemonInstanceUnlockDecision projects release cleanup", () => {
  assert.deepEqual(
    daemonInstanceUnlockDecision({
      fcntlAvailable: true,
      lockHeld: true
    }),
    {
      action: "release",
      unlockFcntl: true,
      closeLockFile: true,
      clearPidLockFile: true,
      removePidFile: true,
      reason: "instance_lock_release"
    }
  );
});

test("daemonHeartbeatWriteDecision projects heartbeat payloads", () => {
  assert.deepEqual(
    daemonHeartbeatWriteDecision({
      heartbeatPathConfigured: true,
      pid: 42,
      status: "busy",
      timestamp: "2026-06-08T03:10:00+00:00"
    }),
    {
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

test("daemonHeartbeatWriteDecision skips unconfigured paths", () => {
  assert.deepEqual(
    daemonHeartbeatWriteDecision({
      heartbeatPathConfigured: false,
      pid: 42,
      status: "idle",
      timestamp: "2026-06-08T03:10:00+00:00"
    }),
    {
      action: "skip",
      ensureParent: false,
      heartbeatPayload: null,
      reason: "heartbeat_path_unconfigured"
    }
  );
});

test("daemonHeartbeatRemoveDecision removes configured heartbeat paths", () => {
  assert.deepEqual(
    daemonHeartbeatRemoveDecision({
      heartbeatPathConfigured: true
    }),
    {
      action: "remove",
      removeHeartbeat: true,
      reason: "heartbeat_remove"
    }
  );
});

test("daemonWatcherBackendDecision uses requested polling", () => {
  assert.deepEqual(
    daemonWatcherBackendDecision({
      requestedBackend: "polling",
      inotifyAvailable: true
    }),
    {
      action: "use",
      backend: "polling",
      errorMessage: null,
      reason: "polling_requested"
    }
  );
});

test("daemonWatcherBackendDecision maps auto to available inotify", () => {
  assert.deepEqual(
    daemonWatcherBackendDecision({
      requestedBackend: "auto",
      inotifyAvailable: true
    }),
    {
      action: "use",
      backend: "inotify",
      errorMessage: null,
      reason: "auto_prefers_inotify"
    }
  );
});

test("daemonWatcherBackendDecision rejects unavailable inotify", () => {
  assert.deepEqual(
    daemonWatcherBackendDecision({
      requestedBackend: "inotify",
      inotifyAvailable: false
    }),
    {
      action: "error",
      backend: null,
      errorMessage: "Inotify backend is not available on this platform.",
      reason: "inotify_unavailable"
    }
  );
});

test("daemonWatcherWaitDecision waits only when requested and active", () => {
  assert.deepEqual(
    daemonWatcherWaitDecision({
      waitRequested: true,
      shutdownRequested: false,
      watcherBackend: "polling"
    }),
    {
      action: "wait",
      waitForChanges: true,
      watcherBackend: "polling",
      reason: "wait_requested"
    }
  );
});

test("daemonWatcherWaitDecision skips when shutdown is requested", () => {
  assert.deepEqual(
    daemonWatcherWaitDecision({
      waitRequested: true,
      shutdownRequested: true,
      watcherBackend: ""
    }),
    {
      action: "skip",
      waitForChanges: false,
      watcherBackend: "unknown",
      reason: "shutdown_requested"
    }
  );
});
