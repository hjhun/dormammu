import assert from "node:assert/strict";
import test from "node:test";

import {
  daemonExistingResultDecision,
  daemonHeartbeatRemoveDecision,
  daemonHeartbeatWriteDecision,
  daemonInstanceLockDecision,
  daemonInstanceUnlockDecision,
  daemonLoopIterationDecision,
  daemonPendingDecision,
  daemonPromptLifecycleDecision,
  daemonPromptPathDecision,
  daemonPromptRouteDecision,
  daemonPromptSettleDecision,
  daemonQueueFileDecision,
  daemonResultArtifactRefDecision,
  daemonResultReportDecision,
  daemonResultStatusDecision,
  daemonRoadmapPhaseDecision,
  daemonRunFinishedDecision,
  daemonShutdownDecision,
  daemonStartupDecision,
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
