import assert from "node:assert/strict";
import test from "node:test";

import {
  daemonHeartbeatRemoveDecision,
  daemonHeartbeatWriteDecision,
  daemonInstanceLockDecision,
  daemonInstanceUnlockDecision,
  daemonLoopIterationDecision,
  daemonPendingDecision,
  daemonPromptRouteDecision,
  daemonShutdownDecision,
  daemonStartupDecision,
  daemonWatcherBackendDecision
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
